"""Catalogo de vozes do Kokoro com metadados para a interface.

O primeiro caractere do id da voz e o codigo de idioma usado pelo Kokoro
(a = ingles americano, b = britanico, p = portugues do Brasil, etc.), e o
segundo indica o genero (f/m).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

LANGUAGES: dict[str, dict[str, str]] = {
    "a": {"code": "a", "name": "Ingles (EUA)", "locale": "en-US", "flag": "🇺🇸"},
    "b": {"code": "b", "name": "Ingles (Reino Unido)", "locale": "en-GB", "flag": "🇬🇧"},
    "p": {"code": "p", "name": "Portugues (Brasil)", "locale": "pt-BR", "flag": "🇧🇷"},
    "e": {"code": "e", "name": "Espanhol", "locale": "es", "flag": "🇪🇸"},
    "f": {"code": "f", "name": "Frances", "locale": "fr-FR", "flag": "🇫🇷"},
    "i": {"code": "i", "name": "Italiano", "locale": "it", "flag": "🇮🇹"},
    "h": {"code": "h", "name": "Hindi", "locale": "hi", "flag": "🇮🇳"},
    "j": {"code": "j", "name": "Japones", "locale": "ja", "flag": "🇯🇵"},
    "z": {"code": "z", "name": "Mandarim", "locale": "zh", "flag": "🇨🇳"},
}

# Idiomas que exigem dependencia extra de G2P (`pip install "misaki[ja]"`).
EXTRA_G2P = {"j": "misaki[ja]", "z": "misaki[zh]"}


@dataclass
class VoiceInfo:
    id: str
    name: str
    lang: str
    locale: str
    language: str
    gender: str
    quality: str  # nota de qualidade publicada pelo projeto Kokoro (A = melhor)
    engine: str = "kokoro"
    cloned: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["flag"] = LANGUAGES.get(self.lang, {}).get("flag", "🎙")
        d["needs_extra"] = EXTRA_G2P.get(self.lang)
        return d


# (id, nome de exibicao, nota de qualidade)
_KOKORO_RAW: list[tuple[str, str, str]] = [
    # Ingles americano
    ("af_heart", "Heart", "A"),
    ("af_bella", "Bella", "A-"),
    ("af_nicole", "Nicole", "B-"),
    ("af_aoede", "Aoede", "C+"),
    ("af_kore", "Kore", "C+"),
    ("af_sarah", "Sarah", "C+"),
    ("af_nova", "Nova", "C"),
    ("af_sky", "Sky", "C-"),
    ("af_alloy", "Alloy", "C"),
    ("af_jessica", "Jessica", "D"),
    ("af_river", "River", "D"),
    ("am_fenrir", "Fenrir", "C+"),
    ("am_michael", "Michael", "C+"),
    ("am_puck", "Puck", "C+"),
    ("am_echo", "Echo", "D"),
    ("am_eric", "Eric", "D"),
    ("am_liam", "Liam", "D"),
    ("am_onyx", "Onyx", "D"),
    ("am_adam", "Adam", "F+"),
    ("am_santa", "Santa", "D-"),
    # Ingles britanico
    ("bf_emma", "Emma", "B-"),
    ("bf_isabella", "Isabella", "C"),
    ("bf_alice", "Alice", "D"),
    ("bf_lily", "Lily", "D"),
    ("bm_fable", "Fable", "C"),
    ("bm_george", "George", "C"),
    ("bm_lewis", "Lewis", "D+"),
    ("bm_daniel", "Daniel", "D"),
    # Portugues do Brasil
    ("pf_dora", "Dora", "C"),
    ("pm_alex", "Alex", "C"),
    ("pm_santa", "Santa", "C"),
    # Espanhol
    ("ef_dora", "Dora", "C"),
    ("em_alex", "Alex", "C"),
    ("em_santa", "Santa", "C"),
    # Frances
    ("ff_siwis", "Siwis", "B-"),
    # Italiano
    ("if_sara", "Sara", "C"),
    ("im_nicola", "Nicola", "C"),
    # Hindi
    ("hf_alpha", "Alpha", "C"),
    ("hf_beta", "Beta", "C"),
    ("hm_omega", "Omega", "C"),
    ("hm_psi", "Psi", "C"),
    # Japones
    ("jf_alpha", "Alpha", "C+"),
    ("jf_gongitsune", "Gongitsune", "C"),
    ("jf_tebukuro", "Tebukuro", "C"),
    ("jf_nezumi", "Nezumi", "C-"),
    ("jm_kumo", "Kumo", "C-"),
    # Mandarim
    ("zf_xiaobei", "Xiaobei", "D"),
    ("zf_xiaoni", "Xiaoni", "D"),
    ("zf_xiaoxiao", "Xiaoxiao", "D"),
    ("zf_xiaoyi", "Xiaoyi", "D"),
    ("zm_yunjian", "Yunjian", "D"),
    ("zm_yunxi", "Yunxi", "D"),
    ("zm_yunxia", "Yunxia", "D"),
    ("zm_yunyang", "Yunyang", "D"),
]


def _build() -> list[VoiceInfo]:
    voices: list[VoiceInfo] = []
    for vid, name, quality in _KOKORO_RAW:
        lang = vid[0]
        gender = "feminina" if vid[1] == "f" else "masculina"
        meta = LANGUAGES.get(lang, {"name": lang, "locale": lang})
        voices.append(
            VoiceInfo(
                id=vid,
                name=name,
                lang=lang,
                locale=meta["locale"],
                language=meta["name"],
                gender=gender,
                quality=quality,
            )
        )
    return voices


KOKORO_VOICES: list[VoiceInfo] = _build()
KOKORO_VOICE_IDS: set[str] = {v.id for v in KOKORO_VOICES}
VOICES_BY_ID: dict[str, VoiceInfo] = {v.id: v for v in KOKORO_VOICES}


def lang_of(voice_id: str) -> str:
    """Codigo de idioma do Kokoro para uma voz (ou para o primeiro de uma mistura)."""
    base = voice_id.split("+")[0].split(":")[0].strip()
    return base[0] if base else "a"


def is_blend(voice_spec: str) -> bool:
    return "+" in voice_spec


def parse_blend(voice_spec: str) -> list[tuple[str, float]]:
    """Le `af_heart:0.6+af_bella:0.4` e devolve pesos normalizados.

    Partes sem peso explicito dividem o que sobrou igualmente; se nenhum peso
    for informado, a mistura fica uniforme.
    """
    parts: list[tuple[str, float | None]] = []
    for chunk in voice_spec.split("+"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            name, _, weight = chunk.partition(":")
            try:
                parts.append((name.strip(), float(weight)))
            except ValueError:
                parts.append((name.strip(), None))
        else:
            parts.append((chunk, None))

    if not parts:
        raise ValueError(f"Mistura de vozes invalida: {voice_spec!r}")

    known = sum(w for _, w in parts if w is not None)
    unknown = [i for i, (_, w) in enumerate(parts) if w is None]
    resolved = [w if w is not None else 0.0 for _, w in parts]
    if unknown:
        share = max(0.0, 1.0 - known) / len(unknown)
        for i in unknown:
            resolved[i] = share

    total = sum(resolved)
    if total <= 0:
        resolved = [1.0 / len(parts)] * len(parts)
        total = 1.0
    return [(name, w / total) for (name, _), w in zip(parts, resolved)]


def validate_voice_spec(voice_spec: str) -> None:
    """Levanta ValueError com mensagem util se a voz nao existir."""
    for name, _ in parse_blend(voice_spec):
        if name not in KOKORO_VOICE_IDS:
            raise ValueError(f"Voz desconhecida: {name!r}")
    langs = {lang_of(name) for name, _ in parse_blend(voice_spec)}
    if len(langs) > 1:
        raise ValueError("So da para misturar vozes do mesmo idioma.")


def describe_blend(voice_spec: str) -> str:
    parts = parse_blend(voice_spec)
    if len(parts) == 1:
        v = VOICES_BY_ID.get(parts[0][0])
        return v.name if v else parts[0][0]
    return " + ".join(
        f"{VOICES_BY_ID[n].name if n in VOICES_BY_ID else n} {round(w * 100)}%" for n, w in parts
    )
