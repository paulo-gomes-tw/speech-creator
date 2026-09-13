# Sobe o Speech Creator no Windows.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$port = if ($env:PORT) { $env:PORT } else { "8000" }

if (-not (Test-Path .venv)) {
  Write-Host "==> Criando ambiente virtual..."
  python -m venv .venv
  Write-Host "==> Instalando dependencias (alguns minutos na primeira vez)..."
  .\.venv\Scripts\pip.exe install --upgrade pip --quiet
  .\.venv\Scripts\pip.exe install -r requirements.txt
}

if (-not (Get-Command espeak-ng -ErrorAction SilentlyContinue)) {
  Write-Host "AVISO: espeak-ng nao encontrado. Instale com: winget install espeak-ng" -ForegroundColor Yellow
}

Write-Host "==> Speech Creator em http://127.0.0.1:$port"
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port $port
