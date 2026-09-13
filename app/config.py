"""Caminhos e configurações globais da aplicação."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

DATA_DIR = Path(os.environ.get("SPEECH_CREATOR_DATA", BASE_DIR / "data"))
PROJECTS_DIR = DATA_DIR / "projects"
OUTPUT_DIR = DATA_DIR / "output"
REFS_DIR = DATA_DIR / "refs"
CACHE_DIR = DATA_DIR / "cache"

# Motor usado quando o projeto nao especifica nenhum.
DEFAULT_ENGINE = os.environ.get("SPEECH_CREATOR_ENGINE", "kokoro")

# "cpu" ou "cuda". Kokoro roda confortavelmente em CPU.
DEVICE = os.environ.get("SPEECH_CREATOR_DEVICE", "cpu")

# Quantas renderizacoes podem rodar ao mesmo tempo. Sintese e pesada em CPU,
# entao 1 evita que o processo estoure a memoria com varios modelos ativos.
RENDER_WORKERS = int(os.environ.get("SPEECH_CREATOR_WORKERS", "1"))

# Limite de caracteres por fala, para evitar que um erro de digitacao vire
# uma renderizacao de 40 minutos.
MAX_CHARS_PER_CUE = int(os.environ.get("SPEECH_CREATOR_MAX_CHARS", "5000"))

# Jobs terminados sao mantidos em memoria para consulta; alem disso os WAVs
# ficam em disco ate o usuario limpar.
MAX_JOBS_IN_MEMORY = 50


def ensure_dirs() -> None:
    for d in (DATA_DIR, PROJECTS_DIR, OUTPUT_DIR, REFS_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
