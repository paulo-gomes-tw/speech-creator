"""Testes do catalogo de vozes e da mistura."""

from __future__ import annotations

import pytest

from app.voices import (
    KOKORO_VOICES, describe_blend, is_blend, lang_of, parse_blend, validate_voice_spec,
)


def test_catalogo_completo_e_consistente():
    assert len(KOKORO_VOICES) == 54
    assert len({v.id for v in KOKORO_VOICES}) == 54
    for v in KOKORO_VOICES:
        assert v.lang == v.id[0]
        assert v.gender in {"feminina", "masculina"}
        assert v.language and v.locale


def test_ingles_e_o_idioma_mais_completo():
    ingles = [v for v in KOKORO_VOICES if v.lang in "ab"]
    assert len(ingles) == 28
    assert any(v.quality == "A" for v in ingles)


def test_pesos_explicitos():
    assert parse_blend("af_heart:0.6+af_bella:0.4") == [("af_heart", 0.6), ("af_bella", 0.4)]


def test_pesos_sao_normalizados():
    partes = parse_blend("af_heart:3+af_bella:1")
    assert sum(w for _, w in partes) == pytest.approx(1.0)
    assert partes[0][1] == pytest.approx(0.75)


def test_sem_peso_divide_igualmente():
    partes = parse_blend("af_heart+af_bella+af_nicole")
    assert all(w == pytest.approx(1 / 3) for _, w in partes)


def test_peso_parcial_distribui_o_restante():
    partes = parse_blend("af_heart:0.8+af_bella")
    assert partes[1][1] == pytest.approx(0.2)


def test_voz_simples_nao_e_mistura():
    assert not is_blend("af_heart") and is_blend("af_heart+af_bella")
    assert parse_blend("af_heart") == [("af_heart", 1.0)]


def test_lang_of():
    assert lang_of("af_heart") == "a"
    assert lang_of("bm_george") == "b"
    assert lang_of("af_heart:0.5+af_bella:0.5") == "a"


def test_validacao_rejeita_voz_inexistente():
    with pytest.raises(ValueError, match="desconhecida"):
        validate_voice_spec("nao_existe")


def test_validacao_rejeita_mistura_entre_idiomas():
    with pytest.raises(ValueError, match="mesmo idioma"):
        validate_voice_spec("af_heart+bf_emma")


def test_mistura_entre_sotaques_do_ingles_tambem_e_bloqueada():
    # 'a' e 'b' usam pipelines de G2P diferentes, entao nao podem ser somadas.
    with pytest.raises(ValueError):
        validate_voice_spec("af_heart:0.5+bm_george:0.5")


def test_descricao_legivel():
    assert describe_blend("af_heart") == "Heart"
    assert describe_blend("af_heart:0.6+af_bella:0.4") == "Heart 60% + Bella 40%"
