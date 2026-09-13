"""Registro dos motores disponiveis."""

from __future__ import annotations

from .base import Engine, EngineError, SynthRequest
from .chatterbox_engine import ChatterboxEngine
from .kokoro_engine import KokoroEngine

# Instancias unicas: o modelo carregado fica em cache entre as requisicoes.
_REGISTRY: dict[str, Engine] = {}


def _registry() -> dict[str, Engine]:
    if not _REGISTRY:
        for engine in (KokoroEngine(), ChatterboxEngine()):
            _REGISTRY[engine.id] = engine
    return _REGISTRY


def get_engine(engine_id: str) -> Engine:
    reg = _registry()
    if engine_id not in reg:
        raise EngineError(f"Motor desconhecido: {engine_id!r}. Disponiveis: {', '.join(reg)}")
    return reg[engine_id]


def list_engines() -> list[Engine]:
    return list(_registry().values())


def register_engine(engine: Engine) -> None:
    """Ponto de extensao para motores adicionais (usado tambem nos testes)."""
    _registry()[engine.id] = engine


__all__ = [
    "Engine", "EngineError", "SynthRequest",
    "KokoroEngine", "ChatterboxEngine",
    "get_engine", "list_engines", "register_engine",
]
