# S3 — THE LIVE PROOF (W2R3 Lane 1)

Owner: backend_engineer (Team 21). Branch: `task/S3-live-proof`.
Worktree: `C:/repo/SUNIL-wt/live`. Stack commands run from the MAIN checkout
`C:/repo/SUNIL` (that is where the real-secret `.env` and `infra/.env.litellm`
live); **no file in the main checkout is edited by this lane.**

This file is written leg-by-leg and committed+pushed after each one. Two earlier
sessions of this lane died leaving nothing on origin; the rule for this attempt
is that a dead session costs one leg, not the run.

**Secret discipline (applies to every line below).** No key, token or secret
value appears in this file, in any command output quoted here, or in any commit.
Evidence is limited to: model aliases, token counts, HTTP status codes, stage
names, latencies, and quoted *model response text*.

---

## Leg 0 — Environment preflight (BLOCKER FOUND)

Not one of the six commissioned legs. It is recorded because it is the thing
that has to be true before legs 1, 2, 3 and 5 can run at all, and because it is
almost certainly what killed the two previous sessions.

### 0.1 `scripts/dev-up` does NOT clobber the real-secret `.env` — verified by reading it

The instruction was to verify this before running anything. Verified statically,
not by experiment (an experiment that is wrong destroys the keys):

* `scripts/dev-up.ps1:147` — the entire `.env`-creation block is guarded by
  `if (-not (Test-Path $EnvFile))`. An existing `.env` is never written,
  never copied over, never rewritten; `Set-EnvValue` is only reachable from
  inside that guard.
* `scripts/dev-up.ps1:180` — same guard shape for `infra/.env.litellm`
  (`if (-not (Test-Path $LitellmEnvFile))`).
* Everything after those blocks is read-only (`Get-EnvFileValue`,
  `Test-Secret`), and the only failure mode is `exit 1` before boot.

**Verdict: safe to run.** `scripts/dev-up` cannot damage the owner keys.

### 0.2 A second, real preflight finding: `.env` is missing every infra secret

`C:/repo/SUNIL/.env` currently carries 18 keys, all *application* keys
(`DATABASE_URL`, provider keys, `GITHUB_TOKEN`, session/owner, `SUNIL_*`).
`.env.example` declares 49, and **none** of the five secrets `dev-up` treats as
hard requirements is present:

| required by `dev-up.ps1:142` | present in `.env` |
|---|---|
| `POSTGRES_PASSWORD`     | no |
| `LITELLM_MASTER_KEY`    | no |
| `N8N_ENCRYPTION_KEY`    | no |
| `LITELLM_DB_PASSWORD`   | no |
| `N8N_DB_PASSWORD`       | no |

There is also a `C:/repo/SUNIL/.env.bak-1787013569` (2026-08-18) whose key set is
the *same* application-only set, so the infra half was already absent a month
ago rather than being lost by a recent edit.

Consequence: `dev-up` would have refused to boot with
`POSTGRES_PASSWORD is missing or empty in .env` — correctly, by design. The fix
is **additive** (append the five generated infra secrets plus the port/db vars
to the existing file, touching no existing line, after a timestamped backup), so
no real key is ever rewritten. Not applied yet — see 0.3 for why it would not
have helped.

### 0.3 THE BLOCKER: Docker Desktop cannot start — half-applied 4.90.0 → 4.91.0 update

Symptom, from `C:/repo/SUNIL`:

```
$ docker info --format '{{.ServerVersion}}'
Error response from daemon: Docker Desktop is unable to start
$ docker info   # tail
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine;
check if the path is correct and if the daemon is running:
open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

Investigation, in order:

1. Docker Desktop processes were running and the `docker-desktop` WSL distro
   reported `Running`, so this was not "the app is closed".
2. `%LOCALAPPDATA%\Docker\log\host\com.docker.backend.exe.log` was looping once
   a second on
   `[vpnkit-bridge] /run/guest-services/socketforwarder-receive-fds.sock: does
   not exist yet, waiting for it to be created` — the VM was up but its guest
   services never came up inside it.
3. Cleared the obvious cause (a wedged VM): quit Docker Desktop, killed the
   remaining `*docker*` processes, `wsl --shutdown` (only `docker-desktop` is
   registered, so nothing else was disturbed), relaunched. **It did not fix it**
   — and the relaunch surfaced the real error, which the wedged run had hidden:

```
[wsl-bootstrap][F] preparing environment: setting up <USER> fs:
  mounting base image /c/Program Files/Docker/Docker/resources/docker-desktop.iso
  on /tmp/docker-desktop-<USER>-ro: copying to cache:
  expected digest 90f23c48dd4b16134b89791ff0260f3c3f38d8d77d5f918fcdc40aa97192ae29
  actual   digest 6ddb76cfa098144d2260fc1ff4208551ecaae081e72fa1e24602efd77cffe7c0
