"""Persistencia de projetos (roteiro + elenco + opcoes) em JSON."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from . import config

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _path(project_id: str) -> Path:
    if not SAFE_ID.match(project_id):
        raise ValueError("Identificador de projeto invalido.")
    return config.PROJECTS_DIR / f"{project_id}.json"


def save(data: dict, project_id: str | None = None) -> dict:
    config.ensure_dirs()
    project_id = project_id or data.get("id") or uuid.uuid4().hex[:12]
    path = _path(project_id)

    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}

    record = {
        "id": project_id,
        "name": data.get("name") or existing.get("name") or "Show sem titulo",
        "script": data.get("script", existing.get("script", "")),
        "cast": data.get("cast", existing.get("cast", {})),
        "options": data.get("options", existing.get("options", {})),
        "created_at": existing.get("created_at", time.time()),
        "updated_at": time.time(),
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def load(project_id: str) -> dict | None:
    path = _path(project_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def delete(project_id: str) -> bool:
    path = _path(project_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def list_all() -> list[dict]:
    config.ensure_dirs()
    items: list[dict] = []
    for path in config.PROJECTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append({
            "id": data.get("id", path.stem),
            "name": data.get("name", path.stem),
            "updated_at": data.get("updated_at", 0),
            "speakers": list((data.get("cast") or {}).keys()),
            "characters": len(data.get("script", "")),
        })
    return sorted(items, key=lambda d: d["updated_at"], reverse=True)
