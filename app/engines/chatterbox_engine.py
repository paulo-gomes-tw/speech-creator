"""Motor Chatterbox (MIT) — clonagem de voz a partir de uma amostra curta.

Complementa o Kokoro: onde o Kokoro tem um elenco fixo, aqui qualquer voz
vira uma voz do show a partir de ~7 a 20 segundos de audio de referencia.
Depende de `chatterbox-tts`, que e um download bem maior que o Kokoro.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from .. import config
from ..audio import as_mono_float32
from ..voices import VoiceInfo
from .base import Engine, EngineError, SynthRequest

# Idiomas do modelo multilingue, rotulados para a interface.
LANGUAGES = {
    "pt": "Portugues", "en": "Ingles", "es": "Espanhol", "fr": "Frances",
    "de": "Alemao", "it": "Italiano", "nl": "Holandes", "pl": "Polones",
    "tr": "Turco", "ru": "Russo", "ar": "Arabe", "zh": "Mandarim",
    "ja": "Japones", "ko": "Coreano", "hi": "Hindi", "sv": "Sueco",
    "da": "Dinamarques", "no": "Norigues", "fi": "Finlandes", "el": "Grego",
    "he": "Hebraico", "ms": "Malaio", "sw": "Suaili",
}


class ChatterboxEngine(Engine):
    id = "chatterbox"
    name = "Chatterbox Multilingual"
    license = "MIT"
    description = (
        "Clona qualquer voz a partir de uma amostra de 7 a 20 segundos, em 23 "
        "idiomas. Tem controle de expressividade. Mais pesado que o Kokoro."
    )
    supports_cloning = True
    supports_blending = False
    splits_clauses = False  # a amostra de referencia ja carrega a entrega
    sample_rate = 24000
    install_hint = "pip install chatterbox-tts"
    native_expressiveness = True

    def __init__(self, device: str | None = None) -> None:
        self.device = device or config.best_device()
        self._model = None
        self._multilingual = False
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        try:
            import chatterbox  # noqa: F401

            return True
        except ImportError:
            return False

    def list_voices(self) -> list[VoiceInfo]:
        """Sem elenco fixo: as vozes sao as amostras que o usuario enviar."""
        return []

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            try:
                from chatterbox.mtl_tts import ChatterboxMultilingualTTS as Model

                self._multilingual = True
            except ImportError:
                from chatterbox.tts import ChatterboxTTS as Model

                self._multilingual = False
        except ImportError as exc:
            raise EngineError("Chatterbox nao esta instalado. Rode:\n  " + self.install_hint) from exc

        try:
            self._model = Model.from_pretrained(device=self.device)
        except Exception as exc:
            raise EngineError(self._load_hint(exc)) from exc

        if getattr(self._model, "sr", None):
            self.sample_rate = int(self._model.sr)
        return self._model

    @staticmethod
    def _load_hint(exc: Exception) -> str:
        """Transforma a falha de carga numa mensagem acionavel."""
        base = f"Falha ao carregar o Chatterbox: {exc}"
        text = str(exc).lower()

        # O perth (marca d'agua do Chatterbox) importa pkg_resources, que saiu
        # dos venvs no Python 3.12 e foi removido do setuptools 81+. O __init__
        # dele engole o ImportError e deixa a classe como None, entao o erro
        # que chega aqui nao diz nada. Instalar o setuptools mais novo nao
        # resolve: e preciso uma versao que ainda traga o pkg_resources.
        if "nonetype" in text and "not callable" in text:
            return (
                base
                + "\n\nO perth (marca d'agua do Chatterbox) precisa do pkg_resources,"
                + "\nque saiu dos ambientes virtuais no Python 3.12 e foi removido"
                + "\ndo setuptools 81+. Instale uma versao que ainda o tenha:"
                + "\n\n  .venv/bin/pip install \"setuptools<81\""
            )
        if any(k in text for k in ("403", "connection", "timeout", "resolve", "network", "ssl", "proxy")):
            return (
                base
                + "\n\nNa primeira execucao o modelo (~3 GB) e baixado de huggingface.co."
                + "\nVerifique a conexao ou o proxy/firewall da rede e tente de novo."
            )
        if "out of memory" in text or "mps" in text:
            return (
                base
                + f"\n\nO modelo esta carregando em '{config.best_device()}'."
                + " Para forcar a CPU, suba a aplicacao com:"
                + "\n  SPEECH_CREATOR_DEVICE=cpu ./run.sh"
            )
        return base

    def warmup(self) -> None:
        self._load()

    def synth(self, req: SynthRequest) -> np.ndarray:
        text = (req.text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.float32)

        if not req.ref_audio:
            raise EngineError("O Chatterbox precisa de uma amostra de voz de referencia.")
        ref = Path(req.ref_audio)
        if not ref.exists():
            raise EngineError(f"Amostra de referencia nao encontrada: {ref.name}")

        with self._lock:
            model = self._load()
            kwargs = {
                "audio_prompt_path": str(ref),
                "exaggeration": float(np.clip(req.params.get("exaggeration", 0.5), 0.25, 2.0)),
                "cfg_weight": float(np.clip(req.params.get("cfg_weight", 0.5), 0.0, 1.0)),
                "temperature": float(np.clip(req.params.get("temperature", 0.8), 0.05, 2.0)),
            }
            if self._multilingual:
                kwargs["language_id"] = req.lang or req.params.get("language_id", "pt")

            try:
                wav = model.generate(text, **kwargs)
            except TypeError:
                # Versoes antigas nao aceitam parte dos kwargs.
                wav = model.generate(text, audio_prompt_path=str(ref))
            except Exception as exc:
                raise EngineError(f"Chatterbox falhou ao sintetizar: {exc}") from exc

        if hasattr(wav, "detach"):
            wav = wav.detach().cpu().numpy()
        audio = as_mono_float32(wav)

        # O Chatterbox nao expoe controle de velocidade; ajustamos no pos.
        speed = float(req.speed or 1.0)
        if abs(speed - 1.0) > 1e-3:
            from ..audio import time_stretch

            audio = time_stretch(audio, speed)
        return audio
