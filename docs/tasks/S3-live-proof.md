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
