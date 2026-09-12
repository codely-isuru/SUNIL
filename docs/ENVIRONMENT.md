# SUNIL — Environment Readiness Survey (V1 build machine)

**Machine:** `win32` (Windows 11 Pro 10.0.26200), primary shell PowerShell, Git Bash also
available. Repo: `C:\repo\SUNIL`, branch `main`.

**Purpose:** read-only fact-finding pass so the Solution Architect designs against what this
machine actually has, not what it might have. Nothing was installed or changed. All commands
below were run and their exact output is reflected in the "Version / evidence" column.

**Target stack (`docs/ROADMAP.md` §4):** Python + FastAPI + PostgreSQL + pgvector + Redis +
Docker (backend), Next.js/React/Tailwind (frontend), on Windows 11.

**Survey date:** 2026-08-13. **Docker section corrected 2026-08-14 (T21)** — the daemon has since
been started; see §3.

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

**Updated 2026-08-14 (T21) — corrects the 2026-08-13 survey below, which is now stale.**

| Check | Result |
|---|---|
| `docker --version` | Docker version 29.7.2, build a7dcaa6 |
| `docker compose version` | Docker Compose version v5.3.1 |
| `docker info` | **Server section now returns.** `OperatingSystem: Docker Desktop`, `OSType: linux`, `ServerVersion: 29.7.2` — Linux containers, confirmed live by direct re-check during T21 |

**Docker Desktop's daemon is now running** (it was not, at the 2026-08-13 survey below — someone
started it since). Linux containers, Compose v5.3.1, server 29.7.2, all verified. This makes the
no-Docker path a **contingency**, not the plan (`docs/ARCHITECTURE_V1.md` §15 item 5) — it does
**not** put Docker/Postgres/Redis back on M1's critical path. SQLite remains the M1 default
(ADR-001); Docker is still needed before Gate 3 to verify the Alembic migration once against real
PostgreSQL (debt D-2).

**V1 implication:** `docker compose up` for Postgres/Redis/pgvector containers will now work as
soon as a compose file exists (T17, optional/post-M1 per `docs/M1_BUILD_PLAN.md` §9 — no compose
file is committed yet as of T21). Nothing in M1's critical path depends on this.

<details>
<summary>Original 2026-08-13 survey (superseded by the above; kept for history)</summary>

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

</details>

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

## 9. V2 platform (added 2026-09-10, Phase 0 — `docs/tasks/P0-platform.md`)

**This section carries the current facts.** §1–§8 above are a dated V1 survey and are kept as
history; where they disagree with this section, this section wins — notably §7, which recorded
port 5432 as free (it is not, see below).

The `V2` branch is a clean-slate rebuild with **no application code** (ADR-030 Amendment 1), so
the platform is infrastructure only: Postgres+pgvector, LiteLLM, n8n. It boots green with zero
app containers, and `infra/docker-compose.yml` carries a commented `api` stub showing exactly
where the rebuilt gateway plugs in.

### Ports

| Service | Host port | Container port | Why not the default |
|---|---|---|---|
| Postgres 17 + pgvector | **5433** | 5432 | 5432 is taken by an unrelated container on this machine (`strapi-next-starter-db-1`) |
| LiteLLM proxy | **4000** | 4000 | LiteLLM's own default; free here |
| n8n | **5680** | 5678 | **both** 5678 and 5679 are held by a single host-native node process — the local n8n source build at `C:\repo\n8n`. 5680 is the first free port after them |
| *(reserved)* | ~~4317~~ | — | **Minions Portal. Never bind it.** CI fails the build if the compose file publishes 4317 |

Container-internal ports are deliberately left at their conventional values, so service-to-service
URLs are the boring ones (`postgres:5432`, `litellm:4000`, `n8n:5678`). Only the host mappings move.

### Pinned images

| Service | Image | Why this pin |
|---|---|---|
| Postgres | `pgvector/pgvector:0.8.6-pg17` | pgvector project's own image, built on official `postgres:17`; pins extension **and** server version independently |
| LiteLLM | `ghcr.io/berriai/litellm:v1.83.14-stable.patch.3` | the vetted `-stable` release lane, not the weekly `v1.89.x` head |
| n8n | `n8nio/n8n:2.38.5` | the digest upstream's `stable` tag currently resolves to |

CI rejects any floating tag (`:latest`, `:stable`, `:main`, `:next`, `:beta`) or untagged image.

### How to boot

```powershell
# from the repo root
copy .env.example .env      # then edit: the required values are dummies
./scripts/dev-up.ps1        # boots, waits for healthchecks, prints status
./scripts/dev-down.ps1      # teardown; add -Volumes to discard all data
```

