# Project memory — devops_engineer (SUNIL)

Lessons learned on this project. Append; do not rewrite history.

---

## L-P0-1 — PowerShell 5.1 + BOM-less UTF-8 = broken parse from a single em dash

**LESSON:** `scripts/dev-up.ps1` failed to parse on Windows PowerShell 5.1 with
*"Unexpected token 'the' in expression or statement"*, and the reported error line contained
nothing unusual to the eye.

**ROOT CAUSE:** not the logic — the **encoding**. The file was BOM-less UTF-8. Windows
PowerShell 5.1 decodes BOM-less files as cp1252, so an em dash (U+2014 = bytes `E2 80 94`)
decoded as three cp1252 characters whose last is `0x94` = `”`, a right double quotation mark
that PowerShell treats as a **string delimiter**. One em dash inside a string silently
terminated it, and the rest of the line parsed as bare tokens.

**RULE:** keep every executable script (`*.ps1`, `*.sh`) **ASCII-only and LF-terminated**, and
enforce it in CI with a byte-level check. Use `-`, never `—`. Two corollaries:
- Parse-checking with `pwsh` (PowerShell 7) on a Linux runner does **not** catch this — PS7
  reads UTF-8 correctly and parses happily. Only a byte-level check catches it off-Windows.
  Likewise PS7 accepts `??`, `?:` and `?.`, which 5.1 rejects; if the target is 5.1, parse-check
  on 5.1.
- Markdown/YAML are unaffected; this rule is about files an interpreter executes.

## L-P0-2 — a `grep`-based guard can fail open

**LESSON:** I first wrote the ASCII guard as `if grep -qP '[^\x00-\x7F]' "$f"; then ...`. It
reported "all clean" on files that definitely contained em dashes.

**ROOT CAUSE:** `grep -P` (PCRE) is an optional, locale-dependent feature. This machine's Git
Bash grep errored with *"-P supports only unibyte and UTF-8 locales"* and returned exit **2**,
which `if grep -q` reads as "no match" — so the guard passed precisely because it had broken.

**RULE:** a check whose job is to fail the build must not be able to **fail open**. Never let a
tool's error exit code be indistinguishable from its success-with-no-findings code. Prefer an
explicit interpreter (`python`, with explicit `sys.exit`) over a shell one-liner whose exit codes
are overloaded; and always test a guard against a file that *should* fail it.

## L-P0-3 — verify third-party image tags against the registry, don't recall them

**LESSON:** Pinning LiteLLM/n8n/pgvector from memory would have produced wrong or floating tags.

**ROOT CAUSE:** upstream release channels differ per project and move fast — n8n's `stable` tag
resolved to 2.38.5 while 2.39.1 was already published on the `latest` lane; LiteLLM's vetted lane
is a `-stable`/`.patch.N` suffix (highest: `v1.83.14-stable.patch.3`) that runs *behind* the
`v1.89.x` weekly head, so "highest version number" is the wrong heuristic.

**RULE:** before pinning, query the registry — Docker Hub `/v2/repositories/<repo>/tags/`, or for
GHCR fetch an anonymous pull token and walk the paginated `/v2/<repo>/tags/list` (it pages via the
`Link` header; the first page is not the newest). Resolve `stable`/`latest` to a digest with
`docker buildx imagetools inspect --format '{{.Manifest.Digest}}'` to learn which concrete version
a channel points at, then pin that concrete version. Add a CI assertion rejecting floating tags.

## L-P0-4 — port recon must be host-level, and the obvious fallback may also be taken

**LESSON:** Reinforces the central-memory lesson about host-level listeners, with a new wrinkle.
The brief said "5678 may be busy, use 5679 if so" — **both** were busy, held by a *single*
host-native node process (the local n8n source build), and 5432 was busy too (an unrelated
container from another project).

**RULE:** enumerate actual listeners (`Get-NetTCPConnection -State Listen` / `ss -ltnp`) *and*
map PIDs to process names before choosing any host port; check the suggested fallback too rather
than assuming it is free; then scan forward for the first genuinely free port and **document why**
the default was not used. On a shared dev box, assume every conventional port is already taken by
some other project.

