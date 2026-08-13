# SUNIL — Environment Readiness Survey (V1 build machine)

**Machine:** `win32` (Windows 11 Pro 10.0.26200), primary shell PowerShell, Git Bash also
available. Repo: `C:\repo\SUNIL`, branch `main`.

**Purpose:** read-only fact-finding pass so the Solution Architect designs against what this
machine actually has, not what it might have. Nothing was installed or changed. All commands
below were run and their exact output is reflected in the "Version / evidence" column.

**Target stack (`docs/ROADMAP.md` §4):** Python + FastAPI + PostgreSQL + pgvector + Redis +
Docker (backend), Next.js/React/Tailwind (frontend), on Windows 11.

**Survey date:** 2026-08-13.

---

## 1. Python

| Check | Result |
|---|---|
| `python --version` | Python 3.13.14 |
| `py -0p` | one interpreter registered: `-V:3.13 *` → `C:\Users\Isu30\AppData\Local\Programs\Python\Python313\python.exe` |
| `pip --version` | pip 26.1.2 (python 3.13) |
| `python -m venv --help` | works (venv module present and functional) |
| `python3 --version` | **fails** — Windows App Execution Alias stub: *"Python was not found; run without arguments to install from the Microsoft Store..."* — this is the known broken-stub gotcha, not a real interpreter |

**V1 implication:** Python 3.13 + pip + venv are ready for FastAPI development. Any script,
CI config, or `package.json`/Makefile helper **must call `python`, never `python3`**, or it
will silently try to launch the Microsoft Store on this machine.

---

## 2. Node / package managers

| Check | Result |
|---|---|
| `node --version` | v24.19.0 |
| `npm --version` | 11.17.0 |
| `pnpm --version` | 11.8.0 |
| `yarn --version` | not found (`yarn: command not found`) |

**Repo note:** `C:\repo\SUNIL\node_modules\` exists and is stale — left over from the retired
TypeScript/NestJS Phase-0/1 build (per `docs/STATUS.md` §4, archived at tag
`archive/v0-typescript-foundation`). It **is** listed in `.gitignore` (line 14,
`node_modules/`) and `git check-ignore -v` confirms it is correctly ignored. Left untouched
per instructions — do not delete; it will be superseded when the new Next.js frontend
workspace (`apps/web`) is created.

**V1 implication:** Node 24 + npm + pnpm are ready for the Next.js frontend. No yarn — use
pnpm (already the more modern choice and already present) for the new frontend workspace, not
yarn. Do not `npm install` at repo root — the new frontend should get its own workspace
(e.g. `apps/web/`) with its own lockfile so it doesn't collide with the stale directory.

---

## 3. Docker

| Check | Result |
|---|---|
| `docker --version` | Docker version 29.7.2, build a7dcaa6 |
| `docker compose version` | Docker Compose v5.3.1 (bundled CLI plugin) |
| `docker info` | Client info returns fully (rich plugin set: buildx, scout, model, mcp, etc.) but the **Server section fails**: `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; ... The system cannot find the file specified.` |
| `wsl -l -v` | one distro registered: `docker-desktop`, state **Stopped**, WSL version 2 |

**Docker Desktop is installed but the daemon is NOT running.** The WSL2 backing distro exists
but is stopped, i.e. Docker Desktop itself has not been launched on this machine (or was
closed). Per task instructions, the daemon was **not started** — this is reported, not fixed.

**V1 implication:** `docker compose up` for Postgres/Redis/pgvector containers will fail
until a human starts Docker Desktop (which will spin the WSL2 distro back up
automatically). This is a two-second manual action, not an install — no CLI command is
needed, just launching the Docker Desktop application. Linux containers are supported
(WSL2 backend, confirmed by the `docker-desktop` distro) once the daemon is up.

---

## 4. PostgreSQL

| Check | Result |
|---|---|
| `where psql` / `psql --version` | not found on PATH |
| Laragon Postgres bin | `C:\laragon\bin\postgresql` does not exist — no Laragon Postgres install found |
| Windows service scan (`sc query state=all \| grep -i postgres`) | no match — no Postgres Windows service registered |
| `where pg_config` | not found |
| Port 5432 | not in the LISTENING set observed (see §7) — free |

**No local PostgreSQL install of any kind (native or Laragon) was found on this machine, and
no `pg_config`/`pgvector` build tooling was found either.**

**V1 implication:** Postgres + pgvector for V1 must come from the Docker Compose stack
(`docker.io/pgvector/pgvector` or `postgres` + the `pgvector` extension image), per
`ROADMAP.md` §20/§23 Step 1. There is no local fallback Postgres to develop against while
Docker is down — Docker Desktop being started is on the critical path for any DB-backed work.

---

## 5. Redis

| Check | Result |
|---|---|
| `where redis-server` / `redis-cli --version` | not found |
| WSL Redis | the only WSL distro present is `docker-desktop` (Stopped) — no separate Linux distro with Redis installed |
| Port 6379 | not in the LISTENING set observed (see §7) — free |

**Confirmed absent, as expected.**

**V1 implication:** Redis, like Postgres, must come from Docker Compose. Same dependency on
Docker Desktop being started.

---

## 6. Git

| Check | Result |
|---|---|
| `git --version` | git version 2.48.1.windows.1 |
| `git config user.name` | codely-isuru |
| `git config user.email` | isuru@codely.digital |
| `git config --list --show-origin \| grep credential` | `credential.helper=manager` (Git Credential Manager, from the global Git for Windows install config) — no separate PAT-in-URL or plaintext credential store detected |
| Remote | `origin → https://github.com/codely-isuru/SUNIL.git` (fetch+push, matches expected repo) |
| `git ls-remote origin HEAD` | succeeded, returned `d2418660446824d23e61bd1abd6016910cb16022  HEAD` — confirms the remote is reachable and authentication works from this machine |
| `git status` at survey time | on `main`, up to date with `origin/main`, **3 files already staged** by another agent process: `.minions/memory/backend_engineer.md`, `.minions/memory/business_analyst.md`, `.minions/memory/solution_architect.md` — left untouched, not part of this task |

