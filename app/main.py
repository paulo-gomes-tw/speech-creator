"""API HTTP e servidor da interface web."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import audio as A
from . import config, effects, emotions, projects
from .engines import EngineError, get_engine, list_engines
from .engines.base import SynthRequest
from .jobs import manager
from .render import RenderOptions, VoiceSetting, render_cue, timeline
from .script_parser import Cue, parse_script
from .voices import LANGUAGES, describe_blend, lang_of

config.ensure_dirs()

app = FastAPI(title="Speech Creator", version="1.0.0")

MAX_PREVIEW_CHARS = 600
MAX_REF_BYTES = 25 * 1024 * 1024
ALLOWED_REF_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


@app.exception_handler(EngineError)
async def engine_error_handler(_request: Request, exc: EngineError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# --------------------------------------------------------------------------
# Metadados
# --------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "version": app.version,
        "ffmpeg": A.has_ffmpeg(),
        "engines": {e.id: e.is_available() for e in list_engines()},
    }


@app.get("/api/engines")
def api_engines() -> dict:
    return {"engines": [e.to_dict() for e in list_engines()]}


@app.get("/api/voices")
def api_voices(engine: str = "kokoro", lang: str | None = None) -> dict:
    eng = get_engine(engine)
    voices = eng.list_voices()
    if lang:
        voices = [v for v in voices if v.lang == lang]
    return {
        "engine": engine,
        "voices": [v.to_dict() for v in voices],
        "languages": LANGUAGES,
        "supports_cloning": eng.supports_cloning,
        "supports_blending": eng.supports_blending,
    }


@app.get("/api/emotions")
def api_emotions() -> dict:
    """Presets de prosodia. Com o Kokoro moldam a entrega; com o Chatterbox
    tambem ajustam a expressividade do modelo."""
    return {"emotions": emotions.catalog(), "default": emotions.DEFAULT}


@app.get("/api/effects")
def api_effects() -> dict:
    return {"effects": effects.catalog(), "default": effects.DEFAULT}


# --------------------------------------------------------------------------
# Roteiro
# --------------------------------------------------------------------------


@app.post("/api/parse")
async def api_parse(payload: dict) -> dict:
    """Analisa o roteiro e, se o elenco vier junto, preve as pausas.

    A previsao sai do mesmo codigo que renderiza, para a linha do tempo
    mostrada na interface nao divergir do audio gerado.
    """
    script = payload.get("script", "")
    if not isinstance(script, str):
        raise HTTPException(status_code=400, detail="Campo 'script' deve ser texto.")

    out = parse_script(script).to_dict()
    cast = {name: VoiceSetting.from_dict(data) for name, data in (payload.get("cast") or {}).items()}
    for name, setting in cast.items():
        setting.speaker = name
    out["timeline"] = timeline(script, cast, RenderOptions.from_dict(payload.get("options") or {}))
    return out


@app.post("/api/preview")
async def api_preview(payload: dict) -> Response:
    """Gera uma amostra curta de uma voz e devolve o WAV direto."""
    text = (payload.get("text") or "Teste de voz para o show da banda.").strip()
    if len(text) > MAX_PREVIEW_CHARS:
        text = text[:MAX_PREVIEW_CHARS]

    setting = VoiceSetting.from_dict(payload.get("setting") or payload)
    opts = RenderOptions.from_dict(payload.get("options") or {})
    opts.per_line_files = False

    cue = Cue(kind="speech", speaker=setting.speaker or "Preview", text=text)
    wav, sr = render_cue(cue, setting, opts)
    if not len(wav):
        raise HTTPException(status_code=400, detail="A sintese nao produziu audio.")

    return Response(
        content=A.wav_bytes(wav, sr),
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "X-Duration": str(round(A.duration(wav, sr), 2)),
            "X-Voice": describe_blend(setting.voice) if setting.engine == "kokoro" else setting.voice,
        },
    )


# --------------------------------------------------------------------------
# Renderizacao
# --------------------------------------------------------------------------


@app.post("/api/render")
async def api_render(payload: dict) -> dict:
    script = payload.get("script", "")
    if not script.strip():
        raise HTTPException(status_code=400, detail="O roteiro esta vazio.")

    cast = {name: VoiceSetting.from_dict(data) for name, data in (payload.get("cast") or {}).items()}
    for name, setting in cast.items():
        setting.speaker = name

    opts = RenderOptions.from_dict(payload.get("options") or {})
    job = manager.submit(script, cast, opts, title=payload.get("name", ""))
    return job.to_dict()


@app.get("/api/jobs")
def api_jobs() -> dict:
    return {"jobs": [j.to_dict() for j in manager.list()]}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict:
    job = manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job nao encontrado.")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
def api_job_cancel(job_id: str) -> dict:
    if not manager.cancel(job_id):
        raise HTTPException(status_code=400, detail="Job nao pode mais ser cancelado.")
    return {"ok": True}


def _job_file(job_id: str, rel_path: str) -> Path:
    """Resolve um arquivo dentro da pasta do job, barrando path traversal."""
    job = manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job nao encontrado.")
    root = Path(job.out_dir).resolve()
    target = (root / rel_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado.")
    return target


@app.get("/api/jobs/{job_id}/file/{rel_path:path}")
def api_job_file(job_id: str, rel_path: str) -> FileResponse:
    path = _job_file(job_id, rel_path)
    media = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".json": "application/json"}
    return FileResponse(path, media_type=media.get(path.suffix, "application/octet-stream"))


@app.get("/api/jobs/{job_id}/download")
def api_job_download(job_id: str, format: str = "wav") -> FileResponse:
    job = manager.get(job_id)
    if not job or not job.manifest:
        raise HTTPException(status_code=404, detail="Renderizacao ainda nao concluida.")
    rel = job.manifest["files"].get(format)
    if not rel:
        raise HTTPException(status_code=404, detail=f"Formato '{format}' nao foi gerado.")
    path = _job_file(job_id, rel)
    safe_title = re.sub(r"[^\w\- ]", "", job.title).strip() or "show"
    return FileResponse(
        path,
        media_type="audio/mpeg" if format == "mp3" else "audio/wav",
        filename=f"{safe_title}.{format}",
    )


# --------------------------------------------------------------------------
# Projetos
# --------------------------------------------------------------------------


@app.get("/api/projects")
def api_projects() -> dict:
    return {"projects": projects.list_all()}


@app.post("/api/projects")
async def api_project_save(payload: dict) -> dict:
    try:
        return projects.save(payload, payload.get("id"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}")
def api_project_get(project_id: str) -> dict:
    try:
        data = projects.load(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not data:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado.")
    return data


@app.delete("/api/projects/{project_id}")
def api_project_delete(project_id: str) -> dict:
    try:
        ok = projects.delete(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado.")
    return {"ok": True}


# --------------------------------------------------------------------------
# Amostras de referencia (para clonagem de voz)
# --------------------------------------------------------------------------


@app.get("/api/refs")
def api_refs() -> dict:
    items = []
    for path in sorted(config.REFS_DIR.glob("*")):
        if path.suffix.lower() in ALLOWED_REF_SUFFIXES:
            items.append({"name": path.name, "path": str(path), "size": path.stat().st_size})
    return {"refs": items}


@app.post("/api/refs")
async def api_ref_upload(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_REF_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Formato nao suportado. Use: {', '.join(sorted(ALLOWED_REF_SUFFIXES))}",
        )

    data = await file.read(MAX_REF_BYTES + 1)
    if len(data) > MAX_REF_BYTES:
        raise HTTPException(status_code=400, detail="Arquivo maior que 25 MB.")

    stem = re.sub(r"[^\w\-]", "_", Path(file.filename or "amostra").stem)[:40] or "amostra"
    dest = config.REFS_DIR / f"{stem}_{uuid.uuid4().hex[:6]}{suffix}"
    dest.write_bytes(data)
    return {"name": dest.name, "path": str(dest), "size": len(data)}


@app.delete("/api/refs/{name}")
def api_ref_delete(name: str) -> dict:
    target = (config.REFS_DIR / name).resolve()
    if not target.is_relative_to(config.REFS_DIR.resolve()) or not target.is_file():
        raise HTTPException(status_code=404, detail="Amostra nao encontrada.")
    target.unlink()
    return {"ok": True}


# --------------------------------------------------------------------------
# Interface
# --------------------------------------------------------------------------

if config.WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")