## L-P0-5 — I captured the evidence and did not READ it against the ADR I had cited

**LESSON:** Phase 0 was BLOCKED by both reviewers for publishing every port on `0.0.0.0`. The
damning part is not the mistake, it is where it was found: **in my own acceptance evidence.** I
pasted `0.0.0.0:4000`, `0.0.0.0:5680`, `0.0.0.0:5433` into the task file as *proof of success*,
three paragraphs after citing ADR-032 — the ADR that rejects `0.0.0.0` by name. I ran the right
command, transcribed the right output, and never compared it to the requirement. QA and Security
both read the paste and found the defect in it.

**ROOT CAUSE:** I treated evidence as a ritual to satisfy ("did the command run and did it
produce output?") rather than as an assertion to check ("does this output satisfy the specific
clause I am claiming compliance with?"). Docker's default publish behaviour is `0.0.0.0` and the
short `"5433:5432"` form gives no visual hint that a host IP is missing, so nothing prompted the
comparison. Related self-deception in the same task file: I claimed a first boot on a volume
that already existed, so the init script never ran — "the stack came up healthy" was true and
"the init script created three databases" was read off an earlier run's volume.

**RULE — three habits, in order:**
1. **Every evidence line gets read back against the specific clause it proves.** Quote the
   requirement next to the output. If I cite an ADR, I open it and check the paste against its
   wording — a citation is not a check.
2. **A first-boot claim requires a proven-empty volume.** Before claiming any once-per-volume
   behaviour (init scripts, `initdb`, migrations, seed data), name the volumes, delete them,
   show `docker volume ls` returning nothing for that project, and only then boot. If the
   pre-condition is not in the evidence, the claim is not evidence. Same class as any
   "idempotent"/"fresh install" claim: state the starting state or do not make the claim.
3. **Turn the check into a machine that reads it for me.** A human reading their own output is
   the weakest link, so the assertion now lives in CI: parse the resolved compose config and
   assert `host_ip == 127.0.0.1` on every published port, and assert the ports equal the ADR's
   table. Anything I would have to remember to eyeball is a check I will eventually skip.

## L-P0-6 — "unset resolves to empty, so the container fails loudly" is an assumption, not a fact

**LESSON:** I declared secrets as bare `${VAR}` and documented that an unset value "makes the
container fail loudly instead of silently running a known-value secret." False for n8n: an empty
`N8N_ENCRYPTION_KEY` makes it **generate its own key**, so the vault holding every tool
credential ends up encrypted under a key nobody manages or backs up. I never tested it — the
comment described intended behaviour as though it were observed behaviour.

**ROOT CAUSE:** a convenience convention (empty must be safe, because it keeps
`docker compose config` lintable in CI without a `.env`) got retro-justified with a fail-closed
story I had not verified for any of the four services it covered.

**RULE:** prefer `${VAR:?message}` — Compose then refuses to resolve at all, which is
fail-closed by construction and needs no per-image knowledge. Keep CI lintable by passing
`--env-file .env.example` instead, and add the inverse assertion: `config` with **no** env file
must FAIL, so the guard is tested rather than assumed. Generally: when a comment claims a
failure mode, either reproduce it or delete the claim.

## L-P0-7 — never let a placeholder filter see the filename

**LESSON:** My CI secret scan piped `git grep -n` through
`grep -viE 'dummy|change-me|example|placeholder'`. The filter matched **whole lines including
the path**, so every finding in a path containing "example" was dropped — a real Anthropic key
pasted into `.env.example` was invisible to the scan whose entire purpose is guarding
`.env.example`. QA demonstrated it with a planted key.

**ROOT CAUSE:** the filter's intended domain was the matched VALUE; its actual domain was
`path:lineno:content`. Composing two line-oriented tools silently widened the input.

**RULE:** allowlists apply to the narrowest possible field, extracted first. Split
`path:lineno:content` and filter `content` only. Then prove it: plant a real-shaped secret in
the file the scan is most responsible for and confirm exit 1. A scan that has never caught
anything is untested, not clean. (Third instance of the same family as L-P0-2: guards need
negative fixtures. I now write the failing fixture *first*, run it, then delete it.)

## L-P0-8 — one shared `.env` breaks credential scoping no matter what the ADR says

**LESSON:** ADR-030 §2 says the application never holds an upstream provider key, and I put
`ANTHROPIC_API_KEY` in the single root `.env` that Compose interpolation, `dev-up` and every
future container read. The architectural boundary existed only in prose.

**RULE:** scope a credential to the one consumer that needs it — a per-service `env_file:` with
its own gitignored file and a committed `.example` twin. Verify by inspection, per container
(`docker exec <other-service> printenv THE_KEY` must be empty). And remember `environment:`
**overrides** `env_file:` in Compose, so naming the variable in both silently blanks the scoped
value.

## L-P0-9 — a worktree on a CRLF machine can defeat `.gitattributes`

**LESSON:** `.gitattributes` said `*.sh text eol=lf` and the index was clean, yet this worktree
held CRLF copies of the bind-mounted Postgres init script. A true first boot would have failed
with exit **255** (the kernel cannot find the interpreter named on a `#!...\r` line). It only
went unnoticed because the volume already existed, so the script never ran.

**RULE:** after creating a worktree on a machine with `core.autocrlf=true`, renormalise
(`git rm -q --cached -r . && git reset --hard HEAD`) and verify with
`file path/to/script.sh` — it must not say "CRLF". Do this for anything a container or
interpreter executes, before trusting a green run. Side note: the renormalise may surface
CRLF-in-blob for files outside your lane (it did: two `.md` files) — flag those to their owner
rather than committing another lane's 291-line whitespace diff.

## Handy facts for this project

- Windows build machine: Docker engine 29.7.2, Compose v5.5.1, daemon normally **up**.
- Reserved: **4317 = Minions Portal**, never bind it. Occupied by others: 5432, 5678, 5679, 3000, 3306.
- SUNIL V2 platform ports: Postgres **5433**, LiteLLM **4000**, n8n **5680** — all bound to
  **127.0.0.1**, asserted in CI by parsing the resolved compose config.
- This host's own IPv4 addresses, for off-loopback probes: `172.21.240.1`, `172.30.112.1`,
  `192.168.0.243`. A correct probe returns **curl exit 7** (connection refused).
- Two env files: root `.env` (everything) and `infra/.env.litellm` (provider keys +
  `LITELLM_SALT_KEY`, litellm container only). Both gitignored, both with committed `.example`.
- Three DB roles: `sunil` (superuser), `litellm_user`, `n8n_user`; the last two cannot connect
  to `sunil`. Created by the init script, which runs **once per volume**.
- `sunil-v2` volumes are `sunil-v2_pgdata` / `sunil-v2_n8n_data`. `sunil_pgdata` and
  `sunil_redisdata` are **V1's** — never delete those, and never run a bare `docker volume
  prune` on this shared box (six unrelated projects live here).
- Local CI dry-run trick: parse `.github/workflows/ci.yml`, pull each step's `run:` block and
  execute it verbatim, so the dry-run tests the shipped text. Under Git Bash, invoke
  `C:/Program Files/Git/usr/bin/bash.exe` explicitly — a plain `bash` from Windows Python
  resolves to WSL's bash, which fails with `execvpe(/bin/bash)`.
- Compose looks for `.env` in the **compose file's** directory. Since ours lives in `infra/` but
  the env file is at the repo root, every invocation needs an explicit
  `--env-file .env`, or interpolation silently resolves to empty.
- The repo is **public**: no `secrets.*` in workflows, `permissions: contents: read` at workflow
  level (convention inherited from `docs/CI.md`).
- `python`, never `python3` — this machine's `python3` is a broken Microsoft Store stub.