```

4. Confirmed it against the file itself rather than trusting the message:

```
$ Get-FileHash "C:\Program Files\Docker\Docker\resources\docker-desktop.iso" -Algorithm SHA256
6ddb76cfa098144d2260fc1ff4208551ecaae081e72fa1e24602efd77cffe7c0
   (780,470,272 bytes, written 2026-09-17)
```

The installed ISO hashes to **exactly the "actual" digest the backend
rejected**. The 4.91.0 backend wants `90f23c48…`; the settings store records
`"UpdatePreviousVersion":"4.90.0"`. So the Docker Desktop **update applied its
Windows binaries but left a base image the new build does not accept**. The
backend then aborts the WSL bootstrap, the Linux engine never starts, and the
named pipe is never created.

**This is not a stale cache and not a SUNIL problem.** The *source* file in
`Program Files` is the wrong one, so deleting any cache re-copies the same bad
ISO. Nothing in this repo, this worktree, or `.env` can affect it.

**Fix (needs a human — out of this lane's boundary):** repair/reinstall Docker
Desktop 4.91.0 so `docker-desktop.iso` is rewritten, then re-run
`scripts/dev-up`. Note before doing so: `%LOCALAPPDATA%\Docker\wsl\disk\
docker_data.vhdx` is **54 GB** of existing images/volumes — use the installer's
repair path, *not* "Reset to factory defaults", which would destroy it. This is
a workstation-level, elevation-requiring change; this lane does not make it
unattended.

### 0.4 What this does to the six legs

| Leg | Needs | Status |
|---|---|---|
| 1 — LiteLLM health + 2 completions | LiteLLM | blocked on the stack |
| 2 — first live governed turn | LiteLLM (+ API, SQLite-capable) | blocked on the stack |
| 3 — GatewayEmbedder + pgvector recall | LiteLLM **and** Postgres/pgvector | blocked on the stack |
| 4 — `GITHUB_TOKEN` posture (T-17) | nothing — plain HTTPS to api.github.com | **runnable now** |
| 5 — 3 opt-in live-gateway tests | LiteLLM | blocked on the stack |
| 6 — teardown + suite green on SQLite | nothing for the suite half | suite half runnable |

Leg 4 is therefore taken first, out of order and deliberately: it is the one
piece of commissioned live evidence this machine can produce today, and leaving
it behind a blocker it does not depend on would repeat the previous sessions'
outcome of shipping nothing.

A native-LiteLLM fallback (run the proxy from `pip` against the same
`infra/litellm/config.yaml` and the same owner keys, no Docker) is evaluated
next for legs 1/2/5; leg 3's pgvector half has no non-Docker path on this
machine (no native PostgreSQL is installed).

### 0.5 The fallback that was built: LiteLLM, natively, on the pinned config

`pip install "litellm[proxy]"` into a **scratchpad** venv (nothing installed into
`apps/api/.venv`, nothing added to the repo). The proxy runs on the repo's own
`infra/litellm/config.yaml` with **exactly two DB-only keys removed** —
`general_settings.database_url` and `general_settings.salt_key` — because both
exist only to talk to the Postgres that Docker would have provided. Verified
mechanically at generation time:

```
aliases: ['claude-sonnet', 'claude-opus', 'claude-haiku', 'gpt-flagship', 'gpt-mini']
general_settings keys kept: ['master_key']
removed (db-only): ['database_url', 'salt_key']
litellm_settings: {'drop_params': False, 'set_verbose': False, 'request_timeout': 600,
                   'turn_off_message_logging': True}
router_settings: {'routing_strategy': 'simple-shuffle', 'num_retries': 0,
                  'allowed_fails': 3, 'cooldown_time': 30}
