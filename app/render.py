"""Pipeline de renderizacao: roteiro + elenco -> arquivos de audio."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio as A
from . import config, effects, emotions
from .engines import EngineError, get_engine
from .script_parser import Cue, parse_script, split_long_text

ProgressFn = Callable[[int, int, str], None]


@dataclass
class VoiceSetting:
    """Como um falante do roteiro deve soar."""

    speaker: str = ""
    engine: str = "kokoro"
    voice: str = "af_heart"       # id simples ou mistura "af_heart:0.6+af_bella:0.4"
    ref_audio: str | None = None  # amostra para motores de clonagem
    lang: str | None = None       # sobrescreve o idioma inferido da voz
    speed: float = 1.0
    pitch: float = 0.0            # semitons
    volume: float = 0.0           # dB
    gap: float | None = None      # pausa depois da fala; None herda o padrao do show
    warmth: float = 0.0           # dB de shelf grave
    brightness: float = 0.0       # dB de shelf agudo
    emotion: str = "neutro"       # preset de prosodia (ver app/emotions.py)
    effect: str = "nenhum"        # efeito de voz (ver app/effects.py)
    effect_amount: float | None = None  # 0 a 1; None usa o padrao do efeito
    params: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "VoiceSetting":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (d or {}).items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RenderOptions:
    """Ajustes que valem para o show inteiro."""

    normalize: bool = True       # iguala o volume percebido entre as vozes
    target_dbfs: float = -20.0
    trim: bool = True            # corta silencio das pontas de cada fala
    lead_in: float = 0.5
    lead_out: float = 1.0
    default_gap: float = 0.6
    limit: bool = True           # limitador suave no mix final
    sample_rate: int | None = None
    formats: list[str] = field(default_factory=lambda: ["wav"])
    per_line_files: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "RenderOptions":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (d or {}).items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)


def _resolve(setting: VoiceSetting, overrides: dict[str, float | str]) -> VoiceSetting:
    """Combina configuracao do falante, preset de emocao e ajustes da linha.

    Precedencia, do mais fraco para o mais forte:

    1. a configuracao do falante (o timbre do personagem);
    2. o preset de emocao, aplicado como *delta* sobre ela — assim um
       personagem grave continua grave quando fica com raiva;
    3. os ajustes numericos escritos na propria linha, que sao absolutos.
    """
    emotion_id = overrides.get("emotion", setting.emotion)
    merged = emotions.apply(setting.to_dict(), emotion_id)

    for key, value in overrides.items():
        if key != "emotion" and key in merged:
            merged[key] = value
    return VoiceSetting.from_dict(merged)


def _safe_name(text: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "_" for c in text]
    return "".join(keep)[:40].strip("_") or "fala"


def render_cue(cue: Cue, setting: VoiceSetting, opts: RenderOptions) -> tuple[np.ndarray, int]:
    """Sintetiza uma fala e aplica todo o pos-processamento. Devolve (audio, sr).

    Recebe a configuracao *crua* do falante e resolve emocao e ajustes da linha
    aqui dentro, para que a previa da interface e a renderizacao completa
    passem exatamente pelo mesmo caminho.
    """
    setting = _resolve(setting, cue.overrides)
    engine = get_engine(setting.engine)
    sr = engine.sample_rate

    if len(cue.text) > config.MAX_CHARS_PER_CUE:
        raise EngineError(
            f"Fala da linha {cue.line_no} tem {len(cue.text)} caracteres "
            f"(limite {config.MAX_CHARS_PER_CUE}). Quebre em falas menores."
        )

    from .engines.base import SynthRequest

    pieces: list[np.ndarray] = []
    for chunk in split_long_text(cue.text):
        part = engine.synth(
            SynthRequest(
                text=chunk,
                voice=setting.voice,
                speed=setting.speed,
                lang=setting.lang,
                ref_audio=setting.ref_audio,
                params=setting.params or {},
            )
        )
        if len(part):
            pieces.append(part)

    if not pieces:
        return np.zeros(0, dtype=np.float32), sr

    # Emenda os pedacos com uma respiracao curta, para nao soar colado.
    joined: list[np.ndarray] = []
    for i, piece in enumerate(pieces):
        joined.append(piece)
        if i < len(pieces) - 1:
            joined.append(A.silence(0.12, sr))
    out = np.concatenate(joined).astype(np.float32)

    if opts.trim:
        out = A.trim_silence(out, sr)
    if abs(setting.pitch) > 1e-3:
        out = A.pitch_shift(out, sr, setting.pitch)
    if abs(setting.warmth) > 1e-3 or abs(setting.brightness) > 1e-3:
        out = A.tone(out, sr, setting.warmth, setting.brightness)
    if setting.effect and setting.effect != effects.DEFAULT:
        out = effects.apply(out, sr, setting.effect, setting.effect_amount)
    if opts.normalize:
        out = A.rms_normalize(out, opts.target_dbfs)
    if abs(setting.volume) > 1e-3:
        out = A.apply_gain_db(out, setting.volume)

    out = A.fade(out, sr)

    target_sr = opts.sample_rate or sr
    if target_sr != sr:
        out = A.resample(out, sr, target_sr)
        sr = target_sr
    return out, sr


def render_script(
    script: str,
    cast: dict[str, VoiceSetting],
    opts: RenderOptions,
    out_dir: Path,
    default_setting: VoiceSetting | None = None,
    progress: ProgressFn | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Renderiza o roteiro inteiro e grava os arquivos em `out_dir`.

    Devolve um manifesto com a linha do tempo, os arquivos gerados e os erros
    de cada fala (uma fala que falha nao derruba o show inteiro).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines_dir = out_dir / "falas"
    if opts.per_line_files:
        lines_dir.mkdir(exist_ok=True)

    parsed = parse_script(script)
    speech_cues = [c for c in parsed.cues if c.kind == "speech"]
    total = len(speech_cues)
    if total == 0:
        raise EngineError("O roteiro nao tem nenhuma fala para gerar.")

    fallback = default_setting or VoiceSetting()
    segments: list[A.Segment] = []
    line_records: list[dict] = []
    errors: list[dict] = []
    out_sr: int | None = None
    lead_in = opts.lead_in
    done = 0

    for cue in parsed.cues:
        if cancelled and cancelled():
            raise EngineError("Renderizacao cancelada.")

        if cue.kind == "pause":
            # Uma pausa explicita vira gap do segmento anterior; antes da primeira
            # fala, vira silencio inicial. `opts` nao e mutado: ele pode ser
            # reaproveitado entre renderizacoes.
            if segments:
                segments[-1].gap_after += cue.seconds
            else:
                lead_in += cue.seconds
            continue

        raw = cast.get(cue.speaker, fallback)
        # A resolvida e so para a pausa e o manifesto: quem renderiza e o
        # render_cue, que resolve a partir da crua uma unica vez.
        setting = _resolve(raw, cue.overrides)
        if progress:
            progress(done, total, f"{cue.speaker}: {cue.text[:60]}")

        try:
            wav, sr = render_cue(cue, raw, opts)
            out_sr = sr
        except EngineError as exc:
            errors.append({"index": cue.index, "speaker": cue.speaker, "line_no": cue.line_no, "error": str(exc)})
            done += 1
            continue
        except Exception as exc:  # erro inesperado do motor
            errors.append({
                "index": cue.index, "speaker": cue.speaker, "line_no": cue.line_no,
                "error": f"{type(exc).__name__}: {exc}",
            })
            done += 1
            continue

        # Precedencia: ajuste da linha > configuracao do falante > padrao do show.
        gap = cue.overrides.get("gap")
        if gap is None:
            gap = setting.gap if setting.gap is not None else opts.default_gap
        segments.append(A.Segment(audio=wav, gap_after=float(gap), label=cue.speaker))

        record = {
            "index": cue.index,
            "speaker": cue.speaker,
            "text": cue.text,
            "line_no": cue.line_no,
            "duration": round(A.duration(wav, sr), 3),
            "voice": setting.voice,
            "engine": setting.engine,
            "emotion": setting.emotion,
            "effect": setting.effect,
        }
        if opts.per_line_files:
            fname = f"{len(line_records) + 1:03d}_{_safe_name(cue.speaker)}.wav"
            A.write_wav(lines_dir / fname, wav, sr)
            record["file"] = f"falas/{fname}"
        line_records.append(record)

        done += 1
        if progress:
            progress(done, total, f"{cue.speaker}: {cue.text[:60]}")

    if not segments:
        raise EngineError(
            "Nenhuma fala pode ser gerada. Primeiro erro: "
            + (errors[0]["error"] if errors else "motivo desconhecido")
        )

    sr = out_sr or 24000
    mixed, marks = A.assemble(segments, sr, lead_in=lead_in, lead_out=opts.lead_out)
    if opts.limit:
        mixed = A.soft_limit(mixed)

    files: dict[str, str] = {}
    formats = opts.formats or ["wav"]
    if "wav" in formats:
        A.write_wav(out_dir / "show.wav", mixed, sr)
        files["wav"] = "show.wav"
    if "mp3" in formats:
        if A.write_mp3(out_dir / "show.mp3", mixed, sr):
            files["mp3"] = "show.mp3"
        else:
            # Sem ffmpeg no sistema: garante que ainda exista um arquivo utilizavel.
            if "wav" not in files:
                A.write_wav(out_dir / "show.wav", mixed, sr)
                files["wav"] = "show.wav"
            errors.append({"index": -1, "speaker": "", "line_no": 0,
                           "error": "MP3 nao gerado: ffmpeg nao encontrado no sistema. O WAV foi salvo."})

    for mark, record in zip(marks, line_records):
        record["start"] = mark["start"]
        record["end"] = mark["end"]

    manifest = {
        "sample_rate": sr,
        "duration": round(A.duration(mixed, sr), 3),
        "files": files,
        "lines": line_records,
        "errors": errors,
        "warnings": parsed.warnings,
        "stats": parsed.stats(),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
