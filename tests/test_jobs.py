"""Testes da fila de renderizacao."""

from __future__ import annotations

import time

import pytest

from app import config
from app.jobs import Job, JobManager
from app.render import RenderOptions, VoiceSetting


def esperar(job, timeout: float = 30.0) -> None:
    limite = time.time() + timeout
    while time.time() < limite:
        if job.status in {"done", "error", "cancelled"}:
            return
        time.sleep(0.02)
    raise AssertionError("job nao terminou")


@pytest.fixture
def gerente():
    return JobManager(workers=1)


def cast(*speakers):
    return {sp: VoiceSetting(speaker=sp, engine="fake", voice="af_heart", gap=0.1) for sp in speakers}


def test_job_completa_e_publica_o_manifesto(gerente):
    job = gerente.submit("[A] hello there\n[A] second line", cast("A"), RenderOptions(), title="Teste")
    esperar(job)
    assert job.status == "done"
    assert job.manifest and len(job.manifest["lines"]) == 2
    assert job.progress == 1.0 and job.title == "Teste"


def test_job_com_erro_guarda_a_mensagem(gerente):
    job = gerente.submit("[A] BOOM", cast("A"), RenderOptions())
    esperar(job)
    assert job.status == "error" and "Nenhuma fala" in job.error


def test_cancelamento(gerente):
    job = gerente.submit("[A] " + "\n[A] ".join(["uma fala bem longa aqui"] * 40), cast("A"), RenderOptions())
    time.sleep(0.05)
    gerente.cancel(job.id)
    esperar(job)
    assert job.status == "cancelled"


def test_cancelar_job_terminado_falha(gerente):
    job = gerente.submit("[A] hello", cast("A"), RenderOptions())
    esperar(job)
    assert gerente.cancel(job.id) is False


def test_get_e_list(gerente):
    job = gerente.submit("[A] hello", cast("A"), RenderOptions())
    esperar(job)
    assert gerente.get(job.id) is job
    assert gerente.get("naoexiste") is None
    assert job.id in [j.id for j in gerente.list()]


def test_listagem_traz_o_mais_recente_primeiro(gerente):
    a = gerente.submit("[A] primeiro", cast("A"), RenderOptions())
    esperar(a)
    b = gerente.submit("[A] segundo", cast("A"), RenderOptions())
    esperar(b)
    assert [j.id for j in gerente.list()][:2] == [b.id, a.id]


def test_descarte_preserva_a_ordem(gerente, monkeypatch):
    """Jobs antigos terminados saem; a ordem dos que ficam nao muda."""
    monkeypatch.setattr(config, "MAX_JOBS_IN_MEMORY", 3)
    ids = []
    for i in range(5):
        job = gerente.submit(f"[A] fala {i}", cast("A"), RenderOptions())
        esperar(job)
        ids.append(job.id)

    restantes = [j.id for j in gerente.list()]
    assert len(restantes) == 3
    assert restantes == list(reversed(ids[-3:]))  # os 3 mais novos, em ordem


def test_descarte_nao_remove_job_ativo(gerente, monkeypatch):
    monkeypatch.setattr(config, "MAX_JOBS_IN_MEMORY", 2)
    ativo = Job(id="ativo", status="running")
    gerente._jobs["ativo"] = ativo
    gerente._order.insert(0, "ativo")
    for i in range(4):
        esperar(gerente.submit(f"[A] fala {i}", cast("A"), RenderOptions()))
    assert gerente.get("ativo") is ativo


def test_to_dict_tem_os_campos_da_interface(gerente):
    job = gerente.submit("[A] hello", cast("A"), RenderOptions())
    esperar(job)
    d = job.to_dict()
    assert {"id", "status", "progress", "current", "total", "manifest", "elapsed"} <= set(d)
