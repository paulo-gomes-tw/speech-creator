"""Fixtures compartilhadas e um motor falso para testar sem baixar modelos."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.engines import register_engine  # noqa: E402
from app.engines.base import Engine, EngineError, SynthRequest  # noqa: E402
from app.voices import KOKORO_VOICES, VoiceInfo  # noqa: E402


class FakeEngine(Engine):
    """Sintetiza um tom cuja duracao acompanha o texto.

    Deixa o pipeline inteiro (DSP, mixagem, arquivos, jobs) testavel sem
    depender do download dos pesos nem do tempo de inferencia.
    """

    id = "fake"
    name = "Fake"
    license = "n/a"
    sample_rate = 24000
    supports_blending = True

    def is_available(self) -> bool:
        return True

    def list_voices(self) -> list[VoiceInfo]:
        return list(KOKORO_VOICES)

    def synth(self, req: SynthRequest) -> np.ndarray:
        if "BOOM" in req.text:
            raise EngineError("falha proposital de sintese")
        seconds = max(0.25, len(req.text) / 14.0) / max(req.speed, 0.1)
        t = np.linspace(0, seconds, int(seconds * self.sample_rate), endpoint=False)
        # Frequencia derivada da voz, para vozes diferentes soarem diferentes.
        freq = 110.0 + (sum(map(ord, req.voice)) % 12) * 20.0
        wave = 0.35 * np.sin(2 * np.pi * freq * t) + 0.12 * np.sin(2 * np.pi * freq * 3 * t)
        envelope = np.minimum(1.0, np.minimum(t / 0.05, (seconds - t) / 0.05))
        return (wave * np.clip(envelope, 0, 1)).astype(np.float32)


@pytest.fixture(scope="session", autouse=True)
def _register_fake() -> None:
    register_engine(FakeEngine())


@pytest.fixture(autouse=True)
def _isolated_data(tmp_path, monkeypatch):
    """Cada teste escreve numa pasta de dados propria."""
    for name in ("DATA_DIR", "PROJECTS_DIR", "OUTPUT_DIR", "REFS_DIR", "CACHE_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    config.ensure_dirs()
    return tmp_path


@pytest.fixture
def sample_script() -> str:
    return """# show de teste
[Announcer](speed=0.95, pitch=-3) Please welcome to the stage.
[pause 2]
[Singer] Good evening! How are you tonight?
[Singer](gap=1.5) This next one is new.
[Guitarist] One, two, three, four!
"""