```

The alias namespace and both DM rulings (`drop_params: false`, `num_retries: 0`)
are therefore **unchanged** — this is the pinned routing policy, not a
lookalike. The proxy's master key is generated per run, lives only in the
scratchpad, and is not an owner secret.

**What the fallback does NOT substitute for** (stated up front so no reader
over-reads the evidence below): virtual keys, per-key budgets and `/key/info`
spend all need the DB, so leg 5's unauthenticated-401 assertion cannot be
honoured here — see leg 5.

**Windows gotcha worth keeping:** LiteLLM prints a non-ASCII banner at startup;
with stdout redirected to a file, Python defaults to cp1252 and the proxy dies
in `proxy_startup_event` with `UnicodeEncodeError ... 'charmap'` and
`Application startup failed`. Set `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1` in
the child environment.

---

## Leg 1 — Gateway health and one completion per vendor

Proxy: LiteLLM native (0.5), `127.0.0.1:4000`, owner keys from
`infra/.env.litellm`, authenticated with the proxy master key.

### 1.1 Health and namespace

```
GET /health/liveliness     -> 200  "I'm alive!"
GET /health/readiness      -> 200  {"status":"healthy","db":"Not connected"}
GET /v1/models             -> 200  aliases=['claude-haiku','claude-opus',
                                            'claude-sonnet','gpt-flagship','gpt-mini']
```

The served alias set equals `config/models.yaml`'s five ids exactly, so C2 §3's
parity check is satisfied against a real proxy (`"db":"Not connected"` is the
expected, honest report of the no-DB fallback).

### 1.2 Completions — ONE VENDOR WORKS, ONE CREDENTIAL IS DEAD

| alias | status | latency | tokens (prompt/completion/total) |
|---|---|---|---|
| `claude-haiku` | **401** | 0.74 s | — (no upstream tokens billed) |
| `gpt-mini` | **200** | 3.34 s | 18 / 16 / 34 |

The `claude-haiku` body, quoted:

```
litellm.AuthenticationError: AnthropicException - {"type":"error","error":
{"type":"authentication_error","message":"API key is invalid."}}.
Received Model Group=claude-haiku  Available Model Group Fallbacks=None
```

### 1.3 Attribution: it is the CREDENTIAL, not SUNIL's plumbing

A 401 seen only through our own gateway proves nothing about whose fault it is,
so the key was put to Anthropic directly, and the failure was checked for
model-specificity:

```
ANTHROPIC_API_KEY shape: len_nonzero=True  starts_sk_ant=True  has_whitespace=False
DIRECT POST https://api.anthropic.com/v1/messages  -> 401  "API key is invalid."
gateway [claude-sonnet] -> 401
gateway [claude-opus]   -> 401
```

The key is **well-formed** (`sk-ant-` prefix, no stray whitespace, so this is not
a `.env` parsing artefact) and **Anthropic itself rejects it**, for every
Anthropic alias. **The owner's Anthropic credential is invalid or revoked.**
Nothing in SUNIL can fix this; it needs a new key in `infra/.env.litellm`.

### 1.4 THE FIRST REAL MODEL OUTPUT IN SUNIL'S HISTORY

With a budget that survives reasoning tokens (see the finding below):

```
gateway [gpt-mini, max_tokens=600] -> 200
  upstream_model = gpt-mini
  usage = {"prompt_tokens": 18, "completion_tokens": 75, "total_tokens": 93,
           "completion_tokens_details": {"reasoning_tokens": 64, ...}}
  finish_reason = stop
  RESPONSE TEXT: "Canberra"
```

Prompt: *"Reply with exactly one word: the capital city of Australia."*
A real model, reached through the pinned gateway config on the owner's own key,
answered **"Canberra"**. 93 upstream tokens.

### 1.5 Finding worth carrying: `max_tokens` is not a text budget on gpt-5-mini

The first `gpt-mini` call returned **200 with `finish_reason="length"` and an
empty string**: `max_tokens=16` was consumed entirely by 16 reasoning tokens,
leaving nothing for visible text. At 600 the same prompt spent 64 reasoning
tokens and then answered.

This matters beyond this leg: a caller that sets a small `max_tokens` on a
reasoning model gets a **successful, empty** completion, not an error. Anywhere
SUNIL asks for structured output (the plan stage) under a tight budget, that
surfaces as schema-validation failure with a 200 and no clue why. Recommend a
floor on `max_tokens` for reasoning-class models, or an explicit empty-content
check at the C2 boundary.

---

## Leg 4 — `GITHUB_TOKEN` posture (T-17) — **FAIL: the token is dead**

Taken out of order because it needs no stack (see 0.4). Target repository is
`codely-isuru/SUNIL`, from `config/projects.yaml` — the only project with a
`repo:`, so the only repository the native tool can reach.

Probed with the token from `C:/repo/SUNIL/.env`, via plain HTTPS to
`https://api.github.com` (the value of `GITHUB_API_BASE_URL`), with
`Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2022-11-28`:

