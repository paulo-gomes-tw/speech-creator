"""Pipeline de renderizacao: roteiro + elenco -> arquivos de audio."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio as A
from . import config, effects, emotions, prosody
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
    emotion_intensity: float = 1.0  # 0 a 1: quanto o preset pesa
    aggression: float | None = None  # 0 a 1; None usa a do preset de tom
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
    intensity = overrides.get("emotion_intensity", setting.emotion_intensity)
    return _with_emotion(setting, overrides, str(emotion_id), float(intensity))


def _with_emotion(
    setting: VoiceSetting, overrides: dict[str, float | str], emotion_id: str, intensity: float
) -> VoiceSetting:
    """Igual ao `_resolve`, mas com o tom dado de fora.

    Os trechos marcados com `<tom>` dentro de uma fala usam este caminho: cada
    um recebe o seu preset, mantendo os ajustes numericos escritos na linha.
    """
    merged = emotions.apply(setting.to_dict(), emotion_id, intensity)
    for key, value in overrides.items():
        if key != "emotion" and key in merged:
            merged[key] = value
    return VoiceSetting.from_dict(merged)


def effective_gap(
    cue: Cue, setting: VoiceSetting, opts: RenderOptions
) -> tuple[float, str]:
    """Pausa depois de uma fala, e de onde ela veio.

    Precedencia: ajuste da linha > pausa do falante > padrao do show. O
    multiplicador do preset de tom incide sobre o padrao herdado, que e o caso
    mais comum (a interface cria todo falante sem pausa propria).

    Fonte unica dessa regra: a renderizacao e a previa da linha do tempo
    chamam esta funcao, para nao divergirem.
    """
    da_linha = cue.overrides.get("gap")
    if da_linha is not None:
        return float(da_linha), "ajuste da linha"

    if setting.gap is not None:
        return float(setting.gap), "falante"

    emocao = emotions.resolve(setting.emotion)
    forca = max(0.0, min(1.0, float(setting.emotion_intensity)))
    mult = 1.0 + (emocao.gap_mult - 1.0) * forca
    if abs(mult - 1.0) < 1e-6:
        return float(opts.default_gap), "padrão do show"
    return float(opts.default_gap * mult), f"padrão do show × {mult:.2f} ({emocao.name})"


def timeline(
    script: str,
    cast: dict[str, VoiceSetting],
    opts: RenderOptions,
    default_setting: VoiceSetting | None = None,
) -> list[dict]:
    """Pausa prevista para cada fala, sem sintetizar nada."""
    parsed = parse_script(script)
    fallback = default_setting or VoiceSetting()
    linhas: list[dict] = []
    pendente: dict | None = None

    for cue in parsed.cues:
        if cue.kind == "pause":
            if pendente is not None:
                # Marcador explicito substitui o gap automatico; seguidos, somam.
                if pendente["source"] == "marcador [pause]":
                    pendente["gap"] = round(pendente["gap"] + cue.seconds, 3)
                else:
                    pendente["gap"] = round(cue.seconds, 3)
                    pendente["source"] = "marcador [pause]"
            continue

        raw = cast.get(cue.speaker, fallback)
        setting = _resolve(raw, cue.overrides)
        gap, origem = effective_gap(cue, setting, opts)

        # Trechos com tom proprio, para a interface mostrar o que muda onde.
        trechos = []
        for span in prosody.split_spans(cue.text, setting.emotion, setting.emotion_intensity):
            span_setting = _with_emotion(raw, cue.overrides, span.emotion, span.intensity)
            trechos.append({
                "emotion": emotions.resolve(span.emotion).id,
                "text": span.text,
                "speed": round(span_setting.speed, 3),
                "volume": round(span_setting.volume, 2),
            })

        pendente = {
            "index": cue.index,
            "speaker": cue.speaker,
            "text": cue.text,
            "line_no": cue.line_no,
            "emotion": setting.emotion,
            "speed": round(setting.speed, 3),
            "volume": round(setting.volume, 2),
            "spans": trechos,
            "gap": round(gap, 3),
            "source": origem,
        }
        linhas.append(pendente)

    if linhas:
        linhas[-1]["gap"] = 0.0
        linhas[-1]["source"] = "última fala"
    return linhas


def _safe_name(text: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "_" for c in text]
    return "".join(keep)[:40].strip("_") or "fala"


def render_cue(cue: Cue, setting: VoiceSetting, opts: RenderOptions) -> tuple[np.ndarray, int]:
    """Sintetiza uma fala e aplica todo o pos-processamento. Devolve (audio, sr).

    Recebe a configuracao *crua* do falante e resolve emocao e ajustes da linha
    aqui dentro, para que a previa da interface e a renderizacao completa
    passem exatamente pelo mesmo caminho.
    """
    raw = setting
    setting = _resolve(setting, cue.overrides)
    engine = get_engine(setting.engine)
    sr = engine.sample_rate

    if len(cue.text) > config.MAX_CHARS_PER_CUE:
        raise EngineError(
            f"Fala da linha {cue.line_no} tem {len(cue.text)} caracteres "
            f"(limite {config.MAX_CHARS_PER_CUE}). Quebre em falas menores."
        )

    from .engines.base import SynthRequest

    # A fala pode trocar de tom no meio, via `<tom>`. Cada trecho recebe o seu
    # preset e vai ao modelo com a sua propria velocidade e pontuacao: e assim
    # que a emocao entra sem tocar no sinal depois, mantendo a mesma voz.
    spans = prosody.split_spans(cue.text, setting.emotion, setting.emotion_intensity)

    pieces: list[np.ndarray] = []
    for span in spans:
        span_setting = _with_emotion(raw, cue.overrides, span.emotion, span.intensity)
        emotion = emotions.resolve(span.emotion)
        k = max(0.0, min(1.0, float(span.intensity)))
        respiro = emotion.clause_pause * k if engine.splits_clauses else 0.0

        trecho: list[np.ndarray] = []
        for chunk in split_long_text(span.text):
            if engine.splits_clauses:
                plano = prosody.plan(
                    chunk, span_setting.speed, emotion.contour, emotion.punctuation, k
                )
            else:
                # Uma geracao so para o trecho inteiro: quem clona copia a
                # entrega da amostra, e cada oracao extra custa uma geracao.
                texto_unico = chunk.strip()
                plano = [(texto_unico, span_setting.speed)] if texto_unico else []

            for texto, velocidade in plano:
                part = engine.synth(
                    SynthRequest(
                        text=texto,
                        voice=span_setting.voice,
                        speed=velocidade,
                        lang=span_setting.lang,
                        ref_audio=span_setting.ref_audio,
                        params=span_setting.params or {},
                    )
                )
                if len(part):
                    trecho.append(part)
                    trecho.append(A.silence(0.12 + respiro, sr))

        if not trecho:
            continue
        trecho.pop()  # o respiro sobrando no fim do trecho
        audio_trecho = np.concatenate(trecho).astype(np.float32)

        # Agressao vocal: compressao, saturacao e agudos, que sao os correlatos
        # acusticos do grito. Vem antes do volume para o ganho do preset incidir
        # sobre o resultado ja esgoelado.
        if span_setting.aggression:
            audio_trecho = A.aggression(audio_trecho, sr, span_setting.aggression)

        # Entre trechos so entra a diferenca RELATIVA de volume; o nivel da fala
        # inteira e aplicado depois da normalizacao, mais abaixo.
        delta = span_setting.volume - setting.volume
        if abs(delta) > 1e-3:
            audio_trecho = A.apply_gain_db(audio_trecho, delta)
        if abs(span_setting.warmth) > 1e-3 or abs(span_setting.brightness) > 1e-3:
            audio_trecho = A.tone(audio_trecho, sr, span_setting.warmth, span_setting.brightness)

        pieces.append(audio_trecho)
        pieces.append(A.silence(0.12 + respiro, sr))

    if not pieces:
        return np.zeros(0, dtype=np.float32), sr
    pieces.pop()
    out = np.concatenate(pieces).astype(np.float32)

    if opts.trim:
        out = A.trim_silence(out, sr)
    if abs(setting.pitch) > 1e-3:
        out = A.pitch_shift(out, sr, setting.pitch)
    if setting.effect and setting.effect != effects.DEFAULT:
        out = effects.apply(out, sr, setting.effect, setting.effect_amount)
    if opts.normalize:
        # "Igualar volume" existe para emparelhar vozes diferentes, nao para
        # apagar dinamica proposital. Por isso a normalizacao vem ANTES dos
        # ganhos deliberados: aplicada depois, ela zerava por completo o volume
        # dos presets de tom — sussurrado e revoltado saiam no mesmo nivel.
        out = A.rms_normalize(out, opts.target_dbfs)

    if abs(setting.volume) > 1e-3:
        out = A.apply_gain_db(out, setting.volume)
    # Um preset alto sobre uma fala ja normalizada pode passar do teto; o
    # limitador do mix final so age depois, e as falas soltas sao gravadas antes.
    out = A.soft_limit(out, -0.5)

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
    pausa_declarada: set[int] = set()  # segmentos cujo silencio veio de [pause N]
    done = 0

    # Carrega os modelos antes do loop: na primeira vez isso baixa alguns GB
    # (o Chatterbox e bem maior que o Kokoro) e, sem aviso, a interface fica
    # parada no 0% como se tivesse travado.
    for engine_id in dict.fromkeys(
        _resolve(cast.get(c.speaker, fallback), c.overrides).engine for c in speech_cues
    ):
        if cancelled and cancelled():
            raise EngineError("Renderizacao cancelada.")
        try:
            engine = get_engine(engine_id)
            if progress:
                progress(0, total, f"Carregando o modelo {engine.name} (pode demorar na primeira vez)...")
            engine.warmup()
        except Exception:
            # Aquecer e so para dar feedback: a falha real vira erro da fala,
            # que o loop reporta sem derrubar as outras.
            pass

    for cue in parsed.cues:
        if cancelled and cancelled():
            raise EngineError("Renderizacao cancelada.")

        if cue.kind == "pause":
            # `[pause N]` vale N segundos de silencio, nao N somados a pausa
            # automatica: quem escreve o marcador esta declarando o tempo que
            # quer ali. Marcadores seguidos se acumulam.
            if segments:
                indice = len(segments) - 1
                if indice in pausa_declarada:
                    segments[-1].gap_after += cue.seconds
                else:
                    segments[-1].gap_after = cue.seconds
                    pausa_declarada.add(indice)
            else:
                # Antes da primeira fala nao ha gap automatico para substituir.
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

        gap, _origem = effective_gap(cue, setting, opts)
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