**V1 implication:** Git push/pull works end-to-end with GCM-managed auth; no action needed.
Note for whoever commits next: there were pre-existing staged files not authored by this
survey — commit them deliberately and separately, don't sweep them in accidentally.

---

## 7. Other ports (dev port scan)

`netstat -ano` filtered to 3000, 3001, 4317, 5173, 8000, 8080, 5432, 6379:

| Port | Status | Notes |
|---|---|---|
| 3000 | free | — |
| 3001 | free | — |
| **4317** | **LISTENING** (PID 27272, 127.0.0.1) | **Minions Portal — must stay free / not be reused for SUNIL services** |
| 5173 | free | — |
| 8000 | free | — |
| 8080 | free | — |
| 5432 | free | no local Postgres running (consistent with §4) |
| 6379 | free | no local Redis running (consistent with §5) |

**V1 implication:** the whole target port range (FastAPI on 8000, Next.js dev on 3000/3001,
Vite-style tooling on 5173, Postgres 5432, Redis 6379) is free right now. Only constraint:
**never bind anything to 4317** — that's the Minions Portal.

---

## 8. Secrets / config surface

| Check | Result |
|---|---|
| `C:\repo\env\FTP Accounts.txt` | **exists** (existence only checked — file was not opened, contents not read or reported, per hard rule) |
| `ANTHROPIC_API_KEY` env var | **not set** in this shell |
| `OPENAI_API_KEY` env var | **not set** in this shell |

**V1 implication:** no provider API keys are present in the ambient environment on this
machine. This is consistent with the existing memory note that Claude access here runs
CLI-first on a subscription, not a raw API key. For the Model Router's Claude/OpenAI
provider adapters (`ROADMAP.md` Epic 3), keys will need to be sourced from a secrets
manager (per the DevOps "secrets manager only" rule) and injected as container/environment
variables at deploy time — not read from this ambient shell and not committed to
`.env`/`.env.example` with real values.

---

## Gaps — what must happen before M1 development can begin

In priority order (suggested commands are for the human to run; none were executed by this
survey):

1. **Start Docker Desktop** (daemon is installed but not running). This blocks Postgres,
   pgvector, and Redis entirely for local dev, since neither is installed natively.
   Suggested action: launch the Docker Desktop application from the Start Menu, then verify
   with `docker info` (should show a populated `Server:` section).

2. **Bring up the Postgres + pgvector + Redis containers** once Docker is running. No
   `docker-compose.yml` exists yet in the repo (Step 1 of `ROADMAP.md` §23 is not started).
   Suggested action (once the compose file is authored in Stage 4): `docker compose up -d`.

3. **Decide and provision provider credentials** (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` or
   equivalent) via the secrets manager for the Model Router providers — currently absent
   from this machine's environment. Suggested action: add them to the team's secrets
   manager (not a local `.env` with real values) before Epic 3 (Provider Abstraction) build
   work starts.

4. **No blockers for Python or Node/pnpm** — both are ready as-is. No action needed.

5. **Minor housekeeping (non-blocking):** when the new `apps/web` Next.js workspace is
   created, initialise it in its own directory so it does not collide with the stale
   root-level `node_modules/` left from the retired TS build; that directory can be deleted
   once the new frontend workspace supersedes it (owner's call, not this survey's).
