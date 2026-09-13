"""Fila de renderizacao em background com acompanhamento de progresso."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .render import RenderOptions, VoiceSetting, render_script


@dataclass
class Job:
    id: str
    status: str = "queued"  # queued | running | done | error | cancelled
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    current: int = 0
    total: int = 0
    message: str = ""
    error: str | None = None
    manifest: dict | None = None
    out_dir: str = ""
    title: str = ""
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def progress(self) -> float:
        return round(self.current / self.total, 4) if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "title": self.title,
            "current": self.current,
            "total": self.total,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "manifest": self.manifest,
            "created_at": self.created_at,
            "elapsed": round((self.finished_at or time.time()) - (self.started_at or self.created_at), 1),
        }


class JobManager:
    def __init__(self, workers: int = 1) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="render")
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def submit(
        self,
        script: str,
        cast: dict[str, VoiceSetting],
        opts: RenderOptions,
        title: str = "",
    ) -> Job:
        job_id = uuid.uuid4().hex[:12]
        out_dir = config.OUTPUT_DIR / job_id
        job = Job(id=job_id, out_dir=str(out_dir), title=title or "Show sem titulo")

        with self._lock:
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._evict_locked()

        self._pool.submit(self._run, job, script, cast, opts, out_dir)
        return job

    def _run(self, job: Job, script: str, cast, opts, out_dir: Path) -> None:
        job.status = "running"
        job.started_at = time.time()

        def on_progress(current: int, total: int, message: str) -> None:
            job.current, job.total, job.message = current, total, message

        try:
            job.manifest = render_script(
                script, cast, opts, out_dir,
                progress=on_progress,
                cancelled=job._cancel.is_set,
            )
            job.status = "cancelled" if job._cancel.is_set() else "done"
            job.current = job.total
            job.message = "Concluido" if job.status == "done" else "Cancelado"
        except Exception as exc:
            job.status = "cancelled" if job._cancel.is_set() else "error"
            job.error = str(exc)
            job.message = job.error
            if job.status == "error":
                traceback.print_exc()
        finally:
            job.finished_at = time.time()

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in {"done", "error", "cancelled"}:
            return False
        job._cancel.set()
        job.message = "Cancelando..."
        return True

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 20) -> list[Job]:
        with self._lock:
            return [self._jobs[i] for i in reversed(self._order[-limit:]) if i in self._jobs]

    def _evict_locked(self) -> None:
        """Descarta os jobs terminados mais antigos, preservando a ordem.

        Jobs ativos nunca sao descartados; se todos estiverem ativos a fila
        simplesmente passa do limite ate algum terminar.
        """
        excedente = len(self._order) - config.MAX_JOBS_IN_MEMORY
        if excedente <= 0:
            return
        mantidos: list[str] = []
        for job_id in self._order:
            job = self._jobs.get(job_id)
            terminado = job is None or job.status in {"done", "error", "cancelled"}
            if excedente > 0 and terminado:
                self._jobs.pop(job_id, None)
                excedente -= 1
            else:
                mantidos.append(job_id)
        self._order = mantidos


manager = JobManager(workers=config.RENDER_WORKERS)
