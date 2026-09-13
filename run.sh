#!/usr/bin/env bash
# Sobe o Speech Creator. Cria o ambiente virtual e instala tudo na primeira vez.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
PY="${PYTHON:-python3}"

if [ ! -d .venv ]; then
  echo "==> Criando ambiente virtual..."
  "$PY" -m venv .venv
  echo "==> Instalando dependencias (alguns minutos na primeira vez)..."
  .venv/bin/pip install --upgrade pip --quiet
  .venv/bin/pip install -r requirements.txt
fi

if ! command -v espeak-ng >/dev/null 2>&1; then
  echo "AVISO: espeak-ng nao encontrado. E necessario para a conversao de texto em fonemas."
  echo "  macOS:  brew install espeak-ng"
  echo "  Ubuntu: sudo apt install espeak-ng"
  echo
fi

echo "==> Speech Creator em http://127.0.0.1:${PORT}"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
