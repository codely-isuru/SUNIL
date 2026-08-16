# Backend dev bootstrap + run. See docs/ARCHITECTURE_V1.md §14.1.
#
# Creates/reuses apps/api/.venv, installs sunil-api editable with dev
# extras, copies .env.example -> .env if .env is missing (never overwrites
# an existing .env), runs the Alembic migration if it exists yet (T2), and
# starts uvicorn.
#
# `python`, never `python3` on this machine — `python3` launches the
# Microsoft Store stub (docs/ENVIRONMENT.md §1).

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$apiDir = Join-Path $repoRoot "apps\api"

if (-not (Test-Path $apiDir)) {
    throw "apps\api not found under $repoRoot — run this from a checkout of the SUNIL repo."
}

Push-Location $apiDir
try {
    if (-not (Test-Path ".venv")) {
        Write-Host "Creating virtual environment (apps\api\.venv)..."
        python -m venv .venv
    }

    Write-Host "Installing sunil-api (editable, dev extras)..."
    & ".\.venv\Scripts\python.exe" -m pip install -e ".[dev]" --quiet

    $envExample = Join-Path $repoRoot ".env.example"
    $envFile = Join-Path $repoRoot ".env"
    if (-not (Test-Path $envFile)) {
        Write-Host "No .env found at repo root — copying .env.example. Fill in the secrets before running for real."
        Copy-Item $envExample $envFile
    }

    if (Test-Path "alembic.ini") {
        Write-Host "Running migrations (alembic upgrade head)..."
        & ".\.venv\Scripts\alembic.exe" upgrade head
    }
    else {
        Write-Host "alembic.ini not present yet (lands with T2) — skipping migrations."
    }

    Write-Host "Starting uvicorn on http://localhost:8000 ..."
    # --host localhost, not 127.0.0.1: avoids the localhost/127.0.0.1 cookie
    # trap noted in docs/ARCHITECTURE_V1.md §14.1 and M1_BUILD_PLAN.md §11.2.
    & ".\.venv\Scripts\uvicorn.exe" sunil.main:app --host localhost --port 8000 --reload
}
finally {
    Pop-Location
}
