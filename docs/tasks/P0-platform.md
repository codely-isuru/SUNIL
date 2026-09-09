# Task — P0-platform: Phase 0 development platform (Compose, LiteLLM, n8n, CI)

Owner (typeKey): `devops_engineer` · Status: in-review (fix round complete, re-review requested)

> ## CORRECTION NOTICE — 2026-09-10, fix round
>
> **Two evidence claims in the original Progress log below were false, and one was
> pasted without being read. They are struck through in place rather than rewritten,
> so the record of what was claimed survives.**
>
> 1. ~~"Stack booted green on first attempt"~~ — the boot happened, but **not on a
>    first boot**: the `pgdata` volume already existed, so
>    `/docker-entrypoint-initdb.d` never executed on that run. QA established that a
>    genuine first boot **would have failed** (`exit 255`) because this worktree's
>    copy of the init script was CRLF on disk. "Created all three databases" was read
>    off a volume initialised by an earlier attempt, not off the run being reported.
> 2. ~~The `docker compose ps` block showing `0.0.0.0:4000`, `0.0.0.0:5680`,
>    `0.0.0.0:5433`~~ — pasted into the acceptance evidence **as proof of success**.
>    Those three strings are the exact configuration ADR-032 rejects by name. I
>    captured the evidence and did not read it against the ADR I had cited three
>    paragraphs earlier. Both reviewers found it in the paste itself.
> 3. The acceptance tick ~~"No secrets anywhere in the repo ✅ (CI enforces ongoing)"~~
>    overstated the CI guard: the scan's placeholder filter matched on whole lines
>    including the path, so anything in `.env.example` was silently dropped.
>
> Corrected, re-verified evidence is in **Progress → fix round** below. Nothing in the
> original log is deleted.

**File ownership** (paths only this task may touch, for parallel lanes):
- `infra/**` (compose file, LiteLLM config, Postgres init)
- `scripts/dev-up.*`, `scripts/dev-down.*`
- `.github/workflows/ci.yml`
- `.env.example`, `.yamllint.yml`
- `docs/tasks/P0-platform.md`
- `docs/ENVIRONMENT.md` — **shared file, appended section only** ("V2 platform"); no
  existing section was edited, so a concurrent lane editing §1–§8 will not conflict.

## Static spec (from the Stage-4 issue)

**Background.** `docs/V2_DEVELOPMENT_PLAN.md` Phase 0 blocks all six parallel streams. Its
platform half requires the Compose stack to gain Postgres+pgvector, LiteLLM and n8n, with
`.env.example` updated. Per ADR-030 Amendment 1 the `V2` branch is a clean-slate rebuild:
**no application code exists**, so the platform must boot green with zero app containers.

**Objective.** A reproducible local platform any stream can boot in one command, plus CI that
is green today and starts enforcing automatically as code lands.

**Functional requirements.**
1. `infra/docker-compose.yml` — Postgres 17 + pgvector, LiteLLM (pinned), n8n (pinned); named
   volumes, healthchecks on all three, restart policies, one shared network; no app container,
   commented stub showing where it plugs in.
2. `infra/litellm/config.yaml` — model_list for Anthropic + OpenAI read from env, commented
   OmniRoute dev-lane entry marked PUBLIC-workloads-only per ADR-030 §8, master_key from env.
3. `.env.example` — every variable, dummy values, grouped and commented; avoid port 4317
   (Minions Portal) and route around an occupied 5678.
4. `scripts/dev-up.ps1` + `scripts/dev-up.sh` (boot, wait for health, print status) and
   `dev-down` twins for teardown.
5. `.github/workflows/ci.yml` — (a) compose config validation, (b) yaml/openapi lint of
   `docs/contracts/*.yaml` **if present**, (c) passing placeholder test job.
6. This task file; a "V2 platform" section in `docs/ENVIRONMENT.md`.

**Technical scope.** Local dev platform only. **Production is out of scope entirely** (Gate 3
is human-only) — nothing here deploys anywhere, and no production credential was accessed.