| probe | class | result |
|---|---|---|
| `GET /repos/codely-isuru/SUNIL/commits?per_page=1` | read | **401** `Bad credentials` |
| `GET /repos/codely-isuru/SUNIL` | read | **401** `Bad credentials` |
| `GET /user` | read | **401** `Bad credentials` |
| `GET /rate_limit` | read | **401** `Bad credentials` |
| `GET /user/repos` | read (classic-shaped) | **401** `Bad credentials` |
| `GET /repos/{o}/{r}/actions/permissions` | admin read | **401** `Bad credentials` |
| `PATCH /git/refs/heads/<nonexistent>` | **write-class** | **401** `Bad credentials` |
| `POST /repos/{o}/{r}/merges` (two nonexistent branches) | **write-class** | **401** `Bad credentials` |
| `GET /repos/codely-isuru/easy_clean_workforce` | containment | **401** `Bad credentials` |

`GET /rate_limit` is the decisive one: it is satisfied by **any** valid
credential, including a token with no repository permissions at all. A 401 there
means the credential is not accepted by GitHub at all — **expired, revoked, or
never valid** — rather than under-scoped.

**Verdict: FAIL.** T-17's posture is **unverified and unverifiable** with this
token. Its THREAT_MODEL rating is still "Mitigated" on the strength of
"provisioning is the owner's action", and as the 2026-08-19 M1 worklog already
said, *provisioning is not verification*.

**On the two write-class probes:** both were chosen to be **incapable of
mutating anything** even against a fully privileged token — `PATCH` of a ref
that does not exist, and a merge of two branches that do not exist. Success is
impossible; only the authorisation verdict can vary. That is the way to test for
write refusal without attempting a write, and it answers the M1 worklog's
"proving absence of write access … attempting a write is out".

**Fine-grained vs classic: indeterminate, leaning fine-grained.** The intended
detector is the `x-oauth-scopes` response header, which GitHub returns for
classic tokens and omits for fine-grained ones. On a 401 GitHub returns **no**
`x-oauth-scopes` header at all, so the detector cannot fire — absence here means
"rejected", not "fine-grained". The only surviving signal is the token's own
prefix, which is the `github_pat_` form (fine-grained), **not** the classic
`ghp_` form. That is suggestive, not proof, and it is recorded as a boolean
only — never as an assertion operand, because pytest prints operands on failure
and that is precisely how M1 leaked a credential into a terminal.

**Recommendation to the owner (needed before T-17 can be closed):**
1. Issue a **fine-grained** PAT scoped to `codely-isuru/SUNIL` alone, with
   Contents / Pull requests / Issues at **Read**, nothing at Write, no
   Administration. (If a classic token is issued instead, this leg is an
   automatic FAIL: classic tokens are account-wide and cannot satisfy T-17.)
2. Put it in `C:/repo/SUNIL/.env` as `GITHUB_TOKEN`.
3. Re-run the env-gated live tests added in this lane; they skip loudly when
   unset and will then assert read-200 / write-class-refused / not-classic for
   real.

**Consequence for leg 2:** the live governed turn cannot use the native GitHub
tool — it would prove only that a dead credential 401s. Leg 2 therefore uses the
MCP stdio fixture for the tool step, and says so.

---

## Leg 5 — The three opt-in live-gateway tests, run for real

```
SUNIL_LIVE_GATEWAY_TEST=1
SUNIL_LLM_GATEWAY_BASE_URL=http://127.0.0.1:4000
LITELLM_VIRTUAL_KEY_DEFAULT=<the native proxy's master key>
python -m pytest tests/unit/providers/test_gateway_live.py -v

2 failed, 1 passed in 0.72s
```

