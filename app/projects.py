"""Gerenciamento de projetos: roteiro, elenco e ajustes guardados em JSON.

Cada projeto e um arquivo em `data/projects/<id>.json`. O formato e o mesmo
usado na exportacao, entao um projeto exportado pode ser versionado no git,
mandado para outra pessoa da banda ou reimportado sem conversao nenhuma.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from . import config

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

MAX_NAME_CHARS = 120
MAX_SCRIPT_CHARS = 500_000
MAX_SPEAKERS = 200

ROTEIRO_INICIAL = """# Novo roteiro
# [Falante] texto  |  [pause 2]  |  ajustes: (emotion=raivoso) (effect=robo)
# Trocar de tom no meio da fala: <furioso> ... <neutro> ...

[Narrator] Good evening. Write your show here.
"""


class ProjectError(ValueError):
    """Erro de projeto com mensagem legivel para o usuario."""


def _path(project_id: str) -> Path:
    if not SAFE_ID.match(project_id or ""):
        raise ProjectError("Identificador de projeto invalido.")
    return config.PROJECTS_DIR / f"{project_id}.json"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _clean_name(name: str | None, fallback: str = "Show sem titulo") -> str:
    name = (name or "").strip()
    return name[:MAX_NAME_CHARS] if name else fallback


def _clean_payload(data: dict) -> dict:
    """Normaliza o conteudo vindo de fora (interface ou arquivo importado).

    So passam as chaves conhecidas, com tipos e tamanhos checados: o import
    aceita arquivo de qualquer origem.
    """
    data = data if isinstance(data, dict) else {}

    script = data.get("script")
    if not isinstance(script, str):
        script = ""
    if len(script) > MAX_SCRIPT_CHARS:
        raise ProjectError(f"Roteiro maior que {MAX_SCRIPT_CHARS} caracteres.")

    cast = data.get("cast")
    if not isinstance(cast, dict):
        cast = {}
    if len(cast) > MAX_SPEAKERS:
        raise ProjectError(f"Mais de {MAX_SPEAKERS} falantes no elenco.")
    cast = {str(k)[:MAX_NAME_CHARS]: v for k, v in cast.items() if isinstance(v, dict)}

    options = data.get("options")
    if not isinstance(options, dict):
        options = {}

    return {"script": script, "cast": cast, "options": options}


def _stats(script: str, cast: dict) -> dict:
    """Resumo guardado junto do projeto, para a listagem nao reprocessar tudo."""
    from .script_parser import parse_script

    parsed = parse_script(script)
    return {
        "lines": parsed.stats()["lines"],
        "characters": len(script),
        "speakers": len(set(parsed.speakers) | set(cast)),
        "estimated_seconds": parsed.stats()["estimated_seconds"],
    }


def _write(record: dict) -> dict:
    _path(record["id"]).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record


# --------------------------------------------------------------------------
# Operacoes
# --------------------------------------------------------------------------


def create(name: str | None = None, data: dict | None = None) -> dict:
    """Cria um projeto novo, sempre com id proprio.

    Sem conteudo, vem com um roteiro inicial em vez de uma pagina em branco.
    """
    config.ensure_dirs()
    limpo = _clean_payload(data or {})
    if not limpo["script"].strip():
        limpo["script"] = ROTEIRO_INICIAL

    agora = time.time()
    return _write({
        "id": _new_id(),
        "name": _clean_name(name, "Novo show"),
        **limpo,
        "stats": _stats(limpo["script"], limpo["cast"]),
        "created_at": agora,
        "updated_at": agora,
    })


def save(data: dict, project_id: str | None = None) -> dict:
    """Grava um projeto. Sem id conhecido, cria um novo."""
    config.ensure_dirs()
    project_id = project_id or data.get("id")
    if not project_id:
        return create(data.get("name"), data)

    existente = load(project_id) or {}
    limpo = _clean_payload({
        "script": data.get("script", existente.get("script", "")),
        "cast": data.get("cast", existente.get("cast", {})),
        "options": data.get("options", existente.get("options", {})),
    })

    return _write({
        "id": project_id,
        "name": _clean_name(data.get("name") or existente.get("name")),
        **limpo,
        "stats": _stats(limpo["script"], limpo["cast"]),
        "created_at": existente.get("created_at", time.time()),
        "updated_at": time.time(),
    })


def load(project_id: str) -> dict | None:
    path = _path(project_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def rename(project_id: str, name: str) -> dict:
    projeto = load(project_id)
    if projeto is None:
        raise ProjectError("Projeto nao encontrado.")
    projeto["name"] = _clean_name(name, projeto.get("name", "Show sem titulo"))
    projeto["updated_at"] = time.time()
    return _write(projeto)


def duplicate(project_id: str, name: str | None = None) -> dict:
    projeto = load(project_id)
    if projeto is None:
        raise ProjectError("Projeto nao encontrado.")

    agora = time.time()
    limpo = _clean_payload(projeto)
    return _write({
        "id": _new_id(),
        "name": _clean_name(name, f"{projeto.get('name', 'Show')} (copia)"),
        **limpo,
        "stats": _stats(limpo["script"], limpo["cast"]),
        "created_at": agora,
        "updated_at": agora,
    })


def import_project(data: dict, name: str | None = None) -> dict:
    """Importa um projeto exportado, sempre como projeto novo.

    Nunca reaproveita o id do arquivo: importar duas vezes tem de gerar dois
    projetos, e nao sobrescrever algo que ja existe com o mesmo id.
    """
    if not isinstance(data, dict):
        raise ProjectError("Arquivo de projeto invalido.")
    return create(name or data.get("name"), data)


def delete(project_id: str) -> bool:
    path = _path(project_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def list_all() -> list[dict]:
    """Resumo de todos os projetos, do mais recente para o mais antigo."""
    config.ensure_dirs()
    items: list[dict] = []
    for path in config.PROJECTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        stats = data.get("stats") or {}
        script = data.get("script", "")
        items.append({
            "id": data.get("id", path.stem),
            "name": data.get("name", path.stem),
            "created_at": data.get("created_at", 0),
            "updated_at": data.get("updated_at", 0),
            "speakers": list((data.get("cast") or {}).keys()),
            "lines": stats.get("lines", 0),
            "characters": stats.get("characters", len(script)),
            "estimated_seconds": stats.get("estimated_seconds", 0),
        })
    return sorted(items, key=lambda d: d["updated_at"], reverse=True)