**Acceptance criteria.**
- ~~`docker compose -f infra/docker-compose.yml config` passes.~~ **Superseded**: secrets
  are now `${VAR:?...}`, so `config` with **no** env file must FAIL. The criterion is now
  `docker compose --env-file .env.example -f infra/docker-compose.yml config` passes, AND
  the same command without an env file fails. Both asserted in CI. ✅
- Stack actually boots and reports healthy, with evidence. ✅ — **re-done on empty volumes**,
  fix round, see Progress 2026-09-10 (the original claim was not a first boot).
- No secrets anywhere in the repo. ✅ (diff grepped before each commit; the CI scan's
  path-blindness is fixed and demonstrated with a planted key)
- CI green on the current branch state. ✅ (every job's steps extracted from the workflow
  YAML and executed verbatim locally — including the new gate against six broken fixtures)

**Test requirements.** Evidence, not assertion: real boot, real health output, functional probe
of each service (not just "container up"), teardown, and a local dry-run of each CI step.

**Affected systems.** Local Docker only. Pre-existing unrelated containers
(`strapi-next-starter-db-1` on :5432, `mysql` on :3306) were left untouched and verified still
running after teardown.

**Security considerations.**
- No real credential is committed. `.env` is gitignored (`.gitignore:26`); only `.env.example`
  with dummy values is tracked.
- Secrets are declared in Compose as `${VAR}` **without defaults** on purpose: unset resolves
  to empty so `config` still validates for CI, but a container started that way fails loudly
  rather than silently running a known-value secret.
- Provider keys are held **only** by the LiteLLM container (ADR-030 §2) — the application never
  receives an upstream key. Third-party credentials live only in n8n's vault (ADR-030 §5),
  which is why `N8N_ENCRYPTION_KEY` is treated as a real secret.
- `turn_off_message_logging: true` and `set_verbose: false` in the LiteLLM config: the gateway
  must not keep a second, unclassified copy of prompt bodies. SUNIL's audit spine is the source
  of truth and applies the capture policy (ADR-014/021).
- The repo is **public** (`docs/CI.md`), so CI references no `secrets.*` and sets
  workflow-level `permissions: contents: read`. Verified: 0 `${{ secrets.` interpolations.
- The OmniRoute dev lane is left **commented out**, so it is off unless a human enables it.
  Verified against the running proxy: `/v1/models` returned 5 models, none OmniRoute.

**Rollback.** `bash scripts/dev-down.sh` (add `--volumes` to discard data). Nothing outside
Docker is modified. Branch-level rollback is `git revert` of the commits below — no migration,
no deployed artefact, nothing stateful outside the two named volumes.

**Documentation needs.** `docs/ENVIRONMENT.md` "V2 platform" section (ports + how to boot) and
this file.

## Cross-lane consumers

- `infra/docker-compose.yml` (service names/ports) → consumed by **Stream B** (LiteLLM base-URL
  override via C2), **Stream C** (Postgres+pgvector for Mem0/entities), **Stream E** (n8n).
- `.env.example` variable names → consumed by **every** stream; adding a Compose variable
  without adding it here now **fails CI** (the "Validate compose file against .env.example"
  step), so drift surfaces at the PR, not on someone's machine days later.
- `docs/contracts/*.yaml` → **produced by** the architect/BA lane (C1–C5), **consumed by** this
  task's `contracts` CI job. That job currently skips cleanly (no files) and begins enforcing
  the moment the first contract lands, with no edit to the workflow.
- The commented `api` stub → consumed by whichever stream first containerises the rebuilt
  gateway; it documents the exact env keys expected (`LLM_BASE_URL`, `DATABASE_URL`).

## Progress