| test | result | meaning |
|---|---|---|
| `test_live_parity_check_passes_against_the_running_gateway` | **PASS** | real evidence |
| `test_live_gateway_rejects_a_completion_with_no_credential_at_all` | FAIL | fallback artefact |
| `test_live_gateway_rejects_an_unknown_virtual_key_as_auth` | FAIL | fallback artefact |

**The pass is the real one.** `GatewayProvider.start()` fetched `GET /v1/models`
from a live LiteLLM, parsed the actual payload shape, and found every
`config/models.yaml` alias served — C2 §3's parity check proven end to end
against a running proxy for the first time, not against a mock transport.

**The two failures are the missing database, and that is shown, not asserted.**
Both tests are about the *authentication* path, and in LiteLLM that path is
resolved against the DB that Docker would have provided:

```
POST /v1/chat/completions, no Authorization header
  -> 500  {"message":"Internal server error","type":"internal_server_error"}
     (test expects 401)

POST /v1/chat/completions, Authorization: Bearer sk-not-a-registered-virtual-key
  -> 400  {"message":"No connected db.","type":"no_db_connection","code":"400"}
     (test expects a 401 the adapter classifies as kind="auth";
      it correctly classified this 400 as kind="bad_request")
```

`"No connected db."` names the cause outright: with no database, LiteLLM cannot
resolve a virtual key at all, so it cannot reach the 401 the test is about. The
adapter itself behaved correctly — given a 400 it said `bad_request`, which is
the right classification of the input it got.

**Therefore: these two tests are NOT satisfied, and Security's deferred item 7
(the pinned proxy 401s an unauthenticated completion) remains UNPROVEN.** They
must be re-run on the Dockerised stack once 0.3 is fixed. Recording them as
"environmental" without showing the `no_db_connection` body would have been
exactly the kind of unfalsifiable claim the M1 worklog warns about.

---

## Leg 3 — GatewayEmbedder round-trip — **BLOCKED, one step further than expected**

`text-embedding-3-small` was added to the native proxy's `model_list` (parity is
unaffected: `GatewayProvider.start()` tolerates extra deployments by design —
"SUNIL only ever names its own ids"). The proxy restarted serving six aliases.

The shipped `GatewayEmbedder` was then driven directly — the real class from
`sunil/core/memory/embedding.py`, not a reimplementation:

```
embedder name   : gateway:text-embedding-3-small
declared dim    : 1536  (module EMBEDDING_DIM=1536)
-> EmbeddingUnavailableError: gateway returned HTTP 400 for an embedding call
```

The class refuses to copy the upstream body into its message (deliberate: the
body can carry a key fragment), so the body was fetched separately:

```
POST /v1/embeddings  -> 400
{"error":{"message":"No connected db.","type":"no_db_connection","code":"400"}}
```

**The same root cause as leg 5, on a different route.** Note the asymmetry
worth knowing: `/v1/chat/completions` accepts the master key without a DB (leg 1
got a real completion through it), but `/v1/embeddings` does not — its auth path
goes to the database. So the no-Docker fallback can prove chat and cannot prove
embeddings, and leg 3 is blocked on 0.3 for **two** independent reasons:

1. LiteLLM's `/v1/embeddings` auth requires the DB;
2. the recall half needs Postgres + pgvector, which does not exist on this
   machine outside Docker (no native PostgreSQL is installed).

**Not claimed:** nothing about embedding width, semantic ranking or
hashing-versus-embeddings is asserted here. One `GatewayEmbedder` line is proven
— `name` and `dimension` are `gateway:text-embedding-3-small` / 1536 — and the
error translation is proven (a 400 became `EmbeddingUnavailableError` with the
body withheld). The round-trip itself is **unproven**, and the C3 docstring's
"**Live-unproven**" caveat stands unchanged.

---

## Leg 2 — The first live governed turn — **NOT ATTEMPTED**

Stated plainly rather than part-done. Two of its three real ingredients are
missing on this machine at this moment:

* the **tool** step cannot be the native GitHub tool (leg 4: the token 401s), so
  it would have to be the MCP stdio fixture;
* the **model** step cannot use the `claude-*` aliases the agents are configured
  for (leg 1: the Anthropic credential is invalid), so the agents would have to
  be repointed at `gpt-mini`/`gpt-flagship` first;
