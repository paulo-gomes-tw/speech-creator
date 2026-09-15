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


# ---------------------------------------------------------------- trechos


from app.prosody import Span, find_tags, split_spans  # noqa: E402


def test_troca_de_tom_no_meio_da_fala():
    spans = split_spans("Good evening! <raivoso>Get up now!<neutro> Thanks.", "neutro")
    assert [(s.emotion, s.text) for s in spans] == [
        ("neutro", "Good evening!"),
        ("raivoso", "Get up now!"),
        ("neutro", "Thanks."),
    ]


def test_tag_vale_ate_o_fim_quando_nao_ha_outra():
    spans = split_spans("Calm start. <cansado>and it fades away", "neutro")
    assert spans[-1].emotion == "cansado"


def test_intensidade_na_tag():
    spans = split_spans("Calm. <raivoso:0.4>A bit angry.", "neutro")
    assert spans[1].intensity == 0.4


def test_tag_sem_intensidade_herda_a_da_fala():
    spans = split_spans("Calm. <raivoso>Angry.", "neutro", default_intensity=0.7)
    assert spans[1].intensity == 0.7


def test_fala_sem_tag_vira_um_trecho_so():
    spans = split_spans("Plain line here", "cansado", 0.6)
    assert spans == [Span(text="Plain line here", emotion="cansado", intensity=0.6)]


def test_tag_desconhecida_fica_como_texto():
    """Um `<3` numa letra nao pode sumir da fala."""
    spans = split_spans("I love you <3 always", "neutro")
    assert len(spans) == 1 and spans[0].text == "I love you <3 always"


def test_tag_no_inicio_da_fala():
    spans = split_spans("<raivoso>Angry from the start.", "neutro")
    assert len(spans) == 1 and spans[0].emotion == "raivoso"


def test_tags_seguidas_nao_criam_trecho_vazio():
    spans = split_spans("<raivoso><cansado>Only tired.", "neutro")
    assert len(spans) == 1 and spans[0].emotion == "cansado"


def test_alias_em_ingles_na_tag():
    assert split_spans("Hi. <angry>Now!", "neutro")[1].emotion == "angry"


def test_texto_vazio():
    assert split_spans("   ", "neutro") == []


def test_find_tags_lista_os_nomes():
    assert find_tags("a <raivoso>b <naoexiste>c") == ["raivoso", "naoexiste"]
    assert find_tags("") == []


def test_nenhuma_palavra_e_perdida():
    import re

    texto = "Good evening! <raivoso>Get up now!<neutro> Thanks for coming."
    spans = split_spans(texto, "neutro")
    esperado = re.findall(r"[a-z']+", re.sub(r"<[^>]+>", " ", texto).lower())
    obtido = re.findall(r"[a-z']+", " ".join(s.text for s in spans).lower())
    assert obtido == esperado


# ------------------------------------------------- fragmentos que alucinam


from app.prosody import has_speech  # noqa: E402


def test_nao_quebra_uma_frase_em_fragmento_curto():
    """Fragmento curto faz o modelo preencher o resto com som inventado."""
    assert split_clauses("Hey, you, over there, listen up now!") == [
        "Hey, you, over there, listen up now!"
    ]


def test_quebra_de_frase_vem_antes_da_quebra_de_oracao():
    """Cada pedaco tem de ser, sempre que der, uma frase inteira."""
    out = split_clauses("Good evening, everyone here. Are you ready to go?")
    assert out == ["Good evening, everyone here.", "Are you ready to go?"]


def test_pedaco_so_de_pontuacao_nao_fica_sozinho():
    """Ele iria ao modelo sem fonema nenhum, que e quando o som e inventado."""
    for texto in ("Listen to me carefully. ...", "Ready? ... Here we go now!"):
        out = split_clauses(texto)
        assert len(out) == 1 or all(has_speech(p) for p in out)


def test_plano_descarta_o_que_nao_se_pronuncia():
    """Sem fonema para gerar, o modelo inventa um: nao pode chegar la."""
    assert plan("...", 1.0, (1.0,), "none") == []
    assert plan("— — —", 1.0, (1.0,), "none") == []


def test_has_speech():
    assert has_speech("oi")
    assert has_speech("3 vezes")
    assert not has_speech("...")
    assert not has_speech("  -- ,;  ")
    assert not has_speech("")
