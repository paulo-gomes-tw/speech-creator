"""Testes do fraseado (divisao em oracoes, contorno e pontuacao)."""

from __future__ import annotations

import pytest

from app.prosody import plan, shape_text, speed_curve, split_clauses


# ---------------------------------------------------------------- oracoes


def test_divide_em_oracoes():
    assert split_clauses("We drove eight hours to get here, so you better be loud.") == [
        "We drove eight hours to get here,", "so you better be loud.",
    ]


def test_frase_unica_nao_e_dividida():
    assert split_clauses("Good evening everyone") == ["Good evening everyone"]


def test_oracoes_curtas_sao_juntadas():
    """Trecho curto perde contexto e sai com entonacao pobre."""
    assert split_clauses("One, two, three, four!") == ["One, two, three, four!"]


def test_ultima_oracao_curta_nao_fica_solta():
    """Regressao: o pop dentro da indexacao encurtava a lista e estourava o
    indice quando sobravam exatamente duas oracoes."""
    out = split_clauses("This is a long enough first clause, go!")
    assert len(out) == 1 and out[0].endswith("go!")


@pytest.mark.parametrize("texto", [
    "One, two, three, four!", "Go!", "A, b.", "", "   ",
    "a, b, c, d, e, f, g!", "Sentence one. Two. Three.",
    "Ends with comma,", "...", "Hello... is anyone there?",
])
def test_nunca_quebra_com_texto_dificil(texto):
    out = split_clauses(texto)
    assert isinstance(out, list)
    assert all(c.strip() for c in out)


def test_nenhum_texto_e_perdido():
    texto = "First clause here, second clause here, third clause here."
    assert "".join(split_clauses(texto)).replace(" ", "") == texto.replace(" ", "")


# ---------------------------------------------------------------- contorno


def test_contorno_tem_media_um():
    """O contorno so molda a variacao; a velocidade geral e do preset."""
    for contorno in [(0.95, 0.80), (1.0, 1.10), (0.9, 1.2)]:
        curva = speed_curve(5, contorno)
        assert sum(curva) / len(curva) == pytest.approx(1.0, abs=1e-6)


def test_contorno_descendente_desacelera():
    curva = speed_curve(4, (0.98, 0.80))
    assert curva == sorted(curva, reverse=True)
    assert curva[0] > curva[-1]


def test_contorno_ascendente_acelera():
    curva = speed_curve(4, (1.0, 1.10))
    assert curva == sorted(curva)


def test_oracao_unica_nao_recebe_contorno():
    assert speed_curve(1, (0.9, 1.2)) == [1.0]


def test_contorno_plano():
    assert speed_curve(3, (1.0,)) == [1.0, 1.0, 1.0]


# ---------------------------------------------------------------- pontuacao


def test_emphatic_vira_exclamacao():
    assert shape_text("Get up now.", "emphatic") == "Get up now!"
    assert shape_text("Get up now", "emphatic") == "Get up now!"


def test_emphatic_preserva_interrogacao():
    assert shape_text("Are you ready?", "emphatic") == "Are you ready?"


def test_clipped_quebra_em_frases_curtas():
    out = shape_text("We drove eight hours, so you better be loud.", "clipped")
    assert out == "We drove eight hours. So you better be loud!"


def test_trailing_usa_reticencias():
    assert shape_text("I can't do this.", "trailing") == "I can't do this..."


def test_hesitant_quebra_no_meio():
    out = shape_text("Sure, that sounds great.", "hesitant")
    assert out == "Sure... that sounds great..."


def test_none_nao_altera():
    assert shape_text("Leave me alone.", "none") == "Leave me alone."


def test_pontuacao_nao_mexe_nas_palavras():
    """Reescrever o texto do usuario alem da pontuacao seria inaceitavel."""
    import re

    original = "We drove eight hours, so you better be loud tonight."
    palavras = re.findall(r"[a-z']+", original.lower())
    for estilo in ("emphatic", "clipped", "trailing", "hesitant"):
        assert re.findall(r"[a-z']+", shape_text(original, estilo).lower()) == palavras


# ---------------------------------------------------------------- plano


def test_plano_devolve_texto_e_velocidade():
    out = plan("First clause is here, second clause is here.", 1.0, (0.98, 0.80), "none")
    assert len(out) == 2
    assert out[0][1] > out[1][1]  # desacelera
    assert all(isinstance(t, str) and t for t, _ in out)


def test_plano_respeita_a_velocidade_base():
    a = plan("Just one clause here", 1.0, (1.0,), "none")
    b = plan("Just one clause here", 0.5, (1.0,), "none")
    assert b[0][1] == pytest.approx(a[0][1] * 0.5)


def test_intensidade_zero_achata_o_contorno():
    out = plan("First clause is here, second clause is here.", 1.0, (0.98, 0.80), "none", intensity=0.0)
    assert out[0][1] == pytest.approx(out[1][1])


def test_intensidade_zero_nao_reescreve_a_pontuacao():
    out = plan("I can't do this.", 1.0, (1.0,), "trailing", intensity=0.0)
    assert out[0][0] == "I can't do this."


def test_velocidade_fica_na_faixa_do_modelo():
    for base in (0.3, 1.0, 3.0):
        for t, v in plan("First clause here, second clause here, third here.", base, (0.5, 1.8), "none"):
            assert 0.3 <= v <= 3.0


def test_texto_vazio_devolve_plano_vazio():
    assert plan("   ", 1.0, (1.0,), "none") == []
