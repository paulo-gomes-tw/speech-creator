"""Fraseado: como a fala e dividida, acelerada e pontuada.

Este modulo existe porque emocao em fala nao e um efeito aplicado ao sinal —
e ritmo, enfase e fraseado. Mexer no audio depois de sintetizado (deslocar o
tom, exagerar o EQ) arrasta os formantes e destroi a identidade da voz: soa
processado, nao emocionado.

O que se faz aqui, em vez disso, e mudar *o que o modelo sintetiza*:

- quebrar a fala em oracoes e dar a cada uma a sua velocidade, criando um
  contorno (acelerar na raiva, perder folego no cansaco);
- inserir respiros entre as oracoes;
- reescrever a pontuacao, que o G2P repassa ao modelo e muda a entonacao.

Tudo isso passa pela sintese, entao o resultado continua sendo a mesma voz.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

# Quebra de frase (pontuacao terminal) e quebra de oracao (virgula e cia).
# Sao separadas de proposito: o modelo sintetiza um pedaco de cada vez e
# alucina quando recebe um fragmento curto ou sem frase fechada, entao a
# quebra dentro da frase so acontece quando sobra texto suficiente dos dois
# lados.
SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
CLAUSE_SPLIT = re.compile(r"(?<=[,;:])\s+")

# Oracao curta demais perde contexto e sai com entonacao pobre — e, pior, faz
# o modelo preencher o resto com som que nao e palavra. Abaixo disso ela e
# juntada com a vizinha.
MIN_CLAUSE_CHARS = 20

# Um caractere que se le: letra ou numero. Pedaco sem nenhum (so pontuacao,
# tipo "..." ou "—") nao pode ir ao modelo: sem fonema para gerar, ele inventa
# um, e o que sai e balbucio ou letra soletrada.
SPEAKABLE = re.compile(r"[^\W_]", re.UNICODE)


def has_speech(text: str) -> bool:
    """Se o texto tem algo para o modelo pronunciar."""
    return bool(SPEAKABLE.search(text or ""))


def _merge_short(partes: list[str], min_chars: int) -> list[str]:
    """Cola os pedacos curtos (ou impronunciaveis) no vizinho."""
    juntadas: list[str] = []
    for parte in partes:
        if juntadas and (
            len(juntadas[-1]) < min_chars
            or not has_speech(juntadas[-1])
            or not has_speech(parte)
        ):
            juntadas[-1] = f"{juntadas[-1]} {parte}"
        else:
            juntadas.append(parte)

    # A ultima tambem nao pode ficar solta e curta. O pop tem de vir antes da
    # indexacao: fazer os dois na mesma expressao encurta a lista e estoura o
    # indice quando sobram exatamente duas oracoes.
    while len(juntadas) > 1 and (
        len(juntadas[-1]) < min_chars or not has_speech(juntadas[-1])
    ):
        ultima = juntadas.pop()
        juntadas[-1] = f"{juntadas[-1]} {ultima}"
    return juntadas


def split_clauses(text: str, min_chars: int = MIN_CLAUSE_CHARS) -> list[str]:
    """Divide em oracoes, juntando as curtas demais para nao picotar a fala.

    Quebra primeiro nas frases e so depois dentro delas: assim o pedaco que
    vai ao modelo e, sempre que da, uma frase inteira — que e o que ele sabe
    sintetizar sem inventar som no fim.
    """
    text = text.strip()
    if not text:
        return []

    oracoes: list[str] = []
    for frase in (f.strip() for f in SENTENCE_SPLIT.split(text)):
        if not frase:
            continue
        partes = [p.strip() for p in CLAUSE_SPLIT.split(frase) if p.strip()]
        oracoes.extend(_merge_short(partes, min_chars))

    return _merge_short(oracoes, min_chars) or [text]


def speed_curve(n: int, contour: tuple[float, ...]) -> list[float]:
    """Interpola o contorno para `n` oracoes, com media 1.0.

    Normalizar a media separa as responsabilidades: o contorno so molda a
    variacao interna da fala, enquanto a velocidade geral continua sendo do
    `speed_mult` do preset.
    """
    if n <= 1 or not contour or len(contour) < 2:
        return [1.0] * max(n, 0)

    curva = np.interp(np.linspace(0.0, 1.0, n), np.linspace(0.0, 1.0, len(contour)), contour)
    media = float(np.mean(curva))
    if media <= 0:
        return [1.0] * n
    return [float(v / media) for v in curva]


# --------------------------------------------------------------------------
# Reescrita de pontuacao
# --------------------------------------------------------------------------

TERMINAL = ".!?…"


def _terminal_split(text: str) -> tuple[str, str]:
    """Separa o corpo da fala da sua pontuacao final."""
    corpo = text.rstrip()
    fim = ""
    while corpo and corpo[-1] in TERMINAL:
        fim = corpo[-1] + fim
        corpo = corpo[:-1].rstrip()
    return corpo, fim


def shape_text(text: str, style: str) -> str:
    """Reescreve a pontuacao para mudar a entonacao que o modelo produz.

    So mexe em pontuacao — nunca nas palavras —, entao o sentido da fala e o
    texto que o usuario escreveu continuam intactos.
    """
    text = text.strip()
    if not text or style in {"", "none", "neutro"}:
        return text

    corpo, fim = _terminal_split(text)
    if not corpo:
        return text

    if style == "emphatic":
        # Ponto final vira exclamacao: entonacao descendente e marcada.
        return corpo + ("!" if fim in {"", "."} else fim)

    if style == "clipped":
        # Virgulas viram pontos: oracoes curtas e secas, sem ligacao.
        corpo = re.sub(r"\s*[,;]\s+(\w)", lambda m: ". " + m.group(1).upper(), corpo)
        return corpo + ("!" if fim in {"", "."} else fim)

    if style == "trailing":
        # Reticencias: a frase morre em vez de terminar.
        return corpo + "..."

    if style == "hesitant":
        # Reticencias no fim e uma quebra antes da ultima oracao.
        corpo = re.sub(r"\s*,\s+", "... ", corpo, count=1)
        return corpo + "..."

    return text


def plan(
    text: str,
    base_speed: float,
    contour: tuple[float, ...] = (1.0,),
    punctuation: str = "none",
    intensity: float = 1.0,
) -> list[tuple[str, float]]:
    """Monta o plano de sintese: uma lista de (texto da oracao, velocidade).

    `intensity` de 0 a 1 aproxima o contorno de 1.0, permitindo dosar o quanto
    a emocao pesa sem trocar de preset.
    """
    text = shape_text(text, punctuation) if intensity > 0.5 else text.strip()
    if not text:
        return []

    # Pedaco sem nada pronunciavel nao vai ao modelo: ele responderia com som
    # inventado no lugar do silencio que se esperava.
    clauses = [c for c in split_clauses(text) if has_speech(c)]
    if not clauses:
        return []
    curva = speed_curve(len(clauses), contour)
    intensity = float(np.clip(intensity, 0.0, 1.0))

    plano: list[tuple[str, float]] = []
    for clause, fator in zip(clauses, curva):
        # intensity=0 achata a curva; intensity=1 aplica o contorno inteiro.
        aplicado = 1.0 + (fator - 1.0) * intensity
        plano.append((clause, float(np.clip(base_speed * aplicado, 0.3, 3.0))))
    return plano


# --------------------------------------------------------------------------
# Trechos com tom proprio dentro de uma mesma fala
# --------------------------------------------------------------------------

# <raivoso> ou <raivoso:0.5>. Troca o tom dali em diante, sem tag de fechamento:
# uma fala tem muito mais trocas do que pares, e esquecer de fechar seria o
# erro mais comum.
SPAN_TAG = re.compile(r"<\s*([A-Za-zÀ-ÿ][\wÀ-ÿ-]*)\s*(?::\s*([01]?(?:\.\d+)?)\s*)?>")


@dataclass(frozen=True)
class Span:
    """Um trecho de fala com o seu proprio tom."""

    text: str
    emotion: str
    intensity: float


def find_tags(text: str) -> list[str]:
    """Nomes usados em tags de tom, para o parser poder validar e avisar."""
    return [m.group(1) for m in SPAN_TAG.finditer(text or "")]


def split_spans(
    text: str,
    default_emotion: str = "neutro",
    default_intensity: float = 1.0,
    is_known=None,
) -> list[Span]:
    """Divide a fala nos trechos marcados por `<tom>`.

    Uma tag cujo nome nao seja um tom conhecido e deixada como texto literal —
    assim um `<3` ou um `<br>` numa letra nao some da fala.
    """
    text = (text or "").strip()
    if not text:
        return []

    if is_known is None:
        from . import emotions

        is_known = emotions.is_known

    spans: list[Span] = []
    emocao, forca = default_emotion, default_intensity
    buffer: list[str] = []
    pos = 0

    def fechar() -> None:
        trecho = "".join(buffer).strip()
        buffer.clear()
        if trecho:
            spans.append(Span(text=trecho, emotion=emocao, intensity=forca))

    for m in SPAN_TAG.finditer(text):
        nome = m.group(1)
        if not is_known(nome):
            continue  # nao e tag de tom: fica no texto
        buffer.append(text[pos:m.start()])
        fechar()
        emocao = nome.strip().lower()
        forca = float(m.group(2)) if m.group(2) else default_intensity
        pos = m.end()

    buffer.append(text[pos:])
    fechar()

    return spans or [Span(text=text, emotion=default_emotion, intensity=default_intensity)]
