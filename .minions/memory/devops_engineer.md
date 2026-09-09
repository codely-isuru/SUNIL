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

## Handy facts for this project

- Windows build machine: Docker engine 29.7.2, Compose v5.5.1, daemon normally **up**.
- Reserved: **4317 = Minions Portal**, never bind it. Occupied by others: 5432, 5678, 5679, 3000, 3306.
- SUNIL V2 platform ports: Postgres **5433**, LiteLLM **4000**, n8n **5680**.
- Compose looks for `.env` in the **compose file's** directory. Since ours lives in `infra/` but
  the env file is at the repo root, every invocation needs an explicit
  `--env-file .env`, or interpolation silently resolves to empty.
- The repo is **public**: no `secrets.*` in workflows, `permissions: contents: read` at workflow
  level (convention inherited from `docs/CI.md`).
- `python`, never `python3` — this machine's `python3` is a broken Microsoft Store stub.