```bash
cp .env.example .env
./scripts/dev-up.sh         # --pull to refresh images, --timeout N to extend the wait
./scripts/dev-down.sh       # --volumes to discard all data
```

**Preferred: do not copy the template — just run `dev-up`.** With no `.env` present it creates
one and generates real random values for the secrets (see *Secrets* below), which is why the
`copy .env.example .env` line above is now the fallback rather than the first step.

The scripts check the Docker **daemon** (not just the CLI), create `.env` and
`infra/.env.litellm` from their templates if missing (generating the secrets they can), **refuse
to boot if any required secret is still a `dummy`/`change-me` template value**, warn about
host-level port conflicts, validate the compose file, then block until every healthcheck reports
`healthy`. They are idempotent.

Raw equivalent — note the explicit `--env-file`, without which Compose looks for `infra/.env`
next to the compose file rather than the repo-root `.env`:

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d
```

### First boot

Slower than later ones (measured: 44s on this machine): Postgres runs `initdb` plus
`infra/postgres/init/01-init-databases.sh`, which enables `vector` + `uuid-ossp`, creates the
`litellm` and `n8n` databases **and their two least-privilege roles**, and revokes `CONNECT` on
`sunil` from both; then LiteLLM pushes its Prisma schema (70 tables) and n8n runs its own
migrations (136 tables). That init script only runs on an **empty** volume — to re-run it you
must `dev-down --volumes`, which destroys the data.

Two things that make a first boot fail where a re-boot succeeds, both found the hard way:

- **The init script must be LF.** It is bind-mounted and executed inside a Linux container; with
  CRLF the kernel cannot find the interpreter and the container exits **255**. `.gitattributes`
  enforces LF, but a worktree created while `core.autocrlf=true` can still hold CRLF on disk —
  `git rm --cached -r . && git reset --hard HEAD` renormalises it. `file infra/postgres/init/*.sh`
  should say nothing about CRLF.
- **"It booted" is not "it first-booted".** If `sunil-v2_pgdata` already exists, the init script
  does not run at all and the log lines you are reading are from an earlier volume. Check
  `docker volume ls --filter name=sunil-v2` is empty before claiming first-boot evidence.
  When tearing down, name the volumes deliberately: this host also carries `sunil_pgdata` /
  `sunil_redisdata` from V1 and volumes for six unrelated projects.
- **A stale `n8n_data` volume stops n8n booting at all** (added 2026-09-12, Stream E). The
  symptom is `Mismatching encryption keys` in the n8n log: the volume holds a credential vault
  encrypted under the `N8N_ENCRYPTION_KEY` of whichever `.env` created it, and a freshly
  generated `.env` carries a different one. The fix is `./scripts/dev-down.sh --volumes` — which
  **also destroys the Postgres volume**, so read the bullet above before running it. To keep
  another round's data instead, boot under your own `COMPOSE_PROJECT_NAME` (a `.env` value) and
  get your own volumes — that is how the Stream E round ran alongside an existing stack.

### Health endpoints

- Postgres — `pg_isready`, or `docker exec sunil-v2-postgres psql -U sunil -d sunil -c 'select 1'`
- LiteLLM — `http://localhost:4000/health/liveliness` (no provider calls) and `/health/readiness`
  (includes DB status). UI at `/ui`. `/health` fans out to upstream providers and will fail with
  dummy keys — that is expected, not a broken stack.
- n8n — `http://localhost:5680/healthz`

### Loopback binding (added 2026-09-10, fix round)

**Every published port is bound to `127.0.0.1` explicitly**, and CI parses the resolved compose
config to assert it. A bare `"5433:5432"` publishes on `0.0.0.0` — every interface, including the
LAN and each WSL/Docker virtual adapter — which is the configuration ADR-032 rejects by name.
Phase 0 shipped that way for a day and it was reachable off-box: reviewers got HTTP 200 for n8n
and LiteLLM from `172.21.240.1`. n8n is the worst case, because its first-boot owner-setup screen
is unauthenticated — whoever reaches the port first owns the vault. Verified after the fix:
`curl` to all three ports on all three of this host's IPv4 addresses is refused, while
`127.0.0.1` answers.

The same rule applies to host-native processes: `API_HOST=127.0.0.1`, never `0.0.0.0`.

### Two env files, on purpose (added 2026-09-10, fix round)

| File | Tracked? | Who reads it |
|---|---|---|
| `.env` | no (`.env.example` is) | Compose interpolation — every service, plus host-native app processes |
| `infra/.env.litellm` | no (`infra/.env.litellm.example` is) | the **LiteLLM container only**, via `env_file:` |

Upstream provider keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) and `LITELLM_SALT_KEY` live in the
second file. ADR-030 §2 promises the application never holds an upstream credential, and a single
shared `.env` quietly broke that: every process reading it saw the provider keys.
`LITELLM_MASTER_KEY` stays in `.env` — it is the gateway's admin credential, and the app
authenticates with a **virtual** key minted against it (`LITELLM_VIRTUAL_KEY_DEFAULT`).

Do not name a provider key in the litellm service's `environment:` block: `environment:` overrides
`env_file:`, so an interpolation from `.env` would silently blank the scoped value.

### Three database roles (added 2026-09-10, fix round)

| Database | Owner role | Can connect to `sunil`? |
|---|---|---|
| `sunil` | `sunil` (superuser) | — |
| `litellm` | `litellm_user` | **no** (`CONNECT` revoked) |
| `n8n` | `n8n_user` | **no** (`CONNECT` revoked) |

`CONNECT` is also revoked from `PUBLIC` on all three, since Postgres grants it implicitly and the
named revokes would otherwise be cosmetic. Rationale (TB9): `sunil` holds `approvals` and
`audit_events`, and ADR-031's startup re-scan *executes* what it finds in state `approved` — a
compromised n8n holding superuser could flip a row and have SUNIL act on it. Passwords:
`LITELLM_DB_PASSWORD`, `N8N_DB_PASSWORD`, **alphanumeric only** (both are embedded in a
connection URL). Applied by the init script, which runs once per volume — changing them later
needs `ALTER ROLE`, not an edit to `.env`.

### Secrets

`.env` is gitignored; only `.env.example` (dummy values) is committed. Real provider keys come
from the secrets manager (`docs/SECRETS_SETUP.md`) and are held **only** by the LiteLLM
container — the application never receives an upstream provider key (ADR-030 §2). Third-party
credentials for connectors live only in n8n's own vault (ADR-030 §5), encrypted with
`N8N_ENCRYPTION_KEY`; losing or changing that key makes every stored credential undecryptable.

Secrets are referenced in the compose file as `${VAR:?set in .env}` — **mandatory**, no default.
Compose refuses to resolve the file at all if one is unset or empty.

> ~~Secrets are referenced as `${VAR}` with no default, on purpose: unset resolves to empty so
> `docker compose config` still validates in CI, but a container started that way fails loudly
> instead of quietly running a guessable secret.~~
> **Corrected 2026-09-10:** the second half of that was **false**. An empty
> `N8N_ENCRYPTION_KEY` does not fail — n8n silently generates its own, leaving the credential
> vault encrypted under a key nobody manages. Hence `:?`. Consequence: `docker compose config`
> now needs an env file, so CI passes `--env-file .env.example` and a CI step asserts that
> `config` **fails** without one.

**`dev-up` will not boot the stack on a template value.** Any of `POSTGRES_PASSWORD`,
`LITELLM_MASTER_KEY`, `N8N_ENCRYPTION_KEY`, `LITELLM_DB_PASSWORD`, `N8N_DB_PASSWORD` or
`LITELLM_SALT_KEY` still matching `dummy`/`change-me` is rejected with exit 1 before anything
starts. When `dev-up` creates the files for you it **generates** those values from a CSPRNG, so
the normal path is `./scripts/dev-up.sh` with **no `.env` at all** — not `cp .env.example .env`.
This repository is public: a stack running on the template passwords is a stack running on
published passwords.

### Scripts must stay ASCII

`*.ps1` and `*.sh` files are ASCII-only and CI enforces it byte-by-byte. Windows PowerShell 5.1
decodes a BOM-less file as cp1252, so an em dash (`E2 80 94`) becomes three characters ending in
`0x94` = `”` — which PowerShell treats as a string delimiter, silently breaking the parse. This
cost a real debugging cycle during Phase 0. Use `-`, not `—`, in scripts. (Markdown and YAML are
unaffected and may use whatever they like.)

---

## Gaps — what must happen before M1 development can begin

In priority order (suggested commands are for the human to run; none were executed by this
survey):

1. ~~**Start Docker Desktop**~~ — **done, corrected 2026-08-14 (T21).** The daemon is now
   running (server 29.7.2, Linux containers, Compose v5.3.1 — see §3 above, re-verified during
   T21). This is no longer a gap and is not on M1's critical path either way (ADR-001/005/013).

2. **Bring up the Postgres + pgvector + Redis containers**, once a compose file exists. No
   `docker-compose.yml` is committed yet — that is T17's scope, and T17 is pre-classified
   optional/post-M1 (`docs/M1_BUILD_PLAN.md` §9). Suggested action, if/when T17 is built:
   `docker compose up -d`.

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
