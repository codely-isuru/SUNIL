# SUNIL — Phase 1 Local Setup (Windows 11)

_Owner: DevOps / SRE. Covers FR-090–093, NFR-013, NFR-017. Companion files:
`docker-compose.yml`, `docker-compose.dev.yml`, `.env.example` (repo root)._

> **Read this if you have never seen this repository before.** It assumes Windows 11, a shell
> (PowerShell or Git Bash), Docker Desktop, and nothing else. There is **no local `psql`
> client** on this host by design (NFR-013/FR-093) — every database operation below goes
> through `docker compose exec postgres psql …` or Prisma, never a host-installed client.

## 0. Current status of this guide (read this first)

This document describes the **full intended Phase 1 stack** (six Compose services: `postgres`,
`redis`, `api`, `worker`, `scheduler`, `web`). As of this writing:

- **`postgres` and `redis` are real today** — buildable, startable, health-checked and verified
  (see §3–5 below; every command in those sections has actually been run against this exact
  repository state).
- **`api`, `worker`, `scheduler` and `web` are declared in `docker-compose.yml` but not yet
  buildable.** The monorepo scaffold and the application source under `apps/*`/`packages/*`
  now exist, but none of the four apps has a `Dockerfile` yet — that is still a separate, later
  piece of work. Sections that depend on it (bring-up of the full Compose stack, migrations,
  bootstrap, first login, MFA enrolment, `pnpm test`) are written as the **procedure you will
  follow once it lands** — they are accurate to the architecture but cannot be executed via
  Compose yet. Each such section says so.
- **Browser↔API is same-origin (ADR-011, amendment A1).** The portal (`web`) is the only
  browser-facing service in the stack — it proxies `/api/...` to the API internally via
  `SUNIL_API_INTERNAL_URL`. The API's own published port exists for non-browser access only
  (curl, QA test suites, dev tooling) and returns no CORS headers; there is no allowed-origins
  variable and none should ever be added. See §2 step 6 and §3.3.

If you only need Postgres/Redis running for local development against the host-run apps
(the normal day-to-day loop once the scaffold exists), skip to §3.

## 1. Prerequisites

| Tool | Verified version on the reference machine | Notes |
|---|---|---|
| Windows | 11 Pro (10.0.26200) | — |
| Docker Desktop | 29.6.1, daemon running | `docker info` must succeed before anything else. If it doesn't, Docker Desktop isn't running — see §7. |
| Node.js | v22.14.0 | Must satisfy `>=22 <23` (root `package.json` `engines`, enforced by `.npmrc engine-strict=true` once the scaffold lands). |
| pnpm | 11.8.0 | `corepack enable` then `corepack prepare pnpm@11.8.0 --activate`, or install directly. |
| git | any recent version | — |
| A host `psql` client | **not required and not used** | Every DB operation in this guide goes through Docker or Prisma. |

You do **not** need Postgres, Redis, or any language runtime beyond Node installed natively —
they run in containers.

## 2. First-run sequence — get your `.env`

1. Clone the repository and check out `feature/phase-1-foundation` (or your working branch).
2. From the repo root, copy the template:
   ```
   cp .env.example .env
   ```
   (PowerShell: `Copy-Item .env.example .env`)
   `.env` is git-ignored (see `.gitignore`) — it will never be committed. `.env.example` is the
   committed template and must never contain a real value; if you ever see one in a diff, that
   is a defect, stop and flag it.
3. Generate the master encryption key (ADR-006). This is the KEK that wraps every stored
   secret's data-encryption key — losing it makes stored secrets permanently unrecoverable;
   leaking it exposes them. Run **one** of:
   ```
   node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"
   openssl rand -base64 32
   ```
   Paste the output into `.env` as `SUNIL_MASTER_KEY=`. Leave `SUNIL_MASTER_KEY_VERSION=1` as
   shipped in the template. Leave `SUNIL_MASTER_KEY_PREVIOUS` empty (it's only used during a
   key-rotation window).
4. Choose the sole owner account's credentials (FR-014 — exactly one owner is ever created):
   ```
   SUNIL_OWNER_EMAIL=you@example.com
   SUNIL_OWNER_INITIAL_PASSWORD=<a strong passphrase, 16+ chars>
   ```
   You can generate a random one the same way as the master key:
   ```
   node -e "console.log(require('crypto').randomBytes(18).toString('base64url'))"
   ```
   This variable is read once at bootstrap and immediately argon2id-hashed; you can delete it
   from your local `.env` after the first successful bootstrap if you like, and you should
   change the password via the portal after first login.
