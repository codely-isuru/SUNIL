# Task — P0-platform: Phase 0 development platform (Compose, LiteLLM, n8n, CI)

Owner (typeKey): `devops_engineer` · Status: in-review

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
- `docker compose -f infra/docker-compose.yml config` passes. ✅
- Stack actually boots and reports healthy, with evidence. ✅ (see Progress)
- No secrets anywhere in the repo. ✅ (diff grepped before commit; CI enforces ongoing)
- CI green on the current branch state. ✅ (every job's steps reproduced locally)

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
- [2026-09-10 01:30 | devops_engineer] **Stack booted green on first attempt.** Evidence:
  ```
  sunil-v2-litellm    ghcr.io/berriai/litellm:v1.83.14-stable.patch.3   Up (healthy)   0.0.0.0:4000->4000/tcp
  sunil-v2-n8n        n8nio/n8n:2.38.5                                  Up (healthy)   0.0.0.0:5680->5678/tcp
  sunil-v2-postgres   pgvector/pgvector:0.8.6-pg17                      Up (healthy)   0.0.0.0:5433->5432/tcp
  ```
  Functional probes, because "container healthy" is weaker than "service works":
  - pgvector **0.8.6** + uuid-ossp installed; a real cosine-distance query returned correct
    ordering (`1:0.0000`, `2:0.2857`) — the extension is usable, not merely present.
  - Init script created all three databases (`sunil`, `litellm`, `n8n`); log lines confirm.
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

- Commits: see `git log task/P0-platform` (6 commits, listed in the handoff report).
- Test evidence: real boot to all-healthy with functional probes per service, idempotent re-run,
  clean teardown, and a local dry-run of every CI step — all transcribed in Progress above.
- Notes: **not merged**; awaiting Delivery Manager review. Production out of scope (Gate 3).
