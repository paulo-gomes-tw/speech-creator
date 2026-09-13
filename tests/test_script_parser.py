"""Testes do parser de roteiro."""

from __future__ import annotations

import pytest

from app.script_parser import parse_script, split_long_text


def test_falantes_e_ordem(sample_script):
    r = parse_script(sample_script)
    assert r.speakers == ["Announcer", "Singer", "Guitarist"]
    assert [c.kind for c in r.cues] == ["speech", "pause", "speech", "speech", "speech"]
    assert [c.index for c in r.cues] == [0, 1, 2, 3, 4]


def test_ajustes_inline(sample_script):
    r = parse_script(sample_script)
    assert r.cues[0].overrides == {"speed": 0.95, "pitch": -3.0}
    assert r.cues[3].overrides == {"gap": 1.5}


def test_aliases_em_portugues():
    r = parse_script("[Ana](velocidade=1.2, tom=3, pausa=2, brilho=4) Oi")
    assert r.cues[0].overrides == {"speed": 1.2, "pitch": 3.0, "gap": 2.0, "brightness": 4.0}


def test_ajuste_desconhecido_vira_aviso():
    r = parse_script("[Ana](reverb=5) Oi")
    assert r.cues[0].overrides == {}
    assert any("reverb" in w for w in r.warnings)


def test_valores_fora_da_faixa_sao_limitados():
    r = parse_script("[Ana](speed=99) Oi")
    assert r.cues[0].overrides["speed"] == 3.0
    assert any("fora da faixa" in w for w in r.warnings)


@pytest.mark.parametrize("linha,segundos", [
    ("[pause 2]", 2.0), ("[pausa 1.5]", 1.5), ("[pause 0.5s]", 0.5),
    ("[silencio 3]", 3.0), ("[pausa]", 1.0), ("[pausa 1,5]", 1.5),
])
def test_formatos_de_pausa(linha, segundos):
    cues = parse_script(f"[A] oi\n{linha}\n[A] tchau").cues
    assert cues[1].kind == "pause" and cues[1].seconds == segundos


def test_pausa_e_limitada_a_60s():
    assert parse_script("[pause 9999]").cues[0].seconds == 60.0


def test_bloco_multilinha_vira_uma_fala():
    r = parse_script("[Ana]\nPrimeira linha\nsegunda linha\n\n[Bob] Outra")
    assert r.cues[0].text == "Primeira linha segunda linha"
    assert len(r.cues) == 2


def test_comentarios_e_linhas_vazias_sao_ignorados():
    r = parse_script("# nota\n\n[Ana] Oi\n\n# outra\n")
    assert len(r.cues) == 1 and r.cues[0].text == "Oi"


def test_texto_sem_falante_usa_o_padrao():
    r = parse_script("Sem marcador nenhum.")
    assert r.cues[0].speaker == "Narrador"


def test_falante_persiste_ate_o_proximo_marcador():
    """Linhas soltas continuam no falante atual, mas viram falas separadas."""
    r = parse_script("[Ana] um\nsegunda parte\n[Bob] tres")
    assert [(c.speaker, c.text) for c in r.cues] == [
        ("Ana", "um"), ("Ana", "segunda parte"), ("Bob", "tres"),
    ]


def test_marcador_com_texto_e_fala_unica_marcador_sozinho_e_bloco():
    """Distincao central da sintaxe.

    `[Ana] texto` fecha a fala na hora, dando controle de pausa linha a linha.
    `[Ana]` sozinho abre um bloco que junta as linhas seguintes numa fala so.
    """
    uma_linha = parse_script("[Ana] primeira\n[Ana] segunda")
    assert len(uma_linha.cues) == 2

    bloco = parse_script("[Ana]\nprimeira\nsegunda")
    assert len(bloco.cues) == 1 and bloco.cues[0].text == "primeira segunda"


def test_linha_em_branco_fecha_o_bloco():
    r = parse_script("[Ana]\nprimeira\n\nsegunda")
    assert [c.text for c in r.cues] == ["primeira", "segunda"]
    assert all(c.speaker == "Ana" for c in r.cues)


def test_roteiro_vazio_avisa():
    r = parse_script("   \n\n# so comentario\n")
    assert r.cues == [] and any("vazio" in w for w in r.warnings)


def test_estatisticas(sample_script):
    s = parse_script(sample_script).stats()
    assert s["lines"] == 4 and s["pauses"] == 1 and s["words"] > 0
    assert s["estimated_seconds"] > 0


def test_split_long_text_respeita_o_limite():
    texto = "Uma frase de teste. " * 80
    chunks = split_long_text(texto, 200)
    assert all(len(c) <= 200 for c in chunks)
    assert "".join(chunks).replace(" ", "") == texto.replace(" ", "")


def test_split_long_text_quebra_palavra_a_palavra_quando_preciso():
    texto = " ".join(["palavra"] * 200)  # sem pontuacao
    chunks = split_long_text(texto, 100)
    assert all(len(c) <= 100 for c in chunks) and len(chunks) > 1


def test_split_long_text_curto_nao_quebra():
    assert split_long_text("Curto.", 400) == ["Curto."]
    assert split_long_text("   ", 400) == []