- [2026-09-10 01:20 | devops_engineer] Recon before writing anything. Docker daemon **is**
  running (engine 29.7.2, Compose v5.5.1), so a real boot was required rather than a
  config-only claim. Host-level listener scan (not just `docker ps` — per my own prior lesson)
  found three port conflicts that changed the design:
  - **5432 occupied** by an unrelated container `strapi-next-starter-db-1` → Postgres mapped to
    host **5433**.
  - **5678 AND 5679 both occupied** by a single host-native node process (PID 7148 — the local
    n8n source build at `C:\repo\n8n`). The brief anticipated 5678 being taken and suggested
    5679, but 5679 is taken by the same process, so n8n is mapped to host **5680**.
  - **4317** confirmed as the Minions Portal; never bound, and CI now asserts it.
- [2026-09-10 01:22 | devops_engineer] Pinned versions verified against the live registries
  rather than guessed: `pgvector/pgvector:0.8.6-pg17`; `n8nio/n8n:2.38.5` (chosen because the
  upstream `stable` tag resolves to that digest, `sha256:f98bb7c2…`, while 2.39.1 is the
  `latest` lane); `ghcr.io/berriai/litellm:v1.83.14-stable.patch.3` (highest `-stable` release,
  walked the full paginated GHCR tag list — 2577 tags — to confirm; the `v1.89.x` weeklies are
  the bleeding-edge lane and this is a seam six streams will point at).
- [2026-09-10 01:30 | devops_engineer] ~~**Stack booted green on first attempt.** Evidence:~~
  **STRUCK 2026-09-10 (fix round): not a first boot — `pgdata` pre-existed, so the init
  script never ran on this run; and the three `0.0.0.0` bindings below are the defect,
  pasted as if they were the proof. See the Correction Notice at the top.**
  ```
  sunil-v2-litellm    ghcr.io/berriai/litellm:v1.83.14-stable.patch.3   Up (healthy)   0.0.0.0:4000->4000/tcp
  sunil-v2-n8n        n8nio/n8n:2.38.5                                  Up (healthy)   0.0.0.0:5680->5678/tcp
  sunil-v2-postgres   pgvector/pgvector:0.8.6-pg17                      Up (healthy)   0.0.0.0:5433->5432/tcp
  ```
  Functional probes, because "container healthy" is weaker than "service works":
  - pgvector **0.8.6** + uuid-ossp installed; a real cosine-distance query returned correct
    ordering (`1:0.0000`, `2:0.2857`) — the extension is usable, not merely present.
  - ~~Init script created all three databases (`sunil`, `litellm`, `n8n`); log lines confirm.~~
    **STRUCK: those log lines came from an earlier run's volume, not from this one.**
  - LiteLLM `/health/readiness` → `{"status":"healthy","db":"connected",...,"litellm_version":"1.83.14"}`;
    **70 tables** migrated into the `litellm` database, so virtual keys/budgets (Stream B) have
    a working store.
  - n8n `/healthz` → `{"status":"ok"}`; **136 tables** in the `n8n` database, confirming it is
    genuinely Postgres-backed rather than falling back to SQLite.
  - LiteLLM loaded the mounted config: `/v1/models` returned `claude-sonnet`, `claude-opus`,
    `claude-haiku`, `gpt-flagship`, `gpt-mini`; **zero** OmniRoute entries. Config verified
    mounted read-only (`touch` → "Read-only file system").
- [2026-09-10 01:34 | devops_engineer] Re-ran `dev-up.sh` against the running stack to prove
  idempotency (re-converged, no churn), then `dev-down.sh` — containers and network removed,
  both named volumes retained as designed. The two unrelated pre-existing containers were
  unaffected.
