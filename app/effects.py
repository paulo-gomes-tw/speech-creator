"""Efeitos de voz: robotizacao, megafone, radio e variacoes.

Diferente dos presets de emocao, que so moldam a prosodia, aqui o
processamento e deterministico: o resultado sai exatamente igual toda vez, e
independe do motor de sintese usado.

Cada efeito recebe uma intensidade de 0 a 1, que controla a mistura entre o
sinal limpo e o processado (e, em alguns casos, a agressividade do processo).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import audio as A


@dataclass(frozen=True)
class Effect:
    id: str
    name: str
    description: str
    fn: Callable[[np.ndarray, int, float], np.ndarray]
    default_amount: float = 0.75

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "default_amount": self.default_amount,
        }


def _none(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    return x


def _robo(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Robo classico: fase zerada na STFT + corpo metalico do filtro pente."""
    wet = A.robotize(x, sr)
    wet = A.comb(wet, sr, delay_ms=6.0, feedback=0.35 + 0.25 * amount)
    # Tirar os graves profundos evita o "ronco" que a fase zerada acumula.
    wet = A._pass(wet, sr, 140.0, high=True)
    wet = A.peak_normalize(wet, -3.0)
    return A.mix(x, wet, amount)


def _androide(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Sintetico, mas articulado: camadas desafinadas + modulacao suave.

    Preserva bem mais inteligibilidade que o robo puro, entao serve para falas
    longas em que o texto precisa ser entendido.
    """
    wet = A.detune_stack(x, sr, cents=(-14.0, 14.0))
    ring = A.ring_mod(wet, sr, freq=30.0)
    wet = A.mix(wet, ring, 0.35 * amount)
    wet = A.tone(wet, sr, warmth_db=-2.0, brightness_db=3.0)
    wet = A.peak_normalize(wet, -3.0)
    return A.mix(x, wet, amount)


def _vocoder(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Robo cantado: robotizacao com zumbido mais grave e agudos realcados."""
    wet = A.robotize(x, sr, n_fft=1024, hop=384)
    wet = A.bandpass(wet, sr, 180.0, 6500.0)
    wet = A.saturate(wet, drive=1.0 + 2.0 * amount)
    wet = A.peak_normalize(wet, -3.0)
    return A.mix(x, wet, amount)


def _megafone(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Megafone / PA de arena: faixa estreita e alto-falante esgoelado."""
    wet = A.bandpass(x, sr, 500.0, 4000.0, poles=2)
    wet = A.saturate(wet, drive=2.0 + 4.0 * amount)
    wet = A.peak_normalize(wet, -3.0)
    return A.mix(x, wet, amount)


def _radio(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Transmissao AM: faixa estreita, chiado e um toque de lo-fi."""
    wet = A.bandpass(x, sr, 400.0, 3200.0, poles=2)
    wet = A.saturate(wet, drive=1.5 + 2.0 * amount)
    wet = A.bitcrush(wet, sr, bits=10, downsample=1)
    wet = A.peak_normalize(wet, -4.0)
    wet = A.add_noise(wet, level_db=-40.0 + 8.0 * amount)
    return A.mix(x, wet, amount)


def _telefone(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Linha telefonica: a faixa padrao de 300 a 3400 Hz."""
    wet = A.bandpass(x, sr, 300.0, 3400.0, poles=3)
    wet = A.peak_normalize(wet, -3.0)
    return A.mix(x, wet, amount)


def _alienigena(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Fora do humano: modulacao em anel aguda, que joga o timbre para fora da escala."""
    wet = A.ring_mod(x, sr, freq=90.0 + 110.0 * amount)
    wet = A.mix(x, wet, 0.85)
    wet = A.comb(wet, sr, delay_ms=11.0, feedback=0.4)
    wet = A.peak_normalize(wet, -3.0)
    return A.mix(x, wet, amount)


def _lofi(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Sampler antigo de 8 bits."""
    bits = int(round(10 - 5 * amount))
    down = int(round(1 + 3 * amount))
    wet = A.bitcrush(x, sr, bits=bits, downsample=down)
    wet = A._pass(wet, sr, 6000.0, high=False)
    wet = A.peak_normalize(wet, -3.0)
    return A.mix(x, wet, amount)


def _coro(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Varias vozes juntas: util para refrao falado e coro de multidao."""
    wet = A.detune_stack(x, sr, cents=(-25.0, -9.0, 9.0, 25.0))
    wet = A.peak_normalize(wet, -3.0)
    return A.mix(x, wet, amount)


EFFECTS: tuple[Effect, ...] = (
    Effect("nenhum", "Nenhum", "Voz sem processamento.", _none, 0.0),
    Effect("robo", "Robo", "Robo classico de ficcao: entonacao vira zumbido metalico.", _robo, 0.8),
    Effect("androide", "Androide", "Sintetico porem claro — bom para falas longas.", _androide, 0.7),
    Effect("vocoder", "Vocoder", "Robo cantado, mais grave e saturado.", _vocoder, 0.8),
    Effect("megafone", "Megafone", "PA de arena, alto-falante esgoelado.", _megafone, 0.85),
    Effect("radio", "Radio AM", "Transmissao antiga, com chiado.", _radio, 0.8),
    Effect("telefone", "Telefone", "Faixa estreita de linha telefonica.", _telefone, 0.9),
    Effect("alienigena", "Alienigena", "Timbre fora do humano.", _alienigena, 0.7),
    Effect("lofi", "Lo-fi", "Sampler de 8 bits.", _lofi, 0.7),
    Effect("coro", "Coro", "Varias vozes desafinadas em uniss ono.", _coro, 0.6),
)

BY_ID: dict[str, Effect] = {e.id: e for e in EFFECTS}
DEFAULT = "nenhum"

ALIASES = {
    "none": "nenhum", "off": "nenhum",
    "robot": "robo", "android": "androide", "alien": "alienigena",
    "megaphone": "megafone", "phone": "telefone", "telephone": "telefone",
    "choir": "coro", "crowd": "coro",
}


def resolve(effect_id: str | None) -> Effect:
    if not effect_id:
        return BY_ID[DEFAULT]
    key = str(effect_id).strip().lower()
    key = ALIASES.get(key, key)
    return BY_ID.get(key, BY_ID[DEFAULT])


def is_known(effect_id: str) -> bool:
    key = str(effect_id).strip().lower()
    return ALIASES.get(key, key) in BY_ID


def apply(x: np.ndarray, sr: int, effect_id: str | None, amount: float | None = None) -> np.ndarray:
    """Aplica um efeito. `amount` None usa a intensidade padrao do efeito."""
    effect = resolve(effect_id)
    if effect.id == DEFAULT or len(x) == 0:
        return x
    level = effect.default_amount if amount is None else float(np.clip(amount, 0.0, 1.0))
    if level <= 0.0:
        return x
    return effect.fn(x, sr, level).astype(np.float32)


def catalog() -> list[dict]:
    return [e.to_dict() for e in EFFECTS]
