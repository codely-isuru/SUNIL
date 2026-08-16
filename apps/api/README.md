# sunil-api

The SUNIL backend: FastAPI orchestrator, agent framework, tool framework and
provider adapters. See `../../docs/ARCHITECTURE_V1.md` for the architecture
and `../../docs/M1_BUILD_PLAN.md` for the task-by-task build order.

## Setup (Windows / PowerShell)

```powershell
cd apps\api
python -m venv .venv                       # `python`, never `python3` — the
                                            # python3 alias on this machine is
                                            # a broken Microsoft Store stub.
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

copy ..\..\.env.example ..\..\.env         # then fill in the secrets
alembic upgrade head                       # once migrations exist (T2)
uvicorn sunil.main:app --host localhost --port 8000 --reload
```

Or run the whole sequence via `..\..\scripts\dev-api.ps1` from the repo root.

Ports: API **8000**, web **3000**. **Never bind port 4317** — it is the
Minions Portal, running on the same machine.

## Configuration

All configuration is read once, in `sunil/settings.py`, via
`pydantic-settings`. Every variable is documented in
`../../docs/ARCHITECTURE_V1.md` §14.4 and has a placeholder entry in
`../../.env.example`. Secrets (`ANTHROPIC_API_KEY`, `GITHUB_TOKEN`,
`SESSION_SECRET`, `OWNER_PASSWORD`, `DATABASE_URL`) are typed `SecretStr` —
call `.get_secret_value()` explicitly at the point of use; never log or
`print()` a `Settings` field directly.

`config/*.yaml` (agents, tools, permissions, projects, models) is separate
from this package and is read from `SUNIL_CONFIG_DIR` (default `./config`)
— see ADR-016. It is not built by T1.

## Testing and linting

```powershell
cd apps\api
pytest -q
ruff check .
ruff format --check .
```

`tests/unit/` is owned per-module by the backend engineers who wrote that
module. `tests/integration/` and `tests/exit/` are QA's (T18);
`tests/security/` is Security's (T19). No file under `tests/` is written by
two lanes.

## Package layout

```
sunil/
  __init__.py
  settings.py        # pydantic-settings Settings — the only env-var seam
  logging.py         # structlog JSON config; routes uvicorn's loggers in
  main.py            # create_app() — FastAPI factory (T1); extended by T5
  db/                # ORM models, session, migrations glue (T2)
  api/               # routes, middleware, schemas (T5, T11a)
  core/
    trace/
      stages.py      # TraceStage — the twelve NFR-020 stage names (T1)
      context.py     # TraceContext Protocol + NullTraceContext (T1);
                      # concrete implementation lands with T4
      emitter.py      # T4
    ...              # orchestrator, registry, permissions, routing, etc.
  providers/         # LLMProvider Protocol + Anthropic adapter (T6)
  agents/            # agent implementations (T10)
  tools/             # tool adapters, e.g. github/ (T8)
```