5. Set real values for the Postgres container credentials if you want anything other than the
   local-only placeholder defaults baked into `docker-compose.yml` (`sunil` / `sunil` /
   `sunil_local_dev_only`) — those defaults are fine for solo local development on a single
   machine and are never exposed to a host port unless you opt into §3.2 below.
   ```
   POSTGRES_USER=sunil
   POSTGRES_PASSWORD=<pick something, or leave the compose default>
   POSTGRES_DB=sunil
   ```
6. Build `DATABASE_URL` and `REDIS_URL` from the values above, using the service names (not
   `localhost`) because the apps that read these run **inside** the Compose network:
   ```
   DATABASE_URL=postgresql://sunil:sunil_local_dev_only@postgres:5432/sunil?schema=public
   REDIS_URL=redis://redis:6379
   ```
   Everything else in `.env.example` ships with a sensible local default already
   (`SUNIL_SESSION_IDLE_HOURS=8`, `SUNIL_AUTH_MAX_FAILURES=5`, etc. — the Gate 1 auth
   thresholds) or is blank/optional (LLM provider keys — not needed; Phase 1's tests run
   entirely against mock transports, A-11).
7. `SUNIL_API_INTERNAL_URL` (ADR-011, server-side only — never sent to the browser) ships in
   `.env.example` with the **host-run dev** default, `http://localhost:3001`, which is what
   you want if you run `apps/web` directly on the host via `turbo dev` while pointing it at a
   Compose-published API port. You do not need to change it for the Compose case:
   `docker-compose.yml` sets it explicitly to `http://api:3001` on the `web` container's
   `environment:` block, and that explicit value always wins over whatever is in `.env` when
   the stack runs under Compose. There is no `NEXT_PUBLIC_API_URL` to set — it has been
   deliberately removed from the configuration inventory (amendment A1); the browser only ever
   fetches relative `/api/...` paths from `web` itself.

## 3. Bring up the infrastructure (works today)

### 3.1 Standard bring-up

```
docker compose up -d postgres redis
```

This starts **exactly** `postgres` and `redis` — it does not attempt to build `api`, `web`,
`worker` or `scheduler` (which don't have Dockerfiles yet), because Compose only builds/starts
the services you name (plus their dependencies), and neither `postgres` nor `redis` depends on
anything else.

Expected output includes both containers reaching `Started`. Verify with:

```
docker compose ps
```

Expected:

```
NAME               IMAGE                            STATUS                    PORTS
sunil-postgres-1   pgvector/pgvector:0.8.5-pg16...   Up ... (healthy)          5432/tcp
sunil-redis-1      redis:7.4-alpine                  Up ... (healthy)          6379/tcp
```

Both should reach `(healthy)` within about 15 seconds (healthcheck `start_period` is 10s for
Postgres, 5s for Redis, polled every 5s). If either stays `(health: starting)` far longer than
that or flips to `(unhealthy)`, see §7.

Note there is intentionally **no `PORTS` mapping to your host** in this default mode — Postgres
and Redis are reachable only from other containers on the Compose network
(`FR-090`/architecture §15.1). That's fine for the full six-service stack once it exists (`api`
and `worker` reach them by service name). If you need to reach them from host tools right now
(a GUI client, or running Prisma from the host once `packages/db` exists), use §3.2.

### 3.2 Dev-loop / host-tool access (optional)

```
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis
```

