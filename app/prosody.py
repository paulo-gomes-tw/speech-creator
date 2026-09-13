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

import numpy as np

# Quebra depois de pontuacao, mantendo-a no fim da oracao.
CLAUSE_SPLIT = re.compile(r"(?<=[,;:.!?…])\s+")

# Oracao curta demais perde contexto e sai com entonacao pobre; abaixo disso
# ela e juntada com a vizinha.
MIN_CLAUSE_CHARS = 14


def split_clauses(text: str, min_chars: int = MIN_CLAUSE_CHARS) -> list[str]:
    """Divide em oracoes, juntando as curtas demais para nao picotar a fala."""
    text = text.strip()
    if not text:
        return []

    partes = [p.strip() for p in CLAUSE_SPLIT.split(text) if p.strip()]
    if len(partes) <= 1:
        return [text]

    juntadas: list[str] = []
    for parte in partes:
        if juntadas and len(juntadas[-1]) < min_chars:
            juntadas[-1] = f"{juntadas[-1]} {parte}"
        else:
            juntadas.append(parte)

    # A ultima tambem nao pode ficar solta e curta. O pop tem de vir antes da
    # indexacao: fazer os dois na mesma expressao encurta a lista e estoura o
    # indice quando sobram exatamente duas oracoes.
    if len(juntadas) > 1 and len(juntadas[-1]) < min_chars:
        ultima = juntadas.pop()
        juntadas[-1] = f"{juntadas[-1]} {ultima}"
    return juntadas


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

    clauses = split_clauses(text)
    curva = speed_curve(len(clauses), contour)
    intensity = float(np.clip(intensity, 0.0, 1.0))

    plano: list[tuple[str, float]] = []
    for clause, fator in zip(clauses, curva):
        # intensity=0 achata a curva; intensity=1 aplica o contorno inteiro.
        aplicado = 1.0 + (fator - 1.0) * intensity
        plano.append((clause, float(np.clip(base_speed * aplicado, 0.3, 3.0))))
    return plano
