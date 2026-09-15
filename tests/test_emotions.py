"""Testes dos presets de tom emocional."""

from __future__ import annotations

import pytest

from app import emotions as E


def base(**kw) -> dict:
    return {"speed": 1.0, "pitch": 0.0, "volume": 0.0, "warmth": 0.0,
            "brightness": 0.0, "gap": 1.0, "params": {}, **kw}


def test_catalogo_tem_os_tons_pedidos():
    ids = {e.id for e in E.EMOTIONS}
    assert {"raivoso", "indiferente", "cansado", "revoltado"} <= ids
    assert E.DEFAULT in ids


def test_neutro_nao_altera_nada():
    out = E.apply(base(speed=1.1, pitch=-3.0, volume=2.0), "neutro")
    assert (out["speed"], out["pitch"], out["volume"]) == (1.1, -3.0, 2.0)


def test_raiva_acelera_intensifica_e_encurta_pausa():
    out = E.apply(base(), "raivoso")
    assert out["speed"] > 1.0
    assert out["volume"] > 0.0
    assert out["brightness"] > 0.0   # esforco vocal joga energia nos agudos
    assert out["gap"] < 1.0          # menos espaco entre as falas


def test_cansaco_e_o_oposto_da_raiva():
    raiva, cansado = E.apply(base(), "raivoso"), E.apply(base(), "cansado")
    assert cansado["speed"] < raiva["speed"]
    assert cansado["volume"] < raiva["volume"]
    assert cansado["brightness"] < raiva["brightness"]
    assert cansado["gap"] > raiva["gap"]


def test_revoltado_e_mais_intenso_que_raivoso():
    raiva, revolta = E.apply(base(), "raivoso"), E.apply(base(), "revoltado")
    assert revolta["volume"] > raiva["volume"]
    assert revolta["speed"] > raiva["speed"]
    assert revolta["params"]["exaggeration"] > raiva["params"]["exaggeration"]


def test_indiferente_apaga_os_agudos_sem_acelerar():
    out = E.apply(base(), "indiferente")
    assert out["brightness"] < 0.0
    assert 0.9 <= out["speed"] <= 1.05
    assert out["params"]["exaggeration"] < 0.5  # pouca expressividade


def test_sussurrado_baixa_muito_o_volume():
    assert E.apply(base(), "sussurrado")["volume"] <= -6.0


@pytest.mark.parametrize("emocao", [e.id for e in E.EMOTIONS])
def test_todos_os_presets_produzem_valores_sensatos(emocao):
    out = E.apply(base(), emocao)
    assert 0.3 <= out["speed"] <= 3.0
    assert -24 <= out["pitch"] <= 24
    assert -40 <= out["volume"] <= 12
    assert out["gap"] >= 0
    assert 0.25 <= out["params"]["exaggeration"] <= 2.0


def test_deltas_sao_relativos_ao_personagem():
    """Um personagem grave continua grave quando fica com raiva."""
    grave = E.apply(base(pitch=-6.0), "raivoso")
    agudo = E.apply(base(pitch=+4.0), "raivoso")
    assert grave["pitch"] < agudo["pitch"]
    assert grave["pitch"] < 0  # nao virou uma voz aguda


def test_velocidade_e_multiplicativa():
    lento = E.apply(base(speed=0.5), "raivoso")
    normal = E.apply(base(speed=1.0), "raivoso")
    assert lento["speed"] == pytest.approx(normal["speed"] * 0.5, rel=1e-3)


def test_gap_none_continua_herdando():
    """Sem pausa propria, o falante herda a do show; o preset nao inventa uma."""
    assert E.apply(base(gap=None), "cansado")["gap"] is None


def test_params_do_usuario_vencem_o_preset_herdado():
    """Tom herdado do falante nao apaga os params que ele proprio configurou."""
    out = E.apply(base(params={"exaggeration": 0.9}), "raivoso")
    assert out["params"]["exaggeration"] == 0.9


def test_preset_do_roteiro_vence_os_params_do_falante():
    """Tom escrito no roteiro e a indicacao mais especifica, entao sobrescreve."""
    out = E.apply(base(params={"exaggeration": 0.9}), "raivoso", force_params=True)
    assert out["params"]["exaggeration"] == E.resolve("raivoso").exaggeration
    assert out["params"]["cfg_weight"] == E.resolve("raivoso").cfg_weight


def test_aliases_em_ingles():
    assert E.resolve("angry").id == "raivoso"
    assert E.resolve("tired").id == "cansado"
    assert E.resolve("WHISPER").id == "sussurrado"


def test_desconhecido_cai_em_neutro_sem_quebrar():
    assert E.resolve("inexistente").id == "neutro"
    assert E.resolve(None).id == "neutro"
    assert E.resolve("").id == "neutro"


def test_is_known():
    assert E.is_known("raivoso") and E.is_known("angry")
    assert not E.is_known("inexistente")


def test_apply_nao_muta_a_entrada():
    entrada = base()
    E.apply(entrada, "raivoso")
    assert entrada["speed"] == 1.0 and entrada["params"] == {}
