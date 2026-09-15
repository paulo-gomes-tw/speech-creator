"""Parser do roteiro de show.

Sintaxe suportada::

    # comentarios comecam com #

    [Narrador] Boa noite, Sao Paulo!
    [Vocalista](speed=1.1, pitch=-2) A proxima e pra voces.
    [Vocalista](ref_audio=voz_cansada.wav, temperature=1.0) E essa aqui doi.
    [pausa 2.5]
    [Narrador]
    Sem texto na mesma linha, o bloco continua
    ate o proximo marcador.

Motores que clonam voz aceitam uma amostra por fala (`ref_audio=`), o que
permite entregas diferentes no mesmo personagem — e o que mais muda a
entonacao nesses motores, mais do que qualquer ajuste numerico.

Marcadores de pausa aceitam `pausa`, `pause` ou `silencio`, com o tempo em
segundos (`[pausa 2]`, `[pause 1.5s]`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# [Falante] ou [Falante](chave=valor, ...) no inicio da linha
SPEAKER_RE = re.compile(r"^\s*\[([^\]\n]+?)\]\s*(?:\(([^)]*)\))?\s*(.*)$")
PAUSE_RE = re.compile(r"^(?:pausa|pause|silencio|sil[eê]ncio)\s*([0-9]*[.,]?[0-9]+)?\s*s?$", re.IGNORECASE)
# O valor vai ate a proxima virgula, inteiro, em vez de so a parte bem
# formada: assim um `ref_audio=pasta/voz.wav` chega completo na validacao e e
# recusado com aviso, em vez de virar um `ref_audio=pasta` silencioso. A chave
# usa `\w`, que em str casa letra acentuada — sem isso os aliases com acento
# (`emoção`, `força`) nunca chegavam a ser lidos.
OVERRIDE_RE = re.compile(r"(\w+)\s*=\s*([^,]+)")

# Ajustes que recebem o nome de um preset, nao um numero.
WORD_OVERRIDES = {"emotion", "effect"}

# Nome de arquivo de uma amostra de referencia, resolvido na renderizacao
# contra a pasta de amostras. Aqui so se valida o formato: um nome simples,
# sem separador de caminho, para que o roteiro nao consiga apontar para fora
# dela.
FILE_OVERRIDES = {"ref_audio"}
SAFE_FILENAME_RE = re.compile(r"^[\w][\w.-]*$")

# Ajustes numericos aceitos por fala, com limites que evitam valores absurdos.
OVERRIDE_BOUNDS: dict[str, tuple[float, float]] = {
    "speed": (0.3, 3.0),
    "pitch": (-24.0, 24.0),
    "volume": (-40.0, 12.0),
    "gap": (0.0, 60.0),
    "warmth": (-18.0, 18.0),
    "brightness": (-18.0, 18.0),
    "effect_amount": (0.0, 1.0),
    "emotion_intensity": (0.0, 1.0),
    "aggression": (0.0, 1.0),
    # Parametros do proprio motor, com os mesmos limites que ele aplica. Vao
    # para `params` em vez de virarem campo do falante.
    "temperature": (0.05, 2.0),
    "exaggeration": (0.25, 1.5),
    "cfg_weight": (0.0, 1.0),
}

# Destes, quem cuida e o motor: a renderizacao os encaminha em `params`.
ENGINE_PARAMS = {"temperature", "exaggeration", "cfg_weight"}

# Aliases em portugues, para o roteiro poder ser escrito no idioma do usuario.
OVERRIDE_ALIASES = {
    "velocidade": "speed",
    "tom": "pitch",
    "altura": "pitch",
    "volume": "volume",
    "pausa": "gap",
    "intervalo": "gap",
    "calor": "warmth",
    "brilho": "brightness",
    "emocao": "emotion",
    "emoção": "emotion",
    "tom_de_voz": "emotion",
    "efeito": "effect",
    "intensidade": "effect_amount",
    "forca": "emotion_intensity",
    "força": "emotion_intensity",
    "agressividade": "aggression",
    "agressao": "aggression",
    "agressão": "aggression",
    "amostra": "ref_audio",
    "referencia": "ref_audio",
    "referência": "ref_audio",
    "temperatura": "temperature",
    "expressividade": "exaggeration",
    "aderencia": "cfg_weight",
    "aderência": "cfg_weight",
}


@dataclass
class Cue:
    """Uma entrada do roteiro: uma fala ou uma pausa."""

    kind: str  # "speech" | "pause"
    index: int = 0
    speaker: str = ""
    text: str = ""
    seconds: float = 0.0  # usado quando kind == "pause"
    overrides: dict[str, float | str] = field(default_factory=dict)
    line_no: int = 0

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "index": self.index,
            "speaker": self.speaker,
            "text": self.text,
            "seconds": self.seconds,
            "overrides": self.overrides,
            "line_no": self.line_no,
        }


@dataclass
class ParseResult:
    cues: list[Cue]
    speakers: list[str]
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "cues": [c.to_dict() for c in self.cues],
            "speakers": self.speakers,
            "warnings": self.warnings,
            "stats": self.stats(),
        }

    def stats(self) -> dict:
        speech = [c for c in self.cues if c.kind == "speech"]
        chars = sum(len(c.text) for c in speech)
        return {
            "lines": len(speech),
            "pauses": len([c for c in self.cues if c.kind == "pause"]),
            "characters": chars,
            "words": sum(len(c.text.split()) for c in speech),
            # ~14 caracteres/segundo e a taxa media de fala do Kokoro em speed=1.
            "estimated_seconds": round(chars / 14.0, 1),
        }


def _parse_overrides(raw: str | None, line_no: int, warnings: list[str]) -> dict[str, float | str]:
    if not raw:
        return {}

    from . import effects, emotions

    out: dict[str, float | str] = {}
    for key, value in OVERRIDE_RE.findall(raw):
        name = OVERRIDE_ALIASES.get(key.lower(), key.lower())
        value = value.strip()

        if name in WORD_OVERRIDES:
            known = emotions.is_known if name == "emotion" else effects.is_known
            if not known(value):
                warnings.append(f"Linha {line_no}: {name} '{value}' nao existe, ignorado.")
                continue
            out[name] = value.lower()
            continue

        if name in FILE_OVERRIDES:
            if not SAFE_FILENAME_RE.match(value) or ".." in value:
                warnings.append(
                    f"Linha {line_no}: '{name}={value}' nao e um nome de amostra valido."
                    " Use so o nome do arquivo, como esta na aba Projetos."
                )
                continue
            out[name] = value
            continue

        if name not in OVERRIDE_BOUNDS:
            warnings.append(f"Linha {line_no}: ajuste '{key}' desconhecido, ignorado.")
            continue

        try:
            num = float(value)
        except ValueError:
            warnings.append(f"Linha {line_no}: '{name}' espera um numero, recebeu '{value}'.")
            continue

        lo, hi = OVERRIDE_BOUNDS[name]
        if not lo <= num <= hi:
            clamped = max(lo, min(hi, num))
            warnings.append(f"Linha {line_no}: '{name}={num}' fora da faixa [{lo}, {hi}], usando {clamped}.")
            num = clamped
        out[name] = num
    return out


def parse_script(script: str, default_speaker: str = "Narrador") -> ParseResult:
    """Converte o texto do roteiro numa lista ordenada de cues."""
    cues: list[Cue] = []
    warnings: list[str] = []
    speakers: list[str] = []

    current_speaker: str | None = None
    current_overrides: dict[str, float] = {}
    buffer: list[str] = []

    def flush(line_no: int) -> None:
        nonlocal buffer, current_speaker, current_overrides
        text = " ".join(part.strip() for part in buffer if part.strip()).strip()
        buffer = []
        if not text:
            return
        speaker = current_speaker or default_speaker
        if speaker not in speakers:
            speakers.append(speaker)
        cues.append(
            Cue(
                kind="speech",
                speaker=speaker,
                text=text,
                overrides=dict(current_overrides),
                line_no=line_no,
            )
        )

    for line_no, raw_line in enumerate(script.splitlines(), start=1):
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            # Linha em branco encerra o bloco atual mas mantem o falante.
            flush(line_no)
            continue

        if stripped.startswith("#"):
            continue

        match = SPEAKER_RE.match(line)
        if not match:
            buffer.append(stripped)
            continue

        tag, override_raw, rest = match.group(1).strip(), match.group(2), match.group(3).strip()

        pause = PAUSE_RE.match(tag)
        if pause:
            flush(line_no)
            seconds = float((pause.group(1) or "1").replace(",", ".")) if pause.group(1) else 1.0
            cues.append(Cue(kind="pause", seconds=min(seconds, 60.0), line_no=line_no))
            if rest:
                warnings.append(f"Linha {line_no}: texto apos marcador de pausa foi ignorado.")
            continue

        flush(line_no)
        current_speaker = tag
        current_overrides = _parse_overrides(override_raw, line_no, warnings)
        if rest:
            buffer.append(rest)
            flush(line_no)

    flush(len(script.splitlines()))

    from . import emotions as _emotions
    from . import prosody as _prosody

    for i, cue in enumerate(cues):
        cue.index = i
        # Tag de tom escrita errada passaria batida como texto falado.
        for nome in _prosody.find_tags(cue.text):
            if not _emotions.is_known(nome):
                warnings.append(
                    f"Linha {cue.line_no}: <{nome}> nao e um tom conhecido; "
                    "sera lido como texto."
                )

    if not cues:
        warnings.append("Roteiro vazio: nada para gerar.")

    return ParseResult(cues=cues, speakers=speakers, warnings=warnings)


def split_long_text(text: str, max_chars: int = 400) -> list[str]:
    """Quebra um texto longo em pedacos, preferindo fim de frase.

    O Kokoro ja segmenta internamente, mas quebrar antes deixa o progresso da
    renderizacao mais granular e evita picos de memoria em falas gigantes.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    chunks: list[str] = []
    current = ""
    # Mantem a pontuacao no fim de cada sentenca.
    for sentence in re.split(r"(?<=[.!?…:;])\s+", text):
        if not sentence:
            continue
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip()
            continue
        if current:
            chunks.append(current)
        if len(sentence) <= max_chars:
            current = sentence
            continue
        # Sentenca unica maior que o limite: quebra por palavras.
        current = ""
        for word in sentence.split():
            if len(current) + len(word) + 1 > max_chars:
                chunks.append(current)
                current = word
            else:
                current = f"{current} {word}".strip()
    if current:
        chunks.append(current)
    return chunks