* `llm_calls` rows, the twelve stages and the 40 s deadline all need the API on
  real seams, which is reachable on the SQLite leg — that part is fine.

Repointing the agent catalogue is a real config change with review implications
(which model plans, which analyses, cost), not a test fixture, and doing it
unreviewed to manufacture a green turn would produce a proof of the wrong thing.
It is left for the next session, which should: fix 0.3, replace the two dead
credentials, then run leg 2 as commissioned on the Dockerised stack.

---

## Leg 6 — Teardown and the suite

**Teardown.** The native proxy was stopped and the port confirmed free
(`Get-NetTCPConnection -LocalPort 4000` → nothing listening). The generated
master key file was deleted from the scratchpad. The Docker stack needed no
teardown — it never came up (0.3). Nothing was installed into `apps/api/.venv`;
the LiteLLM venv lives in the session scratchpad and is not part of the repo.

**Suite, on the SQLite leg, with the new file present:**

```
1085 passed, 53 skipped, 5 warnings in 20.98s
```

Before this lane's test file the same command gave `1085 passed, 47 skipped`, so
the six new tests account for the entire difference and **no existing test
changed state**.

**The new tests skip loudly when unset** — verified, not assumed:

```
SKIPPED [2] ...:115: live GitHub posture check is opt-in: set
            SUNIL_LIVE_GITHUB_TEST=1 with a GITHUB_TOKEN in the environment
```

...and go red with a diagnosis, not a bare comparison, when run against the
dead token:

```
AssertionError: GitHub rejected the credential outright (HTTP 401). The token is
expired, revoked or invalid - T-17 cannot be verified until it is replaced.
AssertionError: write-class probe 'patch-nonexistent-ref' returned HTTP 401;
403 is required. 404/422 means the token passed the authorisation check and
holds write access that T-17 forbids.
```

`test_the_token_is_not_a_classic_pat` **skips** rather than passing falsely,
because GitHub sends no `x-oauth-scopes` header on a rejection and the token
class is therefore genuinely indeterminate. No test message contains any part of
a credential.

---

## Ledger

| Leg | Outcome |
|---|---|
| 0 preflight | `dev-up` proven non-clobbering; `.env` missing all infra secrets; **Docker Desktop blocked** (bad ISO after a half-applied update) |
| 1 health + completions | **DONE (via native fallback)** — health 200, alias parity exact, `gpt-mini` → `"Canberra"`, 93 tokens. `claude-*` 401: **Anthropic credential invalid** |
| 2 live governed turn | **NOT ATTEMPTED** — needs a working model alias *and* a working tool; both are dead |
| 3 GatewayEmbedder + recall | **BLOCKED** — `/v1/embeddings` needs the DB; pgvector needs Docker |
| 4 GITHUB_TOKEN / T-17 | **FAIL** — token 401s everywhere; 6 env-gated tests added so the re-check is one command |
| 5 three opt-in live tests | 1 real PASS (parity), 2 blocked by `no_db_connection` — **Security deferred item 7 still unproven** |
| 6 teardown + suite | **DONE** — 1085 passed / 53 skipped |

**Upstream spend: 127 tokens total** (`gpt-mini`: 18+16 on the truncated first
call, 18+75 on the second; all other calls were rejected before reaching a
provider and billed nothing). Cheap aliases only; no `claude-opus` or
`gpt-flagship` call was ever completed.

## What the owner has to do before this lane can finish

1. **Repair Docker Desktop 4.91.0** so `docker-desktop.iso` matches the build
   (0.3). Use the installer's repair path — *not* factory reset: there is a
   54 GB `docker_data.vhdx`.
2. **Replace `ANTHROPIC_API_KEY`** in `infra/.env.litellm`. The current one is
   rejected by Anthropic directly.
3. **Replace `GITHUB_TOKEN`** in `.env` with a fine-grained PAT scoped to
   `codely-isuru/SUNIL`, read-only (leg 4). Treat this as a **rotation**: the
   current value is invalid *and* was handled in a terminal during this
   investigation, so it should not be reused even if it is later found to work.
4. **Append the five infra secrets** to `.env` (0.2) — additively, after a
   backup, so no existing real key is touched.

Then: legs 2 and 3 as commissioned, and re-run leg 5's two blocked tests.