- [2026-09-10 01:38 | devops_engineer] **Defect found and fixed in my own work** (see Issues
  #1): `scripts/dev-up.ps1` failed to parse on Windows PowerShell 5.1. Fixed, and CI now has a
  byte-level guard that catches the class on a Linux runner.
- [2026-09-10 01:42 | devops_engineer] Every CI step dry-run locally rather than assumed green:
  compose `config` both with and without `.env` (exit 0 both ways), unresolved-variable check,
  image-pin check, port-4317 check, credential-shape scan, `yamllint` (clean, zero output),
  `shellcheck --severity=warning` (clean), ASCII guard, PowerShell parse-check on **5.1**, and
  `bash -n` over all 18 workflow `run:` blocks (0 failures). Confirmed 0 `${{ secrets.`
  interpolations and `permissions: contents: read`. `.env` confirmed gitignored and absent from
  `git status`.
- [2026-09-10 01:45 | devops_engineer] Handing to Delivery Manager for review. **Not merged to
  V2 or main** — branch `task/P0-platform` pushed only. Production untouched and out of scope.

## Progress — fix round (2026-09-10, after the QA and Security reviews)

### Disposition of every review finding

| Finding | Source | Disposition |
|---|---|---|
| B8 / B2 — ports on 0.0.0.0 | QA + Security **blocker** | **FIXED** — `127.0.0.1:` on all four published ports (incl. the api stub); CI parses the resolved config and asserts `host_ip == 127.0.0.1` |
| B9 / B3 — one superuser for three DBs | QA + Security **blocker** | **FIXED** — `litellm_user` / `n8n_user`, own passwords, own database, `CONNECT` on `sunil` revoked; volumes re-created; negative probe run |
| CRLF worktree defect | QA **blocker** | **FIXED** — worktree renormalised; init script is LF; genuine first boot on empty volumes now succeeds |
| False first-boot / unread 0.0.0.0 evidence | QA | **CORRECTED** — struck in place, Correction Notice at the top of this file, fresh evidence below |
| D-1 — dev-up boots on committed dummies | Security + QA should | **FIXED** — hard-reject on `dummy\|change-me`; auto-copy generates CSPRNG values or refuses |
| D-2 — "empty fails loudly" false for n8n | Security should | **FIXED** — `${VAR:?set in .env}` on every secret; CI asserts `config` FAILS with no env file |
| D-3 — secret scan filter includes the path | Security + QA should | **FIXED** — path split from content, allowlist applies to content only; verified with a planted real-shaped key |
| §5 app inventory absent from `.env.example` | QA should | **FIXED** — all 18 vars added with dummy values, comments, and real host ports (5433/5680/3001) |
| Shared `.env` defeats "app never sees an upstream key" | QA + Security should | **FIXED** — `infra/.env.litellm` (gitignored) + committed template, `env_file:`-scoped to the litellm service |
| `drop_params: true` / `num_retries: 2` | QA + Security should/nit | **FIXED** per DM ruling — `false` / `0`, each with a comment citing the ruling |
| api stub env names invented | QA should | **FIXED** — stub uses the frozen §5 names |
| Port parity vs the ADR-032 table | Security B1 fix list | **FIXED (my half)** — CI hardcodes 5433/4000/5680 with ADR-032 named as source. The ADR/§5 amendment itself is the SA's lane; I touched no `docs/decisions` or `docs/contracts` file |
| Actions pinned by tag | Security nit | **FIXED** — SHA-pinned with the version in a trailing comment |
| 4317 check greps instead of parsing | QA nit | **FIXED** — folded into the YAML-parsing port gate |
| Compose location / profiles / pgvector tag float / approval webhook host | QA MISMATCH (should) | **See Issues #6 below** — accepted or deferred with reasoning; the pgvector tag is already pinned to `0.8.6-pg17`, the float is in `ARCHITECTURE_V2:143` (SA's file) |
| LiteLLM empty-master-key behaviour on the pinned tag | Security re-check list #7 | **MOOT** — the key can no longer be empty (`${LITELLM_MASTER_KEY:?...}` + dev-up rejection). Not separately probed; recorded as still-unknown upstream behaviour rather than claimed |

### Fresh first-boot evidence — genuinely empty volumes

**Pre-conditions established, not assumed.** Named the volumes first
(`sunil-v2_pgdata`, `sunil-v2_n8n_data`) so the teardown could not reach anything else:
the host also carries `sunil_pgdata` / `sunil_redisdata` from the V1 stack, plus volumes
for six unrelated projects.

```
$ docker compose --env-file .env.example -f infra/docker-compose.yml down -v --remove-orphans
 Volume sunil-v2_n8n_data Removed
 Volume sunil-v2_pgdata Removed

$ docker volume ls --filter name=sunil          # after
sunil_pgdata          <- V1, untouched
sunil_redisdata       <- V1, untouched
                      # no sunil-v2_* : volumes are EMPTY
$ docker ps
strapi-next-starter-db-1   Up 2 days      <- unrelated, untouched
mysql                      Up 2 days      <- unrelated, untouched
```

**1. dev-up refuses to boot on the committed template** (run before the real boot, with
`.env` replaced by `.env.example` verbatim):

```
    POSTGRES_PASSWORD in .env is still a TEMPLATE value.
    That value is committed to a PUBLIC repository - it is not a secret.
    ... (LITELLM_MASTER_KEY, N8N_ENCRYPTION_KEY, LITELLM_DB_PASSWORD, N8N_DB_PASSWORD)
    SESSION_SECRET in .env is still a template value (nothing reads it yet).   <- warn only
    5 secret(s) rejected. Refusing to boot.
EXIT=1                                          # nothing started
```

**2. True first boot** — no `.env`, no `infra/.env.litellm`, no volumes:

```
    No .env found - creating it from .env.example.
    Generated 8 random secret(s) into .env.
    No infra/.env.litellm found - creating it from the template.
    Generated LITELLM_SALT_KEY into infra/.env.litellm.
    Required secrets present and not template values.
 Volume sunil-v2_pgdata Created / Volume sunil-v2_n8n_data Created / Network sunil-v2_net Created
    litellm=starting  n8n=starting  postgres=healthy
    litellm=healthy   n8n=healthy   postgres=healthy
    All services healthy.

NAME                STATUS                    PORTS
sunil-v2-litellm    Up 33 seconds (healthy)   127.0.0.1:4000->4000/tcp
sunil-v2-n8n        Up 33 seconds (healthy)   127.0.0.1:5680->5678/tcp
sunil-v2-postgres   Up 39 seconds (healthy)   127.0.0.1:5433->5432/tcp

real  0m44s
```

**3. The init script actually executed this time** (LF on disk; it did not before):

```
/usr/local/bin/docker-entrypoint.sh: running /docker-entrypoint-initdb.d/01-init-databases.sh
[sunil-init] main db=sunil (owner sunil)
[sunil-init] side dbs: litellm (owner litellm_user), n8n (owner n8n_user)
[sunil-init] created role litellm_user
[sunil-init] created role n8n_user
[sunil-init] created database litellm owned by litellm_user
[sunil-init] created database n8n owned by n8n_user
[sunil-init] privileges fenced: litellm_user/n8n_user cannot connect to sunil
pgvector 0.8.6
db litellm owner=litellm_user litellm_can_connect=true  n8n_can_connect=false
db n8n     owner=n8n_user     litellm_can_connect=false n8n_can_connect=true
db sunil   owner=sunil        litellm_can_connect=false n8n_can_connect=false
[sunil-init] done
```

**4. `docker port` — the authoritative binding, read against ADR-032 this time:**

```
sunil-v2-postgres    5432/tcp -> 127.0.0.1:5433
sunil-v2-litellm     4000/tcp -> 127.0.0.1:4000
sunil-v2-n8n         5678/tcp -> 127.0.0.1:5680
```

Loopback = 127.0.0.1 only. No `0.0.0.0`, no `[::]`, on any of the three.

**5. Loopback probes — the services work, not just "container healthy":**

```
litellm  /health/liveliness : 200
litellm  /health/readiness  : {"status":"healthy","db":"connected","litellm_version":"1.83.14",...}
n8n      /healthz           : 200  {"status":"ok"}
postgres 127.0.0.1:5433     : accepting connections
litellm  /v1/models         : claude-sonnet, claude-opus, claude-haiku, gpt-flagship, gpt-mini
                              omniroute entries: 0
```

**6. Off-loopback probes — CONNECTION REFUSED, nine for nine.** Every IPv4 address this
host owns, including the exact `172.21.240.1` from which the reviewers got HTTP 200:

```
172.21.240.1    n8n 5680 / litellm 4000 / postgres 5433  -> CONNECTION REFUSED (curl exit 7)
172.30.112.1    n8n 5680 / litellm 4000 / postgres 5433  -> CONNECTION REFUSED (curl exit 7)
192.168.0.243   n8n 5680 / litellm 4000 / postgres 5433  -> CONNECTION REFUSED (curl exit 7)
```

**7. Three databases, three roles, and the negative privilege probe actually run:**

```
$ psql -c "\l"
 litellm   | litellm_user | ... | =T/litellm_user  litellm_user=CTc/litellm_user
 n8n       | n8n_user     | ... | =T/n8n_user      n8n_user=CTc/n8n_user
 sunil     | sunil        | ... | =T/sunil         sunil=CTc/sunil

$ psql -c "\du"
 litellm_user | No inheritance
 n8n_user     | No inheritance
 sunil        | Superuser, Create role, Create DB, Replication, Bypass RLS

NEGATIVE PROBE  litellm_user -> sunil:
  FATAL:  permission denied for database "sunil"
  DETAIL:  User does not have CONNECT privilege.        psql exit=2
NEGATIVE PROBE  n8n_user -> sunil:
  FATAL:  permission denied for database "sunil"        psql exit=2

POSITIVE CONTROL litellm_user -> litellm : connected as litellm_user to litellm; tables=70
POSITIVE CONTROL n8n_user     -> n8n     : connected as n8n_user to n8n; tables=136
```

The positive controls matter as much as the negatives: LiteLLM pushed its 70-table Prisma
schema and n8n ran its 136-table migration **as the restricted roles**, so least privilege
is sufficient for both services, not merely enforced.

**8. Provider-key scoping (values withheld, presence only):**

```
shared root .env   ANTHROPIC/OPENAI lines : 0     <- the app-side env never holds one
infra/.env.litellm ANTHROPIC/OPENAI lines : 2
shared root .env   LITELLM_SALT_KEY lines : 0
litellm  container ANTHROPIC_API_KEY      : sk-ant-... (present)
litellm  container LITELLM_SALT_KEY       : sk-...     (present)
n8n      container ANTHROPIC_API_KEY      : ABSENT
postgres container ANTHROPIC_API_KEY      : ABSENT
n8n      container DB_POSTGRESDB_USER     : n8n_user
```

**9. Idempotent re-run, then teardown. Stack left DOWN, volumes retained.**

```
$ bash scripts/dev-up.sh       # re-run against the running stack: re-converged, no churn
$ bash scripts/dev-down.sh     # containers + network removed
sunil-v2 containers : none
volumes retained    : sunil-v2_pgdata, sunil-v2_n8n_data
unrelated containers: strapi-next-starter-db-1 Up 2 days, mysql Up 2 days
```

### CI re-verification (local dry-run of the shipped text, not a paraphrase)

Each step's `run:` block was extracted from `.github/workflows/ci.yml` by parsing the
workflow YAML and executed verbatim under bash, so what ran is what will run on the
runner. Results: secrets-mandatory ✅ (config with no env file exits non-zero as required) ·
compose-vs-`.env.example` ✅ · unresolved-variable check ✅ · image-pin check ✅ ·
**port gate ✅** · secret scan ✅ · `yamllint` **zero findings** (two >130-column lines
introduced by the fix were shortened rather than left as warnings) · `shellcheck
--severity=warning` clean · ASCII/LF guard clean on all five scripts · PowerShell **5.1**
parse-check clean on `dev-up.ps1`.

**The port gate was tested against deliberately-broken fixtures, then the fixtures were
deleted** — a guard that has never failed is a guard whose failure path is untested:

| Fixture | Result |
|---|---|
| n8n `host_ip: 0.0.0.0` (the shipped defect) | exit 1, names the service and port |
| `host_ip` key absent (short-form `5680:5678`) | exit 1 |
| postgres drifts to 5432 (pre-amendment ADR value) | exit 1, "Amend the ADR or the compose file" |
| litellm on 4317 (Minions Portal) | exit 1, two distinct errors |
| no published ports at all | exit 1, "would have passed vacuously. Refusing." |
| empty / unparseable file | exit 1 |

Same treatment for the secret scan: planting `sk-ant-api03-…` in `.env.example` — the case
QA demonstrated was invisible — now exits 1 and reports a 12-character prefix only.

## Issues

- `scripts/dev-up.ps1:118` — **blocker (self-found, FIXED)** — the script did not parse under
  Windows PowerShell 5.1: *"Unexpected token 'the' in expression or statement"*. Root cause was
  not the logic but the file encoding: the file is BOM-less UTF-8, and PowerShell 5.1 decodes
  BOM-less files as **cp1252**, so an em dash (U+2014 = `E2 80 94`) decoded as three characters
  the last of which is `0x94` = `”`, a **right double quotation mark that PowerShell treats as a
  string delimiter**. One em dash inside a string silently terminated it and broke the parse.
  Fix: all executable scripts (`*.ps1`, `*.sh`) are now ASCII-only, LF-terminated, and CI asserts
  it byte-by-byte. Re-verified: both `.ps1` files parse clean on 5.1.26100.9278.
- `scripts/dev-up.ps1:95` — **should (FIXED)** — first draft used `??`, which does not exist in
  Windows PowerShell 5.1. Replaced with an explicit `Get-EnvVal` helper. Caught by the same
  5.1 parse check.
- `.github/workflows/ci.yml` — **should (FIXED)** — the ASCII guard was first written as
  `if grep -qP …`. `grep`'s PCRE support is optional and locale-dependent, and when it bails it
  returns **2**, which that guard reads as "no match" — i.e. it would **fail open**. Confirmed
  locally: this Git Bash `grep -P` errors with *"-P supports only unibyte and UTF-8 locales"*
  while the guard still reported success. Rewritten in Python so it cannot fail open.
- `.github/workflows/ci.yml` — **nit (accepted)** — the `pwsh` parse-check runs PowerShell **7**
  on the Linux runner, so it cannot catch constructs that parse in 7 but not in 5.1 (`??`, `?:`).
  The ASCII guard covers the encoding class cross-platform; the operator class is covered by
  review. Accepted rather than adding a Windows runner to CI for two small scripts — revisit if
  the PowerShell surface grows.
- **Fix round, accepted / deferred with reasoning (issue #6).**
  - `infra/.env.litellm` is attached with `required: false`, which is a deliberate
    **fail-open on file PRESENCE** — CI cannot have a gitignored file, so a hard requirement
    would break linting. Safe because a missing file means *no provider key*, so every
    completion call fails with an explicit upstream 401; it can never mean "use a weaker
    credential". `dev-up` creates the file and refuses to boot on dummy values, so the
    only way to hit the fail-open path is to bypass `dev-up` **and** delete the file.
  - **Compose file location** (`infra/` vs the ADR's "repo root") and **compose profiles**
    (`infra` + `full` specified, none implemented, so `--profile full` silently no-ops):
    both are real doc/infra mismatches, both are one-line doc fixes in a file that is not
    mine this round (`ADR-032` / `ARCHITECTURE_V2` belong to the SA's parallel lane).
    Flagged to the SA via the DM rather than edited. Profiles: I would rather delete them
    from the doc than implement two profiles over three services that are all always
    needed — a profile that no one passes is a footgun, not a feature.
  - **pgvector tag float** — the compose file already pins `0.8.6-pg17` (both versions).
    The floating reference is in `ARCHITECTURE_V2:143`, the SA's file.
  - **Approval-webhook host base** — `SUNIL_APPROVAL_NOTIFY_WEBHOOK_URL` ships EMPTY rather
    than guessing a host. Empty means no notification is sent and the approval still parks
    correctly, which is the safe default; the URL is a capability and should be set
    deliberately. Stream D/E owns the value.
  - **`LITELLM_VIRTUAL_KEY_DEFAULT` is not generated** by `dev-up` (it warns instead). It
    must be minted by LiteLLM via `POST /key/generate`, so a random local string would
    only produce a 401 at first use. Whoever wires Stream B mints it.
  - **`DATABASE_URL` is not rewritten** when `dev-up` generates `POSTGRES_PASSWORD`. It is
    a composite value and the app that consumes it does not exist yet; `dev-up` prints a
    warning naming the file and the field. Worth automating once Stream B needs it.
  - **CRLF renormalisation side-effect, outside my lane, needs an owner.** The renormalise
    (`git rm --cached -r . && git reset --hard`) fixed my scripts, and also revealed that
    two committed blobs carry CRLF against the `*.md text eol=lf` rule:
    `docs/STATUS.md` and `docs/worklog/2026-09-10-v2-clean-slate-and-engagement-start.md`.
    They now show as modified with a **pure line-ending diff** (`git diff
    --ignore-cr-at-eol --stat` is empty — zero content change). I did **not** commit them:
    they belong to the DM/documentation lane, and silently rewriting 291 lines of another
    lane's file mid-review is worse than leaving a flagged one-line fix. Whoever owns
    `docs/STATUS.md` should `git add` them in their own commit.
- `docs/ENVIRONMENT.md §7` — **nit (accepted, not edited)** — that section states 5432 is free.
  It is now occupied. I did **not** rewrite §7 (it is an explicitly dated historical survey, and
  it is a shared file other lanes may be editing); the new "V2 platform" section carries the
  current facts and points back at it.

## Questions

1. **n8n on host 5680, not 5679.** The brief specified 5679 as the fallback, but the local
   host-native n8n build holds both 5678 and 5679 from one process. Proceeding on the assumption
   that "a free port, documented" was the intent. If 5679 must be freed instead, that is a
   human action on `C:\repo\n8n` — I did not touch that process.
2. **LiteLLM release lane.** I chose `v1.83.14-stable.patch.3` (the vetted `-stable` lane) over
   the newer `v1.89.7`. That is ~6 minor versions behind head. If a Stream B feature needs a
   post-1.83 capability, this pin is the thing to revisit — it is one line.
3. **n8n licence.** Sustainable Use Licence: internal use only, no resale as a hosted service
   (ADR-030 Consequences). Fine for a dev platform, but it is a **commercial** constraint on any
   future SUNIL offering that embeds n8n. Flagging for the owner, not for me to decide.
4. **Model IDs in `config.yaml` are placeholders** (`claude-sonnet-4-5`, `gpt-5`, etc.) and were
   not called against a live provider — the stack has no real keys, by design. Stream B should
   confirm the exact upstream model strings when it wires real credentials from the secrets
   manager.
5. **No Redis.** `ROADMAP.md` §4 lists Redis in the target stack, but nothing in Phase 0 or the
   six streams currently requires it (n8n runs in single-main mode; no queue mode, no separate
   cache consumer). Left out deliberately rather than shipping an unused container. It is ~10
   lines to add when a consumer appears.

## Outcome

- Commits: see `git log task/P0-platform` — 6 from the original build, plus 7 from the fix
  round (env templates · three DB roles · loopback + mandatory secrets · LiteLLM ruling ·
  dev-up secret rejection · CI port gate and secret scan · docs).
- Test evidence: **fix round supersedes the original** — genuine first boot on empty volumes,
  init script executed, all three services healthy, `docker port` showing loopback only,
  loopback probes 200, nine off-loopback probes refused, three databases / three roles with
  the negative CONNECT probe run and positive controls passing, idempotent re-run, clean
  teardown with volumes retained, unrelated containers verified untouched, and every CI step
  executed locally from the shipped workflow text including six deliberately-broken fixtures.
- Stack left **DOWN**; both named volumes retained; `.env` and `infra/.env.litellm` exist
  locally with generated values and are gitignored (verified with `git check-ignore`).
- Notes: **not merged**; branch `task/P0-platform` pushed only, re-review requested.
  Production untouched and out of scope entirely (Gate 3 is human-only).
