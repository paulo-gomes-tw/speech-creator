"""Testes do processamento de audio."""

from __future__ import annotations

import numpy as np
import pytest

from app import audio as A


def tone(freq: float = 220.0, seconds: float = 1.0, sr: int = 24000) -> np.ndarray:
    t = np.linspace(0, seconds, int(seconds * sr), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def dominant_freq(x: np.ndarray, sr: int) -> float:
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / sr)[int(np.argmax(spectrum))])


def test_as_mono_converte_estereo_e_inteiros():
    assert A.as_mono_float32(np.zeros((2, 100))).shape == (100,)
    assert A.as_mono_float32(np.zeros((100, 2))).shape == (100,)
    out = A.as_mono_float32(np.full(10, 16384, dtype=np.int16))
    assert out.dtype == np.float32 and abs(out[0] - 0.5) < 0.01


def test_ganho_em_db():
    x = tone()
    assert np.max(np.abs(A.apply_gain_db(x, 6.0))) == pytest.approx(np.max(np.abs(x)) * 2, rel=0.01)
    assert A.apply_gain_db(x, 0.0) is x  # sem copia desnecessaria


@pytest.mark.parametrize("sr_to", [16000, 44100, 48000])
def test_resample_preserva_duracao_e_frequencia(sr_to):
    sr = 24000
    x = tone(440.0, 1.0, sr)
    out = A.resample(x, sr, sr_to)
    assert abs(len(out) / sr_to - 1.0) < 0.01
    assert dominant_freq(out, sr_to) == pytest.approx(440, abs=5)


@pytest.mark.parametrize("rate", [0.5, 0.8, 1.5, 2.0])
def test_time_stretch_muda_duracao_mantendo_pitch(rate):
    sr = 24000
    x = tone(440.0, 2.0, sr)
    out = A.time_stretch(x, rate)
    assert abs(len(out) / len(x) - 1 / rate) < 0.06
    assert dominant_freq(out, sr) == pytest.approx(440, abs=12)


@pytest.mark.parametrize("semitones", [-12, -5, 4, 7, 12])
def test_pitch_shift_muda_pitch_mantendo_duracao(semitones):
    sr = 24000
    x = tone(440.0, 1.5, sr)
    out = A.pitch_shift(x, sr, semitones)
    esperado = 440.0 * 2 ** (semitones / 12)
    assert abs(len(out) - len(x)) / len(x) < 0.06
    assert dominant_freq(out, sr) == pytest.approx(esperado, rel=0.06)


def test_pitch_shift_zero_nao_altera():
    x = tone()
    assert A.pitch_shift(x, 24000, 0.0) is x


def test_shelf_de_graves_e_agudos():
    sr = 24000
    graves, agudos = tone(120, 1.0, sr), tone(6000, 1.0, sr)
    rms = lambda v: float(np.sqrt(np.mean(v**2)))
    assert rms(A.tone(graves, sr, warmth_db=9.0)) > rms(graves) * 1.4
    assert rms(A.tone(agudos, sr, brightness_db=9.0)) > rms(agudos) * 1.4
    assert rms(A.tone(graves, sr, warmth_db=-9.0)) < rms(graves) * 0.8


def test_normalizacao_por_pico_e_rms():
    x = tone() * 0.1
    assert A.lin_to_db(float(np.max(np.abs(A.peak_normalize(x, -1.0))))) == pytest.approx(-1.0, abs=0.1)
    out = A.rms_normalize(x, -20.0)
    assert A.lin_to_db(float(np.sqrt(np.mean(out**2)))) == pytest.approx(-20.0, abs=0.2)


def test_rms_normalize_respeita_teto():
    x = tone() * 0.001  # exigiria ganho enorme
    out = A.rms_normalize(x, target_dbfs=-3.0, ceiling_dbfs=-1.0)
    assert float(np.max(np.abs(out))) <= A.db_to_lin(-1.0) + 1e-6


def test_trim_silence_corta_as_pontas():
    sr = 24000
    x = np.concatenate([A.silence(1.0, sr), tone(440, 1.0, sr), A.silence(1.0, sr)])
    out = A.trim_silence(x, sr)
    assert 0.9 < A.duration(out, sr) < 1.3


def test_fade_zera_as_bordas():
    out = A.fade(tone(), 24000, 20, 20)
    assert abs(out[0]) < 0.01 and abs(out[-1]) < 0.01


def test_soft_limit_segura_picos():
    out = A.soft_limit(tone() * 4.0, -0.5)
    assert float(np.max(np.abs(out))) <= A.db_to_lin(-0.5) + 1e-6


def test_assemble_posiciona_os_segmentos():
    sr = 24000
    segs = [
        A.Segment(audio=tone(220, 1.0, sr), gap_after=0.5, label="A"),
        A.Segment(audio=tone(330, 2.0, sr), gap_after=0.5, label="B"),
    ]
    mixed, marks = A.assemble(segs, sr, lead_in=1.0, lead_out=2.0)
    # 1.0 + 1.0 + 0.5 + 2.0 + 2.0 (gap final nao entra)
    assert A.duration(mixed, sr) == pytest.approx(6.5, abs=0.01)
    assert marks[0]["start"] == pytest.approx(1.0, abs=0.01)
    assert marks[1]["start"] == pytest.approx(2.5, abs=0.01)
    assert [m["label"] for m in marks] == ["A", "B"]


def test_wav_round_trip(tmp_path):
    sr = 24000
    x = tone(440, 0.5, sr)
    path = tmp_path / "t.wav"
    A.write_wav(path, x, sr)
    back, sr_back = A.read_audio(path)
    assert sr_back == sr and len(back) == len(x)
    assert np.max(np.abs(back - x)) < 0.001


def test_wav_bytes_tem_cabecalho_riff():
    data = A.wav_bytes(tone(), 24000)
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def test_clipping_e_contido_na_escrita(tmp_path):
    path = tmp_path / "c.wav"
    A.write_wav(path, tone() * 10.0, 24000)
    back, _ = A.read_audio(path)
    assert float(np.max(np.abs(back))) <= 1.0
