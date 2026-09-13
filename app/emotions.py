"""Presets de tom emocional.

Uma versao anterior deste modulo mudava o tom (pitch) e exagerava o EQ para
sugerir emocao. Era a ferramenta errada: deslocar o tom com phase vocoder
arrasta os formantes junto, e formante e o que define a identidade de uma voz.
O resultado nao soava como a mesma pessoa com raiva — soava como voz
distorcida. EQ de 5 ou 6 dB so somava aspereza.

Emocao em fala e ritmo, enfase e fraseado, nao um deslocamento de frequencia.
Entao os presets agora atuam antes da sintese, nao depois:

- `speed_mult`  — velocidade nativa do Kokoro; o modelo re-sintetiza, sem artefato;
- `contour`     — velocidade variando ao longo da fala (acelerar, perder folego);
- `clause_pause`— respiro entre as oracoes;
- `punctuation` — reescrita da pontuacao, que muda a entonacao gerada;
- `volume_delta`— ganho, que nao distorce.

O EQ continua disponivel, mas limitado a ajustes sutis de timbre. O pitch nao
e mais tocado por nenhum preset: continua como controle manual do usuario, que
e quem decide se quer pagar esse preco.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# Teto do EQ nos presets. Acima disso o ouvido le como processamento, nao
# como intencao — foi exatamente o erro da versao anterior.
MAX_EQ_DB = 2.0


@dataclass(frozen=True)
class Emotion:
    id: str
    name: str
    description: str

    # --- levers que passam pela sintese (sem artefato) ---
    speed_mult: float = 1.0
    contour: tuple[float, ...] = (1.0,)   # velocidade relativa, do inicio ao fim
    clause_pause: float = 0.0             # respiro extra entre oracoes, em segundos
    punctuation: str = "none"             # emphatic | clipped | trailing | hesitant

    # --- levers de mixagem (nao distorcem) ---
    volume_delta: float = 0.0             # dB
    gap_mult: float = 1.0                 # pausa entre falas

    # --- timbre sutil, limitado a +/- MAX_EQ_DB ---
    warmth_delta: float = 0.0
    brightness_delta: float = 0.0

    # --- expressividade do Chatterbox, que tem emocao nativa ---
    exaggeration: float | None = None
    cfg_weight: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["contour"] = list(self.contour)
        return d


EMOTIONS: tuple[Emotion, ...] = (
    Emotion(
        "neutro", "Neutro", "A voz como configurada, sem alteracao.",
        exaggeration=0.5, cfg_weight=0.5,
    ),
    Emotion(
        "raivoso", "Raivoso",
        "Rapido e cortado, acelerando: frases curtas, quase sem respiro.",
        speed_mult=1.10, contour=(1.0, 1.10), clause_pause=0.0,
        punctuation="clipped", volume_delta=3.5, gap_mult=0.65,
        brightness_delta=1.5,
        exaggeration=1.3, cfg_weight=0.4,
    ),
    Emotion(
        "revoltado", "Revoltado",
        "Raiva sem freio: mais rapido ainda, atropelando as pausas.",
        speed_mult=1.16, contour=(1.02, 1.14), clause_pause=0.0,
        punctuation="emphatic", volume_delta=5.0, gap_mult=0.55,
        brightness_delta=2.0,
        exaggeration=1.7, cfg_weight=0.32,
    ),
    Emotion(
        "indiferente", "Indiferente",
        "Sem investimento: ritmo constante, nenhuma variacao, pausas iguais.",
        speed_mult=0.97, contour=(1.0,), clause_pause=0.05,
        punctuation="none", volume_delta=-1.5, gap_mult=1.1,
        brightness_delta=-1.5,
        exaggeration=0.3, cfg_weight=0.72,
    ),
    Emotion(
        "cansado", "Cansado",
        "Vai perdendo folego: comeca quase normal e vai arrastando ate o fim.",
        speed_mult=0.86, contour=(0.98, 0.80), clause_pause=0.30,
        punctuation="trailing", volume_delta=-3.5, gap_mult=1.5,
        warmth_delta=1.0, brightness_delta=-2.0,
        exaggeration=0.35, cfg_weight=0.65,
    ),
    Emotion(
        "animado", "Animado",
        "Empolgado: rapido e crescendo, pausas curtas.",
        speed_mult=1.13, contour=(1.0, 1.08), clause_pause=0.0,
        punctuation="emphatic", volume_delta=2.5, gap_mult=0.75,
        brightness_delta=1.5,
        exaggeration=1.2, cfg_weight=0.45,
    ),
    Emotion(
        "sombrio", "Sombrio",
        "Deliberado e pesado: lento, com silencio entre as oracoes.",
        speed_mult=0.89, contour=(0.96, 0.90), clause_pause=0.35,
        punctuation="none", volume_delta=-0.5, gap_mult=1.35,
        warmth_delta=2.0, brightness_delta=-1.5,
        exaggeration=0.6, cfg_weight=0.6,
    ),
    Emotion(
        "sarcastico", "Sarcastico",
        "Arrastado de proposito, com uma quebra no meio.",
        speed_mult=0.92, contour=(0.92, 1.04), clause_pause=0.25,
        punctuation="hesitant", volume_delta=-1.0, gap_mult=1.25,
        exaggeration=0.9, cfg_weight=0.55,
    ),
    Emotion(
        "sussurrado", "Sussurrado",
        "Baixo e contido, sem projecao.",
        speed_mult=0.94, contour=(1.0,), clause_pause=0.15,
        punctuation="trailing", volume_delta=-9.0, gap_mult=1.2,
        warmth_delta=-1.5, brightness_delta=1.0,
        exaggeration=0.4, cfg_weight=0.7,
    ),
    Emotion(
        "epico", "Epico",
        "Locutor de arena: cada oracao separada, com peso.",
        speed_mult=0.88, contour=(0.94, 0.90), clause_pause=0.45,
        punctuation="none", volume_delta=1.5, gap_mult=1.35,
        warmth_delta=2.0,
        exaggeration=0.8, cfg_weight=0.5,
    ),
)

BY_ID: dict[str, Emotion] = {e.id: e for e in EMOTIONS}
DEFAULT = "neutro"

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
    return BY_ID.get(ALIASES.get(key, key), BY_ID[DEFAULT])


def is_known(emotion_id: str) -> bool:
    key = str(emotion_id).strip().lower()
    return ALIASES.get(key, key) in BY_ID


def apply(settings: dict, emotion_id: str | None, intensity: float = 1.0) -> dict:
    """Aplica o preset sobre a configuracao de um falante.

    `intensity` de 0 a 1 dosa o quanto o preset pesa, sem trocar de preset.
    O tom (pitch) nunca e alterado aqui: preservar os formantes e o que
    mantem a voz reconhecivel.
    """
    emotion = resolve(emotion_id)
    k = max(0.0, min(1.0, float(intensity)))
    out = dict(settings)

    # Interpola entre "sem efeito" (1.0 / 0.0) e o valor cheio do preset.
    out["speed"] = round(float(out.get("speed", 1.0)) * (1.0 + (emotion.speed_mult - 1.0) * k), 4)
    out["volume"] = round(float(out.get("volume", 0.0)) + emotion.volume_delta * k, 4)

    for campo, delta in (("warmth", emotion.warmth_delta), ("brightness", emotion.brightness_delta)):
        limitado = max(-MAX_EQ_DB, min(MAX_EQ_DB, delta))
        out[campo] = round(float(out.get(campo, 0.0)) + limitado * k, 4)

    gap = out.get("gap")
    if gap is not None:
        out["gap"] = round(float(gap) * (1.0 + (emotion.gap_mult - 1.0) * k), 4)

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
