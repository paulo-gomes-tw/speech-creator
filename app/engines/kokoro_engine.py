"""Motor Kokoro-82M (Apache 2.0).

54 vozes em 9 idiomas, roda bem em CPU e permite misturar vozes somando os
tensores de estilo — o que amplia bastante o elenco disponivel.
"""

from __future__ import annotations

import threading

import numpy as np

from .. import config
from ..audio import as_mono_float32
from ..prosody import has_speech
from ..voices import EXTRA_G2P, KOKORO_VOICES, VoiceInfo, lang_of, parse_blend, validate_voice_spec
from .base import Engine, EngineError, SynthRequest


class KokoroEngine(Engine):
    id = "kokoro"
    name = "Kokoro-82M"
    license = "Apache-2.0"
    description = (
        "82M parametros, 54 vozes em 9 idiomas. Roda em CPU, e a licenca "
        "Apache-2.0 permite uso comercial (inclusive em show)."
    )
    supports_cloning = False
    supports_blending = True
    sample_rate = 24000
    install_hint = 'pip install "kokoro>=0.9.4" soundfile  # + espeak-ng no sistema'

    def __init__(self, device: str | None = None) -> None:
        self.device = device or config.DEVICE
        # Um pipeline por idioma: o G2P e especifico de cada um.
        self._pipelines: dict[str, object] = {}
        self._voice_cache: dict[str, object] = {}
        # A sintese roda numa pool de threads; o modelo nao e reentrante.
        self._lock = threading.Lock()

    # -- disponibilidade ---------------------------------------------------

    def is_available(self) -> bool:
        try:
            import kokoro  # noqa: F401

            return True
        except ImportError:
            return False

    def list_voices(self) -> list[VoiceInfo]:
        return list(KOKORO_VOICES)

    # -- carga preguicosa --------------------------------------------------

    def _pipeline(self, lang: str):
        if lang in self._pipelines:
            return self._pipelines[lang]

        try:
            from kokoro import KPipeline
        except ImportError as exc:
            raise EngineError(
                "Kokoro nao esta instalado. Rode:\n  " + self.install_hint
            ) from exc

        try:
            # repo_id explicito evita o aviso de default do kokoro.
            pipeline = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M", device=self.device)
        except TypeError:
            # Versoes mais antigas nao aceitam repo_id/device.
            pipeline = KPipeline(lang_code=lang)
        except Exception as exc:  # download do modelo, G2P faltando, etc.
            raise EngineError(self._load_hint(lang, exc)) from exc

        self._pipelines[lang] = pipeline
        return pipeline

    @staticmethod
    def _load_hint(lang: str, exc: Exception) -> str:
        """Transforma a falha de carga numa mensagem acionavel."""
        base = f"Falha ao carregar o Kokoro para o idioma '{lang}': {exc}"
        text = str(exc).lower()

        if any(k in text for k in ("403", "connection", "timeout", "resolve", "network", "ssl", "proxy")):
            return (
                base
                + "\n\nNa primeira execucao o modelo (~330 MB) e baixado de huggingface.co."
                + "\nVerifique a conexao ou o proxy/firewall da rede e tente de novo."
                + "\nJa baixado uma vez, ele fica em cache e a aplicacao roda offline."
            )
        if "espeak" in text or "phonemiz" in text:
            return (
                base
                + "\n\nFalta o espeak-ng no sistema:"
                + "\n  macOS:  brew install espeak-ng"
                + "\n  Ubuntu: sudo apt install espeak-ng"
                + "\n  Windows: winget install espeak-ng"
            )
        extra = EXTRA_G2P.get(lang)
        if extra:
            return base + f'\n\nEsse idioma precisa de: pip install "{extra}"'
        return base

    def _voice_tensor(self, voice_spec: str, lang: str):
        """Resolve uma voz simples ou uma mistura ponderada de tensores."""
        if voice_spec in self._voice_cache:
            return self._voice_cache[voice_spec]

        import torch

        pipeline = self._pipeline(lang)
        parts = parse_blend(voice_spec)

        if len(parts) == 1:
            tensor = pipeline.load_single_voice(parts[0][0])
        else:
            tensor = None
            for name, weight in parts:
                scaled = pipeline.load_single_voice(name) * weight
                tensor = scaled if tensor is None else tensor + scaled

        # O Kokoro so reconhece um tensor de voz via `isinstance(v, torch.FloatTensor)`,
        # que exige float32 na CPU. Garantir isso evita que a mistura seja tratada
        # como nome de voz e quebre com AttributeError.
        tensor = tensor.detach().to(device="cpu", dtype=torch.float32)
        self._voice_cache[voice_spec] = tensor
        return tensor

    def warmup(self, lang: str = "a") -> None:
        self._pipeline(lang)

    # -- sintese -----------------------------------------------------------

    def synth(self, req: SynthRequest) -> np.ndarray:
        text = (req.text or "").strip()
        # Texto so com pontuacao nao tem fonema para gerar, e o modelo preenche
        # o lugar dele com som que nao e palavra.
        if not has_speech(text):
            return np.zeros(0, dtype=np.float32)

        voice_spec = req.voice or "af_heart"
        try:
            validate_voice_spec(voice_spec)
        except ValueError as exc:
            raise EngineError(str(exc)) from exc

        lang = req.lang or lang_of(voice_spec)
        speed = float(np.clip(req.speed or 1.0, 0.3, 3.0))

        with self._lock:
            pipeline = self._pipeline(lang)
            voice = self._voice_tensor(voice_spec, lang)
            try:
                chunks = [
                    as_mono_float32(result.audio.detach().cpu().numpy() if hasattr(result.audio, "detach") else result.audio)
                    for result in pipeline(text, voice=voice, speed=speed)
                    if result.audio is not None
                ]
            except EngineError:
                raise
            except Exception as exc:
                raise EngineError(f"Kokoro falhou ao sintetizar: {exc}") from exc

        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32)
