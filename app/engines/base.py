"""Contrato comum entre os motores de sintese."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from ..voices import VoiceInfo


class EngineError(RuntimeError):
    """Falha de sintese que deve ser mostrada ao usuario como texto legivel."""


@dataclass
class SynthRequest:
    """Um pedido de sintese ja resolvido (sem heranca de configuracao pendente)."""

    text: str
    voice: str = ""
    speed: float = 1.0
    lang: str | None = None
    ref_audio: str | None = None  # caminho da amostra, para motores com clonagem
    params: dict = field(default_factory=dict)  # opcoes especificas do motor


class Engine(ABC):
    """Um motor de texto-para-fala.

    Implementacoes carregam o modelo de forma preguicosa: instanciar um motor
    deve ser barato, para a aplicacao poder listar tudo sem baixar nada.
    """

    id: str = ""
    name: str = ""
    license: str = ""
    description: str = ""
    supports_cloning: bool = False
    supports_blending: bool = False
    sample_rate: int = 24000
    install_hint: str = ""

    @abstractmethod
    def is_available(self) -> bool:
        """True se as dependencias estiverem instaladas (sem baixar o modelo)."""

    @abstractmethod
    def list_voices(self) -> list[VoiceInfo]:
        """Vozes prontas para uso. Pode ser vazio em motores so de clonagem."""

    @abstractmethod
    def synth(self, req: SynthRequest) -> np.ndarray:
        """Sintetiza uma fala. Devolve float32 mono em `self.sample_rate`."""

    def warmup(self) -> None:
        """Carrega o modelo antecipadamente. Opcional."""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "license": self.license,
            "description": self.description,
            "supports_cloning": self.supports_cloning,
            "supports_blending": self.supports_blending,
            "sample_rate": self.sample_rate,
            "available": self.is_available(),
            "install_hint": self.install_hint,
        }
