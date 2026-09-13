"""Processamento de audio: pitch, ganho, normalizacao, cortes e mixagem.

Tudo aqui opera em `np.ndarray` float32 mono, na faixa [-1, 1]. Manter esse
contrato unico evita conversoes espalhadas pelo resto do codigo.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import wave
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

try:  # scipy da um resampler de qualidade; sem ele caimos para interpolacao linear
    from scipy.signal import lfilter, resample_poly

    _HAS_SCIPY = True
    _HAS_LFILTER = True
except ImportError:  # pragma: no cover - caminho de fallback
    _HAS_SCIPY = False
    _HAS_LFILTER = False


EPS = 1e-12


# --------------------------------------------------------------------------
# Utilidades basicas
# --------------------------------------------------------------------------


def as_mono_float32(x: np.ndarray) -> np.ndarray:
    """Normaliza qualquer entrada para mono float32 contiguo."""
    x = np.asarray(x)
    if x.ndim > 1:
        # (canais, amostras) ou (amostras, canais) -> media dos canais
        axis = 0 if x.shape[0] < x.shape[-1] else -1
        x = x.mean(axis=axis)
    if x.dtype == np.int16:
        x = x.astype(np.float32) / 32768.0
    elif x.dtype == np.int32:
        x = x.astype(np.float32) / 2147483648.0
    return np.ascontiguousarray(x, dtype=np.float32)


def db_to_lin(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def lin_to_db(x: float) -> float:
    return float(20.0 * np.log10(max(abs(x), EPS)))


def apply_gain_db(x: np.ndarray, db: float) -> np.ndarray:
    if abs(db) < 1e-6:
        return x
    return (x * db_to_lin(db)).astype(np.float32)


def silence(seconds: float, sr: int) -> np.ndarray:
    n = max(0, int(round(seconds * sr)))
    return np.zeros(n, dtype=np.float32)


def duration(x: np.ndarray, sr: int) -> float:
    return len(x) / float(sr) if sr else 0.0


# --------------------------------------------------------------------------
# Resample
# --------------------------------------------------------------------------


def resample(x: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """Reamostra preservando a duracao em segundos."""
    if sr_from == sr_to or len(x) == 0:
        return x
    if _HAS_SCIPY:
        ratio = Fraction(int(sr_to), int(sr_from)).limit_denominator(1000)
        return np.ascontiguousarray(
            resample_poly(x, ratio.numerator, ratio.denominator).astype(np.float32)
        )
    n_out = int(round(len(x) * sr_to / sr_from))
    idx = np.linspace(0, len(x) - 1, n_out, dtype=np.float64)
    return np.interp(idx, np.arange(len(x)), x).astype(np.float32)


# --------------------------------------------------------------------------
# Phase vocoder: time-stretch e pitch shift independentes
# --------------------------------------------------------------------------


def _stft(x: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    win = np.hanning(n_fft + 1)[:-1].astype(np.float32)
    padded = np.pad(x, (n_fft // 2, n_fft // 2), mode="reflect")
    n_frames = 1 + (len(padded) - n_fft) // hop
    if n_frames <= 0:
        return np.zeros((n_fft // 2 + 1, 0), dtype=np.complex64)
    # Janelamento vetorizado via stride tricks, bem mais rapido que um loop.
    frames = np.lib.stride_tricks.sliding_window_view(padded, n_fft)[::hop][:n_frames]
    return np.fft.rfft(frames * win, axis=1).astype(np.complex64).T


def _istft(spec: np.ndarray, n_fft: int, hop: int, length: int | None = None) -> np.ndarray:
    win = np.hanning(n_fft + 1)[:-1].astype(np.float32)
    n_frames = spec.shape[1]
    if n_frames == 0:
        return np.zeros(0, dtype=np.float32)
    frames = np.fft.irfft(spec, n=n_fft, axis=0).T.astype(np.float32) * win

    out_len = n_fft + hop * (n_frames - 1)
    out = np.zeros(out_len, dtype=np.float32)
    norm = np.zeros(out_len, dtype=np.float32)
    win_sq = win**2
    for i in range(n_frames):
        start = i * hop
        out[start : start + n_fft] += frames[i]
        norm[start : start + n_fft] += win_sq

    out /= np.maximum(norm, 1e-8)
    out = out[n_fft // 2 : len(out) - n_fft // 2]
    if length is not None:
        out = out[:length] if len(out) >= length else np.pad(out, (0, length - len(out)))
    return out.astype(np.float32)


def time_stretch(x: np.ndarray, rate: float, n_fft: int = 2048, hop: int = 512) -> np.ndarray:
    """Muda a duracao sem alterar o pitch. rate > 1 encurta, rate < 1 alonga."""
    if abs(rate - 1.0) < 1e-4 or len(x) < n_fft:
        return x

    spec = _stft(x, n_fft, hop)
    n_bins, n_frames = spec.shape
    if n_frames < 2:
        return x

    steps = np.arange(0, n_frames - 1, rate, dtype=np.float64)
    out = np.zeros((n_bins, len(steps)), dtype=np.complex64)

    # Avanco de fase esperado por bin entre dois frames consecutivos.
    phi_advance = hop * 2.0 * np.pi * np.arange(n_bins) / n_fft
    phase_acc = np.angle(spec[:, 0]).astype(np.float64)

    mag = np.abs(spec)
    ang = np.angle(spec)

    for t, step in enumerate(steps):
        i = int(step)
        frac = step - i
        # Magnitude interpolada entre os dois frames vizinhos.
        out[:, t] = ((1.0 - frac) * mag[:, i] + frac * mag[:, i + 1]) * np.exp(1j * phase_acc)
        # Desvio de fase real em relacao ao avanco esperado, enrolado em [-pi, pi].
        dphi = ang[:, i + 1] - ang[:, i] - phi_advance
        dphi -= 2.0 * np.pi * np.round(dphi / (2.0 * np.pi))
        phase_acc += phi_advance + dphi

    return _istft(out, n_fft, hop)


def pitch_shift(x: np.ndarray, sr: int, semitones: float) -> np.ndarray:
    """Muda o pitch em semitons mantendo a duracao original."""
    if abs(semitones) < 1e-3 or len(x) == 0:
        return x
    rate = 2.0 ** (-float(semitones) / 12.0)
    stretched = time_stretch(x, rate)
    # Reamostrar de sr/rate para sr devolve a duracao original com o pitch deslocado.
    shifted = resample(stretched, int(round(sr / rate)), sr)
    return shifted.astype(np.float32)


# --------------------------------------------------------------------------
# Filtros de timbre (biquads RBJ)
# --------------------------------------------------------------------------


def _biquad(x: np.ndarray, b: np.ndarray, a: np.ndarray) -> np.ndarray:
    """Aplica um biquad. Usa lfilter quando ha scipy; o loop e o fallback."""
    if _HAS_LFILTER:
        return lfilter(b, np.concatenate(([1.0], a)), x).astype(np.float32)

    # Direct Form I. Bem mais lento, mas mantem a aplicacao funcional sem scipy.
    y = np.zeros_like(x)
    x1 = x2 = y1 = y2 = 0.0
    b0, b1, b2 = b
    a1, a2 = a
    for n in range(len(x)):
        xn = float(x[n])
        yn = b0 * xn + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1 = x1, xn
        y2, y1 = y1, yn
        y[n] = yn
    return y.astype(np.float32)


def _shelf(x: np.ndarray, sr: int, freq: float, gain_db: float, high: bool) -> np.ndarray:
    if abs(gain_db) < 1e-3 or len(x) == 0:
        return x
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * freq / sr
    cos_w0, sin_w0 = np.cos(w0), np.sin(w0)
    alpha = sin_w0 / 2.0 * np.sqrt((A + 1.0 / A) * (1.0 / 0.9 - 1.0) + 2.0)
    two_sqrtA_alpha = 2.0 * np.sqrt(A) * alpha

    if high:
        b0 = A * ((A + 1) + (A - 1) * cos_w0 + two_sqrtA_alpha)
        b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
        b2 = A * ((A + 1) + (A - 1) * cos_w0 - two_sqrtA_alpha)
        a0 = (A + 1) - (A - 1) * cos_w0 + two_sqrtA_alpha
        a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
        a2 = (A + 1) - (A - 1) * cos_w0 - two_sqrtA_alpha
    else:
        b0 = A * ((A + 1) - (A - 1) * cos_w0 + two_sqrtA_alpha)
        b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
        b2 = A * ((A + 1) - (A - 1) * cos_w0 - two_sqrtA_alpha)
        a0 = (A + 1) + (A - 1) * cos_w0 + two_sqrtA_alpha
        a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
        a2 = (A + 1) + (A - 1) * cos_w0 - two_sqrtA_alpha

    b = np.array([b0, b1, b2]) / a0
    a = np.array([a1, a2]) / a0
    return _biquad(x, b, a)


def tone(x: np.ndarray, sr: int, warmth_db: float = 0.0, brightness_db: float = 0.0) -> np.ndarray:
    """Ajuste rapido de timbre: graves em 220 Hz, agudos em 3.5 kHz."""
    out = _shelf(x, sr, 220.0, warmth_db, high=False)
    return _shelf(out, sr, 3500.0, brightness_db, high=True)


def _pass(x: np.ndarray, sr: int, freq: float, high: bool, q: float = 0.707) -> np.ndarray:
    """Passa-alta ou passa-baixa de 2a ordem (RBJ)."""
    if len(x) == 0:
        return x
    freq = float(np.clip(freq, 20.0, sr * 0.45))
    w0 = 2.0 * np.pi * freq / sr
    cos_w0, alpha = np.cos(w0), np.sin(w0) / (2.0 * q)

    if high:
        b0, b1, b2 = (1 + cos_w0) / 2, -(1 + cos_w0), (1 + cos_w0) / 2
    else:
        b0, b1, b2 = (1 - cos_w0) / 2, 1 - cos_w0, (1 - cos_w0) / 2
    a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha

    return _biquad(x, np.array([b0, b1, b2]) / a0, np.array([a1, a2]) / a0)


def bandpass(x: np.ndarray, sr: int, low: float, high: float, poles: int = 2) -> np.ndarray:
    """Deixa passar so a faixa entre `low` e `high`. `poles` empilha biquads."""
    out = x
    for _ in range(max(1, poles)):
        out = _pass(out, sr, low, high=True)
        out = _pass(out, sr, high, high=False)
    return out


# --------------------------------------------------------------------------
# Dinamica e limpeza
# --------------------------------------------------------------------------


def peak_normalize(x: np.ndarray, target_dbfs: float = -1.0) -> np.ndarray:
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak < EPS:
        return x
    return (x * (db_to_lin(target_dbfs) / peak)).astype(np.float32)


def rms_normalize(x: np.ndarray, target_dbfs: float = -20.0, ceiling_dbfs: float = -1.0) -> np.ndarray:
    """Iguala o volume percebido entre vozes diferentes, sem estourar o pico."""
    if len(x) == 0:
        return x
    rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
    if rms < EPS:
        return x
    gain = db_to_lin(target_dbfs) / rms
    peak = float(np.max(np.abs(x)))
    if peak * gain > db_to_lin(ceiling_dbfs):
        gain = db_to_lin(ceiling_dbfs) / peak
    return (x * gain).astype(np.float32)


def trim_silence(x: np.ndarray, sr: int, threshold_db: float = -45.0, pad_ms: float = 40.0) -> np.ndarray:
    """Corta silencio das pontas, deixando uma pequena folga."""
    if len(x) == 0:
        return x
    frame = max(1, int(sr * 0.01))
    n_frames = len(x) // frame
    if n_frames < 2:
        return x
    frames = x[: n_frames * frame].reshape(n_frames, frame)
    energy = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    peak = float(energy.max())
    if peak < EPS:
        return x
    loud = np.where(energy > peak * db_to_lin(threshold_db))[0]
    if len(loud) == 0:
        return x
    pad = int(sr * pad_ms / 1000.0)
    start = max(0, loud[0] * frame - pad)
    end = min(len(x), (loud[-1] + 1) * frame + pad)
    return x[start:end]


def fade(x: np.ndarray, sr: int, fade_in_ms: float = 8.0, fade_out_ms: float = 12.0) -> np.ndarray:
    """Rampas curtas nas bordas evitam cliques ao emendar as falas."""
    if len(x) == 0:
        return x
    out = x.copy()
    n_in = min(int(sr * fade_in_ms / 1000.0), len(out))
    n_out = min(int(sr * fade_out_ms / 1000.0), len(out))
    if n_in > 1:
        out[:n_in] *= np.linspace(0.0, 1.0, n_in, dtype=np.float32)
    if n_out > 1:
        out[-n_out:] *= np.linspace(1.0, 0.0, n_out, dtype=np.float32)
    return out


def soft_limit(x: np.ndarray, ceiling_dbfs: float = -0.5) -> np.ndarray:
    """Saturacao suave em tanh; segura picos sem o clique do clip duro."""
    ceiling = db_to_lin(ceiling_dbfs)
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak <= ceiling:
        return x
    return (np.tanh(x / ceiling) * ceiling).astype(np.float32)


# --------------------------------------------------------------------------
# Primitivas de efeito
# --------------------------------------------------------------------------


def mix(dry: np.ndarray, wet: np.ndarray, amount: float) -> np.ndarray:
    """Mistura sinal limpo e processado. amount=0 devolve o limpo, 1 o processado."""
    amount = float(np.clip(amount, 0.0, 1.0))
    n = min(len(dry), len(wet))
    if n == 0:
        return dry
    return ((1.0 - amount) * dry[:n] + amount * wet[:n]).astype(np.float32)


def robotize(x: np.ndarray, sr: int, n_fft: int = 1024, hop: int = 256) -> np.ndarray:
    """Voz robotica classica: descarta a fase da STFT e ressintetiza.

    Sem a fase original, todos os frames passam a se somar em fase, o que
    substitui a entonacao por um zumbido constante em sr/hop Hz — o efeito
    "robo" de sintetizador, mantendo os formantes (e a inteligibilidade).
    """
    if len(x) < n_fft:
        return x
    spec = _stft(x, n_fft, hop)
    # Magnitude como numero real puro = fase zerada em todos os bins.
    return _istft(np.abs(spec).astype(np.complex64), n_fft, hop, length=len(x))


def ring_mod(x: np.ndarray, sr: int, freq: float = 55.0) -> np.ndarray:
    """Modulacao em anel: multiplica por uma senoide, gerando bandas laterais."""
    if len(x) == 0:
        return x
    t = np.arange(len(x), dtype=np.float32) / sr
    return (x * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def bitcrush(x: np.ndarray, sr: int, bits: int = 8, downsample: int = 1) -> np.ndarray:
    """Reduz resolucao de amplitude e/ou taxa de amostragem (lo-fi digital)."""
    out = x
    if downsample > 1:
        # Sample-and-hold: segura cada amostra por `downsample` posicoes.
        held = out[::downsample]
        out = np.repeat(held, downsample)[: len(x)].astype(np.float32)
        if len(out) < len(x):
            out = np.pad(out, (0, len(x) - len(out)))
    if bits < 16:
        levels = float(2 ** max(1, bits))
        out = (np.round(out * levels) / levels).astype(np.float32)
    return out


def comb(x: np.ndarray, sr: int, delay_ms: float = 8.0, feedback: float = 0.55) -> np.ndarray:
    """Filtro pente: ressonancia metalica, o "corpo de lata" do robo."""
    d = max(1, int(sr * delay_ms / 1000.0))
    if len(x) <= d:
        return x
    out = x.astype(np.float32).copy()
    fb = float(np.clip(feedback, 0.0, 0.95))
    # Recursivo por blocos do tamanho do atraso: cada bloco so depende do anterior.
    for start in range(d, len(out), d):
        stop = min(start + d, len(out))
        out[start:stop] += fb * out[start - d : stop - d]
    peak = float(np.max(np.abs(out)))
    return (out / peak * float(np.max(np.abs(x)))).astype(np.float32) if peak > 1.0 else out


def detune_stack(x: np.ndarray, sr: int, cents: tuple[float, ...] = (-12.0, 12.0)) -> np.ndarray:
    """Empilha copias levemente desafinadas: engrossa e "sintetiza" a voz."""
    layers = [x]
    for c in cents:
        layers.append(pitch_shift(x, sr, c / 100.0))
    n = min(len(layer) for layer in layers)
    stacked = np.sum([layer[:n] for layer in layers], axis=0) / len(layers)
    return stacked.astype(np.float32)


def add_noise(x: np.ndarray, level_db: float = -34.0, seed: int = 0) -> np.ndarray:
    """Chiado de fundo, para radio e transmissao antiga."""
    if len(x) == 0:
        return x
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(len(x)).astype(np.float32) * db_to_lin(level_db)
    return (x + noise).astype(np.float32)


def saturate(x: np.ndarray, drive: float = 3.0) -> np.ndarray:
    """Saturacao por tanh: o "esgoelado" de megafone e alto-falante pequeno."""
    drive = max(1.0, float(drive))
    return (np.tanh(x * drive) / np.tanh(drive)).astype(np.float32)


# --------------------------------------------------------------------------
# Montagem da timeline
# --------------------------------------------------------------------------


@dataclass
class Segment:
    """Uma fala ja renderizada, posicionada na linha do tempo final."""

    audio: np.ndarray
    gap_after: float = 0.6
    label: str = ""


def assemble(segments: list[Segment], sr: int, lead_in: float = 0.0, lead_out: float = 0.0) -> tuple[np.ndarray, list[dict]]:
    """Concatena falas com as pausas pedidas e devolve o mapa de tempos."""
    parts: list[np.ndarray] = []
    marks: list[dict] = []
    cursor = 0.0

    if lead_in > 0:
        parts.append(silence(lead_in, sr))
        cursor += lead_in

    for i, seg in enumerate(segments):
        start = cursor
        parts.append(seg.audio)
        cursor += duration(seg.audio, sr)
        marks.append({"index": i, "label": seg.label, "start": round(start, 3), "end": round(cursor, 3)})
        gap = seg.gap_after if i < len(segments) - 1 else 0.0
        if gap > 0:
            parts.append(silence(gap, sr))
            cursor += gap

    if lead_out > 0:
        parts.append(silence(lead_out, sr))

    mixed = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    return mixed.astype(np.float32), marks


# --------------------------------------------------------------------------
# Entrada e saida de arquivos
# --------------------------------------------------------------------------


def write_wav(path, x: np.ndarray, sr: int) -> None:
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def wav_bytes(x: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def read_audio(path) -> tuple[np.ndarray, int]:
    """Le um arquivo de audio. Usa soundfile quando disponivel, senao wave."""
    try:
        import soundfile as sf

        data, sr = sf.read(str(path), dtype="float32", always_2d=False)
        return as_mono_float32(data), int(sr)
    except ImportError:
        with wave.open(str(path), "rb") as w:
            sr = w.getframerate()
            raw = w.readframes(w.getnframes())
            data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            if w.getnchannels() > 1:
                data = data.reshape(-1, w.getnchannels()).mean(axis=1)
        return np.ascontiguousarray(data, dtype=np.float32), sr


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def write_mp3(path, x: np.ndarray, sr: int, bitrate: str = "192k") -> bool:
    """Converte via ffmpeg. Devolve False se o ffmpeg nao estiver instalado."""
    if not has_ffmpeg():
        return False
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
            "-codec:a", "libmp3lame", "-b:a", bitrate, str(path),
        ],
        input=(np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes(),
        capture_output=True,
    )
    return proc.returncode == 0