This additionally publishes Postgres to `localhost:${SUNIL_PORT_POSTGRES:-5432}` and Redis to
`localhost:${SUNIL_PORT_REDIS:-6379}`, for the "infra in Docker, apps on the host via `turbo
dev`" workflow described in architecture §15.3 pitfall 6, and for any GUI database/Redis tool
you want to point at the stack. It does not start `api`/`web`/`worker`/`scheduler` either, for
the same reason as §3.1.

### 3.3 Bring up the full stack (once the scaffold + Dockerfiles exist)

Once a later wave adds `apps/*` and their Dockerfiles, the acceptance configuration is the
**bare** command with no service names, which brings up all six services in dependency order
(`postgres`/`redis` healthy → `api` → `web`; `worker`/`scheduler` after `postgres`/`redis`):

```
docker compose up -d
```

Wait for all six to report `(healthy)`:

```
docker compose ps
```

The portal is reachable at `http://localhost:${SUNIL_PORT_WEB:-3000}` — **this is the only URL
you open in a browser.** `apps/web` proxies every `/api/...` request to the API internally
(ADR-011); nothing in the portal ever issues a client-side request to the API's own origin.

The API is separately reachable at `http://localhost:${SUNIL_PORT_API:-3001}` for **non-browser
use only** — QA exit-test suites, `curl`, Postman/Insomnia, dev tooling. It returns no CORS
headers and is not meant to be opened in a browser tab for anything beyond manual API
inspection (`GET /api/system-health` is fine to hit directly; don't expect a page).

## 4. Verify each service is healthy

### 4.1 Postgres — pgvector extension check

There is no host `psql`, so verification goes through the container:

```
docker compose exec postgres psql -U sunil -d sunil -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker compose exec postgres psql -U sunil -d sunil -c "\dx vector"
```

(Substitute your own `POSTGRES_USER`/`POSTGRES_DB` if you changed them from the defaults.)
Expect `CREATE EXTENSION` followed by a one-row table showing `vector | 0.8.5 | public | ...`.
If `CREATE EXTENSION` fails, see §7.

### 4.2 Redis — persistence settings (ADR-002)

Confirm AOF and the eviction policy are actually in effect, not just configured in the compose
file:

```
docker compose exec redis redis-cli CONFIG GET appendonly
docker compose exec redis redis-cli CONFIG GET appendfsync
docker compose exec redis redis-cli CONFIG GET maxmemory-policy
```

Expect `yes`, `everysec`, `noeviction` respectively. These three settings are load-bearing for
the queue-durability guarantee (ADR-002, exit test ET-4) — **do not** change
`maxmemory-policy` away from `noeviction` to relieve memory pressure; any eviction policy can
silently delete BullMQ queue state.

### 4.3 API health endpoint (once buildable)

This is exactly the kind of direct, non-browser access to the API's published port that
ADR-011 keeps it around for:

```
curl http://localhost:${SUNIL_PORT_API:-3001}/api/system-health
```

Expect `{"status": "...", "deps": {"postgres": "up", "redis": "up"}}` — no secrets, connection
strings or version numbers in the body (FR-091). To check the same thing through the portal's
same-origin proxy instead (once `web` is buildable too): `curl
http://localhost:${SUNIL_PORT_WEB:-3000}/api/system-health` should return the identical body.

## 5. Migrations and bootstrap (once `packages/db` exists)

The API container runs `prisma migrate deploy` as its entry step before it starts listening
(idempotent — safe to run on every start, NFR-009), so a normal `docker compose up` brings the
schema up to date automatically. To run it by hand, or before the API container exists:

```
docker compose run --rm api pnpm --filter @sunil/db exec prisma migrate deploy
```

Bootstrap seeds the four roles, the 21 permissions, role-permission grants, the three
`LlmProvider` rows (disabled), seed settings, and the sole owner account from
`SUNIL_OWNER_EMAIL` / `SUNIL_OWNER_INITIAL_PASSWORD` (§5.8 of the architecture — idempotent,
re-running detects an existing owner and changes nothing):

```
docker compose run --rm api pnpm --filter @sunil/db run db:bootstrap
```

## 6. First login and MFA enrolment (once the portal exists)

1. Open `http://localhost:${SUNIL_PORT_WEB:-3000}`.
2. Log in with `SUNIL_OWNER_EMAIL` / `SUNIL_OWNER_INITIAL_PASSWORD` from your `.env`.
3. Change the password from the portal, then you may delete
   `SUNIL_OWNER_INITIAL_PASSWORD` from your local `.env`.
4. Optionally enrol TOTP MFA (self-service, not mandatory to use — assumption A-06): scan the
   QR / enter the secret shown **once** into an authenticator app, confirm with a current code.
   Save the 10 recovery codes shown at that point; they are not retrievable again.

## 7. Running the automated tests (once the scaffold exists)

```
pnpm test
```

runs the Vitest suite across every workspace (root command per FR-003) with zero API keys
required — all three LLM providers are exercised through mock transports (A-11). A JSON summary
per workspace is emitted for machine consumption.

## 8. Troubleshooting

**Docker daemon not running.**
`docker compose up` fails immediately with something like `error during connect ... the system
cannot find the file specified` or `pipe/dockerDesktopLinuxEngine`. Start Docker Desktop and
wait for it to report "Engine running" before retrying. Confirm with `docker info`.

**Port already in use (`Bind for 0.0.0.0:5432 failed: port is already allocated`, or similar
for 3000/3001/6379).**
Something else on the host (a native Postgres/Redis install, another project's Compose stack)
already holds that port. Every published port in this stack is env-configurable — set a
different value in `.env` (`SUNIL_PORT_WEB`, `SUNIL_PORT_API`, `SUNIL_PORT_POSTGRES`,
`SUNIL_PORT_REDIS`) and re-run. You do not need to stop the other program if you'd rather just
move SUNIL's port.

**`CREATE EXTENSION vector` fails ("could not open extension control file" or similar).**
This should not happen with the pinned image (`pgvector/pgvector:0.8.5-pg16`, digest
`sha256:1d533553fefe4f12e5d80c7b80622ba0c382abb5758856f52983d8789179f0fb` — the extension ships
inside that image). If you see this, you are very likely running against a **different**
Postgres image or an existing `pgdata` volume created by a different image than the one this
compose file pins. Check `docker compose images postgres` shows the pinned digest above; if a
plain `postgres` (non-pgvector) image was ever used against the same named volume, the fix is
the reset procedure in §9 (extension files live in the image, not the data volume, so this
usually means the running container isn't the image you think it is — restart it: `docker
compose up -d --force-recreate postgres`).

**CRLF line endings breaking a script run inside a Linux container.**
Windows checkouts can produce CRLF line endings; a shell script starting `#!/bin/sh\r` fails
inside the container with `bad interpreter` or silently misbehaves. This repository's
`.gitattributes` forces LF for `*.sh`, `Dockerfile*`, `*.yml`/`*.yaml` and `prisma/**` — if you
hit this anyway (e.g. a new script type not covered), check `git config core.autocrlf` is not
`true` for this repo (`git config core.autocrlf input` or `false` is safer on Windows for a
repo with `.gitattributes` already doing the job), and re-checkout the affected file
(`git rm --cached <file> && git checkout <file>`) so the attribute takes effect. This is R-03
in the risk register — it is a live risk specifically because Windows is the dev host and every
container is Linux.

**`better-sqlite3`-style native-module build failures on Windows (node-gyp errors, missing
Visual Studio Build Tools/Python during `pnpm install`).**
Phase 1 deliberately avoids any dependency that compiles with `node-gyp` at install time (§4 of
the architecture) — most notably `@node-rs/argon2` is used instead of the classic `argon2`
package specifically because it ships prebuilt N-API binaries for `win32-x64` and
`linux-x64-musl`, needing no build toolchain on Windows at all. If you see a node-gyp-style
failure during install, it means either (a) a dependency was added that violates this rule —
that's a defect, flag it, don't work around it locally — or (b) `pnpm`'s
`onlyBuiltDependencies` allowlist is missing an entry for a legitimate prebuilt-binary package
that still runs a (harmless) install script; check the root `package.json`
`pnpm.onlyBuiltDependencies` list. Do not add `node-gyp`/Python/Visual Studio Build Tools to
"fix" this — that is exactly the toolchain dependency the architecture avoids.

**Windows path length.**
Keep the repository at a short path (`C:\repo\SUNIL` is fine, per architecture §15.3 pitfall 5).
Deeply nested `node_modules` paths can approach the 260-character Windows limit; if you see
`ENAMETOOLONG` or similar during install, move the checkout closer to a drive root.

**Bind-mount permission errors.**
This stack deliberately uses **named volumes**, never bind mounts, for all data and
`node_modules` (architecture §15.3 pitfall 1 — bind-mounted `node_modules` on Windows is both
slow and symlink-hostile with pnpm). If you see permission-denied errors referencing a bind
mount, check you haven't added one locally; named volumes (`pgdata`, `redisdata`) don't exhibit
this class of problem.

**A service stays `unhealthy` after the `start_period`.**
Check its logs: `docker compose logs postgres` / `docker compose logs redis`. For Postgres, a
common cause is `POSTGRES_PASSWORD` being empty with no `POSTGRES_HOST_AUTH_METHOD` set — the
compose file's fallback defaults avoid this, but if you set a blank value in `.env` you can
reintroduce it; either fill it in or remove the line so the fallback default applies.

## 9. Rollback and reset

**Stop the stack, keep all data** (owner account, audit records, job history, AOF-persisted
queue state — everything on the named volumes):

```
docker compose down
```

Bringing it back up (`docker compose up -d postgres redis`, or the full stack once buildable)
restores exactly where you left off — this is exactly what exit test ET-4 4.9 requires
(restarting the *whole* stack, volumes retained, and confirming the owner account, audit
records and execution history all survive).

**Stop one misbehaving service and recreate it without touching data:**

```
docker compose up -d --force-recreate postgres
```

**Full reset — destroy all local data and start clean** (only do this deliberately; it is
irreversible and takes down the owner account, every audit record, every stored secret and all
job history):

```
docker compose down -v
```

The `-v` flag removes the named volumes (`pgdata`, `redisdata`, and `ollamadata` if you used
the `ollama` profile) along with the containers. A subsequent `docker compose up -d postgres
redis` starts from a completely empty Postgres and Redis, as if this were a fresh checkout.

**Removing just the pinned images** (rarely needed — e.g. to force a re-pull and re-verify the
digest):

```
docker compose down
docker image rm pgvector/pgvector:0.8.5-pg16 redis:7.4-alpine
docker compose up -d postgres redis
```

## 10. Image provenance (R-02)

`pgvector/pgvector:pg16` is a floating tag — it moves as new pgvector patch releases ship for
Postgres 16. Risk R-02 requires resolving it to an explicit, immutable pin. This was done by:

1. Inspecting the already-pulled `pgvector/pgvector:pg16` image on the build host:
   ```
   docker image inspect pgvector/pgvector:pg16 --format '{{json .RepoDigests}}'
   ```
   → `pgvector/pgvector@sha256:1d533553fefe4f12e5d80c7b80622ba0c382abb5758856f52983d8789179f0fb`
2. Cross-checking that digest against Docker Hub's tag list for the repository
   (`https://hub.docker.com/v2/repositories/pgvector/pgvector/tags`) to find which explicit
   version tag it corresponds to. It matched `0.8.5-pg16` (and `0.8.5-pg16-bookworm`,
   `pg16-bookworm` — all aliases of the same image).
3. Pulling `pgvector/pgvector:0.8.5-pg16` directly and confirming its image ID and digest are
   byte-identical to the originally-pulled `pgvector/pgvector:pg16` — i.e. this pin captures
   exactly the image already in use, not a different build.

**Resulting pin**, as recorded in `docker-compose.yml`:

```
pgvector/pgvector:0.8.5-pg16@sha256:1d533553fefe4f12e5d80c7b80622ba0c382abb5758856f52983d8789179f0fb
```

Both the tag and the digest are embedded in the image reference, so `docker compose pull` can
never silently resolve to a different image even if the `pgvector/pgvector:pg16` or
`pgvector/pgvector:0.8.5-pg16` tags are later repointed upstream. To intentionally move to a
newer pgvector/Postgres-16 build, change this pin explicitly (repeat the three steps above
against the new tag) — never let it float.

`redis:7.4-alpine` is pinned to an explicit version tag already (not a floating major); its
resolved digest at the time of writing is
`sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99`, recorded as a comment
in `docker-compose.yml` for the same provenance reasons, though R-02 itself is specifically a
Postgres/pgvector risk.

## 11. Phase 1 limitations (state these honestly — do not imply more than is built)

- **LLM provider adapters are unverified against live endpoints** (FR-065). Every automated
  test runs against mocked transports; setting a real `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` in
  `.env` lets you manually exercise the real adapter, but no Phase 1 code path or test does
  this automatically, and the portal will always show providers as "not configured /
  unverified against live endpoints," never "connected/healthy."
- **No WebSocket gateway, no chat, no workflow engine, no outbound integrations (email, Jira,
  Teams) exist in Phase 1.** The agent runtime executes no real LLM work — only mocked/
  simulated steps (assumption A-07).
- **Single-node only.** One Postgres, one Redis, one worker replica (assumption A-14). This is
  a local development topology, not a production or staging deployment — there is no TLS
  termination, no public hostname, and `SUNIL_COOKIE_SECURE` defaults to `false` for that
  reason (assumption A-01). None of that is appropriate beyond a developer's own machine.
- **`api`, `worker`, `scheduler`, `web` have no Dockerfile yet** as of this document's writing
  — see §0. `docker compose up` (bare, no service names) will fail until a later wave adds
  them; `docker compose up -d postgres redis` works today and is the correct command until
  then.
- **No CORS in Phase 1, by design, not by omission** (ADR-011, amendment A1). The browser only
  ever talks to `web`; there is no allowed-origins configuration variable anywhere and adding
  one is explicitly forbidden as a drive-by change — a genuinely cross-origin client (a mobile
  app, a third-party consumer) requires a new architecture decision, not an env var. If you are
  building against this stack and find yourself wanting to fetch the API's origin directly from
  browser JavaScript, that is a sign you're solving the wrong problem — use the relative
  `/api/...` path through `web` instead.
