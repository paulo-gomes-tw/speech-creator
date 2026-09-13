"""Presets de tom emocional.

O Kokoro nao tem controle de emocao: as vozes sao embeddings fixos. O que da
para fazer com ele e moldar a *prosodia* — velocidade, tom, intensidade e
brilho —, que sao as marcas mensuraveis de cada estado emocional. O resultado
le como a emocao certa, mas nao e atuacao.

Emocao atuada de verdade so vem do motor Chatterbox, que copia a entrega do
audio de referencia; por isso cada preset tambem carrega `exaggeration` e
`cfg_weight`, que sao os parametros de expressividade dele.

Os valores sao *relativos* a configuracao do falante: um personagem grave
continua grave quando fica com raiva.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Emotion:
    id: str
    name: str
    description: str
    speed_mult: float = 1.0
    pitch_delta: float = 0.0       # semitons
    volume_delta: float = 0.0      # dB
    warmth_delta: float = 0.0      # dB no shelf grave
    brightness_delta: float = 0.0  # dB no shelf agudo
    gap_mult: float = 1.0          # encurta ou alonga a pausa depois da fala
    exaggeration: float | None = None  # Chatterbox
    cfg_weight: float | None = None    # Chatterbox

    def to_dict(self) -> dict:
        return asdict(self)


# Esforco vocal alto (raiva, revolta, empolgacao) sobe o tom, acelera, aumenta
# a intensidade e joga energia nos agudos. Estados de baixa ativacao (cansaco,
# indiferenca) fazem o oposto e alongam as pausas.
EMOTIONS: tuple[Emotion, ...] = (
    Emotion(
        "neutro", "Neutro", "Sem alteracao — a voz como configurada.",
        exaggeration=0.5, cfg_weight=0.5,
    ),
    Emotion(
        "raivoso", "Raivoso", "Tenso e cortante: mais rapido, mais alto, agudos duros.",
        speed_mult=1.12, pitch_delta=1.0, volume_delta=4.0,
        warmth_delta=1.0, brightness_delta=4.5, gap_mult=0.7,
        exaggeration=1.3, cfg_weight=0.4,
    ),
    Emotion(
        "revoltado", "Revoltado", "Raiva levada ao grito — o extremo da escala.",
        speed_mult=1.16, pitch_delta=1.5, volume_delta=5.5,
        warmth_delta=0.5, brightness_delta=6.0, gap_mult=0.6,
        exaggeration=1.7, cfg_weight=0.32,
    ),
    Emotion(
        "indiferente", "Indiferente", "Plano e sem investimento: pouca variacao, agudos apagados.",
        speed_mult=0.98, pitch_delta=-0.5, volume_delta=-2.0,
        brightness_delta=-3.5, gap_mult=1.1,
        exaggeration=0.3, cfg_weight=0.7,
    ),
    Emotion(
        "cansado", "Cansado", "Arrastado e sem forca: lento, grave, abafado, pausas longas.",
        speed_mult=0.85, pitch_delta=-2.0, volume_delta=-4.0,
        warmth_delta=2.0, brightness_delta=-5.0, gap_mult=1.45,
        exaggeration=0.35, cfg_weight=0.65,
    ),
    Emotion(
        "animado", "Animado", "Energia positiva: rapido, tom acima, brilhante.",
        speed_mult=1.15, pitch_delta=2.0, volume_delta=3.0,
        brightness_delta=3.0, gap_mult=0.75,
        exaggeration=1.2, cfg_weight=0.45,
    ),
    Emotion(
        "sombrio", "Sombrio", "Grave e ameacador, com peso nos graves.",
        speed_mult=0.88, pitch_delta=-4.0, volume_delta=0.0,
        warmth_delta=5.0, brightness_delta=-3.0, gap_mult=1.3,
        exaggeration=0.6, cfg_weight=0.6,
    ),
    Emotion(
        "sarcastico", "Sarcastico", "Arrastado o bastante para soar de proposito.",
        speed_mult=0.93, pitch_delta=0.5, volume_delta=-1.0,
        brightness_delta=1.5, gap_mult=1.25,
        exaggeration=0.9, cfg_weight=0.55,
    ),
    Emotion(
        "sussurrado", "Sussurrado", "Baixo e proximo, sem corpo nos graves.",
        speed_mult=0.92, pitch_delta=-1.0, volume_delta=-9.0,
        warmth_delta=-4.0, brightness_delta=2.0, gap_mult=1.2,
        exaggeration=0.4, cfg_weight=0.7,
    ),
    Emotion(
        "epico", "Epico", "Locutor de arena: lento, grave e encorpado.",
        speed_mult=0.87, pitch_delta=-3.0, volume_delta=2.0,
        warmth_delta=5.0, brightness_delta=2.0, gap_mult=1.3,
        exaggeration=0.8, cfg_weight=0.5,
    ),
)

BY_ID: dict[str, Emotion] = {e.id: e for e in EMOTIONS}
DEFAULT = "neutro"

# Aceita tambem o nome em ingles, comum em roteiros escritos no idioma do show.
ALIASES = {
    "angry": "raivoso", "outraged": "revoltado", "furious": "revoltado",
    "indifferent": "indiferente", "flat": "indiferente", "deadpan": "indiferente",
    "tired": "cansado", "exhausted": "cansado",
    "excited": "animado", "happy": "animado",
    "dark": "sombrio", "ominous": "sombrio",
    "sarcastic": "sarcastico", "whisper": "sussurrado", "whispered": "sussurrado",
    "epic": "epico", "announcer": "epico",
    "neutral": "neutro", "none": "neutro",
}


def resolve(emotion_id: str | None) -> Emotion:
    """Devolve o preset pedido. Nome desconhecido cai em neutro."""
    if not emotion_id:
        return BY_ID[DEFAULT]
    key = str(emotion_id).strip().lower()
    key = ALIASES.get(key, key)
    return BY_ID.get(key, BY_ID[DEFAULT])


def is_known(emotion_id: str) -> bool:
    key = str(emotion_id).strip().lower()
    return ALIASES.get(key, key) in BY_ID


def apply(settings: dict, emotion_id: str | None) -> dict:
    """Aplica os deltas do preset sobre a configuracao de um falante.

    Recebe e devolve o dicionario de uma `VoiceSetting`. Nao mexe em `gap`
    quando ele e None: nesse caso o falante herda a pausa padrao do show, e a
    multiplicacao acontece depois, sobre o valor herdado.
    """
    emotion = resolve(emotion_id)
    out = dict(settings)

    out["speed"] = round(float(out.get("speed", 1.0)) * emotion.speed_mult, 4)
    out["pitch"] = round(float(out.get("pitch", 0.0)) + emotion.pitch_delta, 4)
    out["volume"] = round(float(out.get("volume", 0.0)) + emotion.volume_delta, 4)
    out["warmth"] = round(float(out.get("warmth", 0.0)) + emotion.warmth_delta, 4)
    out["brightness"] = round(float(out.get("brightness", 0.0)) + emotion.brightness_delta, 4)

    gap = out.get("gap")
    if gap is not None:
        out["gap"] = round(float(gap) * emotion.gap_mult, 4)

    # Expressividade do Chatterbox: o preset so preenche o que o usuario nao fixou.
    params = dict(out.get("params") or {})
    if emotion.exaggeration is not None:
        params.setdefault("exaggeration", emotion.exaggeration)
    if emotion.cfg_weight is not None:
        params.setdefault("cfg_weight", emotion.cfg_weight)
    out["params"] = params

    out["emotion"] = emotion.id
    return out


def catalog() -> list[dict]:
    return [e.to_dict() for e in EMOTIONS]
