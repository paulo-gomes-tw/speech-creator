"""Testes da API HTTP."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def fake_cast(*speakers) -> dict:
    return {sp: {"engine": "fake", "voice": "af_heart", "gap": 0.2} for sp in speakers}


def wait_for_job(client, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "error", "cancelled"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job nao terminou em {timeout}s")


# ---------------------------------------------------------------- metadados


def test_health(client):
    data = client.get("/api/health").json()
    assert data["ok"] is True and "kokoro" in data["engines"]


def test_lista_motores(client):
    ids = {e["id"] for e in client.get("/api/engines").json()["engines"]}
    assert {"kokoro", "chatterbox"} <= ids


def test_lista_vozes(client):
    data = client.get("/api/voices?engine=kokoro").json()
    assert len(data["voices"]) == 54
    assert data["supports_blending"] is True
    assert data["voices"][0]["flag"]


def test_filtra_vozes_por_idioma(client):
    data = client.get("/api/voices?engine=kokoro&lang=a").json()
    assert len(data["voices"]) == 20
    assert all(v["lang"] == "a" for v in data["voices"])


def test_motor_invalido(client):
    assert client.get("/api/voices?engine=nao_existe").status_code == 400


# ---------------------------------------------------------------- roteiro


def test_parse(client, sample_script):
    data = client.post("/api/parse", json={"script": sample_script}).json()
    assert data["speakers"] == ["Announcer", "Singer", "Guitarist"]
    assert data["stats"]["lines"] == 4


def test_parse_rejeita_tipo_errado(client):
    assert client.post("/api/parse", json={"script": 123}).status_code == 400


def test_preview_devolve_wav(client):
    res = client.post("/api/preview", json={
        "text": "Good evening everyone",
        "setting": {"engine": "fake", "voice": "af_heart"},
    })
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"
    assert res.content[:4] == b"RIFF"
    assert float(res.headers["X-Duration"]) > 0


def test_preview_com_voz_invalida(client):
    res = client.post("/api/preview", json={"text": "oi", "setting": {"engine": "kokoro", "voice": "zzz"}})
    assert res.status_code == 400 and "desconhecida" in res.json()["detail"]


def test_preview_limita_o_tamanho(client):
    res = client.post("/api/preview", json={"text": "a " * 2000, "setting": {"engine": "fake"}})
    assert res.status_code == 200 and float(res.headers["X-Duration"]) < 120


# ---------------------------------------------------------------- render


def test_render_completo(client, sample_script):
    job = client.post("/api/render", json={
        "script": sample_script, "cast": fake_cast("Announcer", "Singer", "Guitarist"),
        "options": {"per_line_files": True}, "name": "Show de teste",
    }).json()
    assert job["status"] in {"queued", "running"}

    done = wait_for_job(client, job["id"])
    assert done["status"] == "done", done.get("error")
    assert done["progress"] == 1.0
    m = done["manifest"]
    assert len(m["lines"]) == 4 and m["duration"] > 0

    audio = client.get(f"/api/jobs/{job['id']}/file/{m['files']['wav']}")
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"

    dl = client.get(f"/api/jobs/{job['id']}/download?format=wav")
    assert dl.status_code == 200
    # O Starlette codifica o nome em RFC 5987 quando ha caracteres nao-ASCII/espacos.
    assert "Show%20de%20teste.wav" in dl.headers["content-disposition"]

    fala = client.get(f"/api/jobs/{job['id']}/file/{m['lines'][0]['file']}")
    assert fala.status_code == 200 and fala.content[:4] == b"RIFF"


def test_render_roteiro_vazio(client):
    assert client.post("/api/render", json={"script": "   "}).status_code == 400


def test_render_com_erro_reporta(client):
    job = client.post("/api/render", json={"script": "[A] BOOM", "cast": fake_cast("A")}).json()
    done = wait_for_job(client, job["id"])
    assert done["status"] == "error" and "Nenhuma fala" in done["error"]


def test_job_inexistente(client):
    assert client.get("/api/jobs/naoexiste").status_code == 404


def test_download_antes_de_terminar(client):
    assert client.get("/api/jobs/naoexiste/download").status_code == 404


def test_lista_jobs(client, sample_script):
    job = client.post("/api/render", json={"script": "[A] hello", "cast": fake_cast("A")}).json()
    wait_for_job(client, job["id"])
    assert any(j["id"] == job["id"] for j in client.get("/api/jobs").json()["jobs"])


def test_path_traversal_bloqueado(client):
    job = client.post("/api/render", json={"script": "[A] hello", "cast": fake_cast("A")}).json()
    wait_for_job(client, job["id"])
    for alvo in ["../../../../etc/passwd", "..%2f..%2fetc%2fpasswd"]:
        assert client.get(f"/api/jobs/{job['id']}/file/{alvo}").status_code == 404


def test_formato_nao_gerado(client):
    job = client.post("/api/render", json={
        "script": "[A] hello", "cast": fake_cast("A"), "options": {"formats": ["wav"]},
    }).json()
    wait_for_job(client, job["id"])
    assert client.get(f"/api/jobs/{job['id']}/download?format=mp3").status_code == 404


# ---------------------------------------------------------------- projetos


def test_ciclo_de_vida_do_projeto(client, sample_script):
    saved = client.post("/api/projects", json={
        "name": "Meu show", "script": sample_script, "cast": fake_cast("Singer"),
        "options": {"lead_in": 1.5},
    }).json()
    pid = saved["id"]
    assert saved["name"] == "Meu show"

    loaded = client.get(f"/api/projects/{pid}").json()
    assert loaded["script"] == sample_script and loaded["options"]["lead_in"] == 1.5

    assert any(p["id"] == pid for p in client.get("/api/projects").json()["projects"])

    client.post("/api/projects", json={"id": pid, "name": "Renomeado"})
    assert client.get(f"/api/projects/{pid}").json()["name"] == "Renomeado"
    # Atualizar so o nome preserva o roteiro.
    assert client.get(f"/api/projects/{pid}").json()["script"] == sample_script

    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_projeto_inexistente(client):
    assert client.get("/api/projects/naoexiste").status_code == 404
    assert client.delete("/api/projects/naoexiste").status_code == 404


def test_id_de_projeto_malicioso(client):
    for bad in ["..%2f..%2fetc%2fpasswd", "a/b"]:
        assert client.get(f"/api/projects/{bad}").status_code in {400, 404}


# ---------------------------------------------------------------- amostras


def test_upload_de_amostra(client):
    import io

    from app import audio as A
    import numpy as np

    wav = A.wav_bytes(np.zeros(24000, dtype=np.float32), 24000)
    res = client.post("/api/refs", files={"file": ("minha voz.wav", io.BytesIO(wav), "audio/wav")})
    assert res.status_code == 200
    nome = res.json()["name"]
    assert nome.endswith(".wav") and " " not in nome

    assert any(r["name"] == nome for r in client.get("/api/refs").json()["refs"])
    assert client.delete(f"/api/refs/{nome}").status_code == 200
    assert client.get("/api/refs").json()["refs"] == []


def test_upload_formato_invalido(client):
    import io

    res = client.post("/api/refs", files={"file": ("x.txt", io.BytesIO(b"nao e audio"), "text/plain")})
    assert res.status_code == 400


def test_amostra_inexistente(client):
    assert client.delete("/api/refs/naoexiste.wav").status_code == 404


# ---------------------------------------------------------------- interface


def test_interface_e_servida(client):
    res = client.get("/")
    assert res.status_code == 200 and "Speech" in res.text


# ------------------------------------------------------ tom de voz e efeitos


def test_lista_emocoes(client):
    data = client.get("/api/emotions").json()
    ids = {e["id"] for e in data["emotions"]}
    assert {"raivoso", "indiferente", "cansado", "revoltado"} <= ids
    assert data["default"] == "neutro"
    assert all(e["name"] and e["description"] for e in data["emotions"])


def test_lista_efeitos(client):
    data = client.get("/api/effects").json()
    ids = {e["id"] for e in data["effects"]}
    assert {"robo", "megafone", "telefone"} <= ids
    assert data["default"] == "nenhum"


def test_preview_com_emocao_e_efeito(client):
    res = client.post("/api/preview", json={
        "text": "You call that loud?",
        "setting": {"engine": "fake", "voice": "af_heart", "emotion": "raivoso", "effect": "robo"},
    })
    assert res.status_code == 200 and res.content[:4] == b"RIFF"


def test_render_com_presets_no_roteiro(client):
    job = client.post("/api/render", json={
        "script": "[A](emotion=raivoso) Get up!\n[B](effect=robo) Systems online.",
        "cast": {**fake_cast("A", "B")},
        "options": {"per_line_files": False},
    }).json()
    done = wait_for_job(client, job["id"])
    assert done["status"] == "done", done.get("error")
    linhas = done["manifest"]["lines"]
    assert linhas[0]["emotion"] == "raivoso"
    assert linhas[1]["effect"] == "robo"
