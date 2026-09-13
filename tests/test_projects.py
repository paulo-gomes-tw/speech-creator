"""Testes do gerenciamento de projetos."""

from __future__ import annotations

import json

import pytest

from app import projects


def payload(**kw) -> dict:
    base = {
        "name": "Show de teste",
        "script": "[A] hello there\n[B] second line",
        "cast": {"A": {"engine": "fake", "voice": "af_heart"}},
        "options": {"lead_in": 1.5},
    }
    return {**base, **kw}


# ---------------------------------------------------------------- criar


def test_criar_gera_id_proprio():
    a, b = projects.create("Um"), projects.create("Dois")
    assert a["id"] != b["id"]
    assert a["name"] == "Um" and b["name"] == "Dois"


def test_projeto_novo_vem_com_roteiro_inicial():
    """Pagina em branco nao ajuda: o roteiro inicial mostra a sintaxe."""
    p = projects.create()
    assert p["script"].strip()
    assert "[" in p["script"]


def test_criar_com_conteudo():
    p = projects.create("Com conteudo", payload())
    assert p["script"] == payload()["script"]
    assert p["cast"] == payload()["cast"]


def test_criar_sem_nome_usa_padrao():
    assert projects.create().name if False else projects.create()["name"]


def test_stats_sao_guardados():
    p = projects.create("X", payload())
    assert p["stats"]["lines"] == 2
    assert p["stats"]["speakers"] >= 2
    assert p["stats"]["characters"] == len(payload()["script"])


# ---------------------------------------------------------------- salvar


def test_salvar_sem_id_cria():
    p = projects.save(payload())
    assert p["id"] and projects.load(p["id"]) is not None


def test_salvar_com_id_atualiza_sem_duplicar():
    p = projects.save(payload())
    de_novo = projects.save({**payload(), "id": p["id"], "name": "Renomeado"})
    assert de_novo["id"] == p["id"]
    assert de_novo["name"] == "Renomeado"
    assert len(projects.list_all()) == 1


def test_salvar_parcial_preserva_o_resto():
    p = projects.save(payload())
    so_nome = projects.save({"id": p["id"], "name": "Outro nome"})
    assert so_nome["script"] == payload()["script"]
    assert so_nome["cast"] == payload()["cast"]


def test_created_at_nao_muda_ao_atualizar():
    p = projects.save(payload())
    de_novo = projects.save({**payload(), "id": p["id"], "name": "Z"})
    assert de_novo["created_at"] == p["created_at"]
    assert de_novo["updated_at"] >= p["updated_at"]


# ---------------------------------------------------------------- duplicar


def test_duplicar_copia_o_conteudo_com_id_novo():
    p = projects.create("Original", payload())
    copia = projects.duplicate(p["id"])
    assert copia["id"] != p["id"]
    assert copia["script"] == p["script"] and copia["cast"] == p["cast"]
    assert "copia" in copia["name"].lower()
    assert len(projects.list_all()) == 2


def test_duplicar_com_nome_escolhido():
    p = projects.create("Original", payload())
    assert projects.duplicate(p["id"], "Versao acustica")["name"] == "Versao acustica"


def test_duplicar_e_independente():
    """Editar a copia nao pode mexer no original."""
    p = projects.create("Original", payload())
    copia = projects.duplicate(p["id"])
    projects.save({"id": copia["id"], "script": "[Z] mudou"})
    assert projects.load(p["id"])["script"] == payload()["script"]


def test_duplicar_inexistente():
    with pytest.raises(projects.ProjectError, match="nao encontrado"):
        projects.duplicate("naoexiste")


# ---------------------------------------------------------------- renomear


def test_renomear():
    p = projects.create("Antigo", payload())
    novo = projects.rename(p["id"], "Novo nome")
    assert novo["name"] == "Novo nome"
    assert novo["script"] == p["script"]  # so o nome muda


def test_renomear_inexistente():
    with pytest.raises(projects.ProjectError, match="nao encontrado"):
        projects.rename("naoexiste", "X")


def test_nome_vazio_cai_no_padrao():
    p = projects.create("Tinha nome", payload())
    assert projects.rename(p["id"], "   ")["name"] == "Tinha nome"


def test_nome_muito_longo_e_cortado():
    assert len(projects.create("x" * 500)["name"]) <= projects.MAX_NAME_CHARS


# ---------------------------------------------------------------- importar


def test_importar_cria_projeto_novo():
    p = projects.create("Original", payload())
    exportado = projects.load(p["id"])
    importado = projects.import_project(exportado)
    assert importado["id"] != p["id"]
    assert importado["script"] == p["script"]


def test_importar_duas_vezes_gera_dois_projetos():
    """Reaproveitar o id do arquivo sobrescreveria um projeto existente."""
    p = projects.create("Original", payload())
    exportado = projects.load(p["id"])
    projects.import_project(exportado)
    projects.import_project(exportado)
    assert len(projects.list_all()) == 3


def test_importar_lixo_nao_quebra():
    importado = projects.import_project({"script": 123, "cast": "nao e dict", "options": []})
    assert importado["script"].strip()  # caiu no roteiro inicial
    assert importado["cast"] == {} and importado["options"] == {}


def test_importar_nao_dicionario():
    with pytest.raises(projects.ProjectError):
        projects.import_project(["isso nao e um projeto"])


def test_importar_roteiro_gigante_e_recusado():
    with pytest.raises(projects.ProjectError, match="maior que"):
        projects.import_project({"script": "a" * (projects.MAX_SCRIPT_CHARS + 1)})


def test_importar_elenco_gigante_e_recusado():
    cast = {f"F{i}": {} for i in range(projects.MAX_SPEAKERS + 1)}
    with pytest.raises(projects.ProjectError, match="falantes"):
        projects.import_project({"cast": cast})


# ---------------------------------------------------------------- listar e apagar


def test_listar_traz_o_mais_recente_primeiro():
    import time

    a = projects.create("Primeiro")
    time.sleep(0.01)
    b = projects.create("Segundo")
    assert [p["id"] for p in projects.list_all()][:2] == [b["id"], a["id"]]


def test_listagem_tem_o_resumo():
    projects.create("Show", payload())
    item = projects.list_all()[0]
    assert item["lines"] == 2
    assert set(item["speakers"]) == {"A"}
    assert item["characters"] > 0


def test_listagem_ignora_arquivo_corrompido():
    projects.create("Bom", payload())
    (projects.config.PROJECTS_DIR / "quebrado.json").write_text("{ isso nao e json", encoding="utf-8")
    assert len(projects.list_all()) == 1


def test_apagar():
    p = projects.create("Some", payload())
    assert projects.delete(p["id"]) is True
    assert projects.load(p["id"]) is None
    assert projects.delete(p["id"]) is False


# ---------------------------------------------------------------- seguranca


@pytest.mark.parametrize("ruim", ["../fora", "a/b", "", "..", "x" * 100, "com espaco"])
def test_id_invalido_e_recusado(ruim):
    with pytest.raises(projects.ProjectError, match="invalido"):
        projects._path(ruim)


def test_load_de_id_invalido_nao_le_fora_da_pasta():
    with pytest.raises(projects.ProjectError):
        projects.load("../../etc/passwd")


def test_arquivo_salvo_e_json_valido():
    p = projects.create("Show", payload())
    lido = json.loads((projects.config.PROJECTS_DIR / f"{p['id']}.json").read_text(encoding="utf-8"))
    assert lido["id"] == p["id"] and lido["name"] == "Show"
