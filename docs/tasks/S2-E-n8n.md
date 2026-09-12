# S2-E-n8n — the n8n lane (Stream E)

**Branch:** `task/S2-E-n8n` (cut from `V2` @`6280f48`) · **Lane:** backend_engineer · **Date:** 2026-09-12
**Scope owned this round:** `config/tools.yaml`, `config/permissions.yaml`, `infra/n8n/**`,
`scripts/n8n-*`, `apps/api/tests/unit/n8n/**`, this file, plus one additive model in
`apps/api/sunil/tools/mcp/params.py` (§7).

ADR-030 §5 gives n8n two jobs and this round delivers both, plus the answer to the security item
that has been deferred since the platform review: **does n8n actually enforce the MCP bearer?**
It does. §4 is the evidence.

---

## 1. Boot and owner setup, scripted

`scripts/n8n-setup.sh` / `scripts/n8n-setup.ps1` (POSIX + Windows twins, same behaviour, same exit
codes). One command from a clean machine:

1. boots the platform if n8n is not answering `/healthz` (delegates to `dev-up.*`, never
   re-implements it);
2. **claims the owner** with a GENERATED password written to `.env` (gitignored), then signs in;
3. creates/updates the two `httpBearerAuth` credentials that hold SUNIL's tokens — in n8n's
   **encrypted vault**, never in a file;
4. imports every `infra/n8n/workflows/*.json`, substituting credential ids, and activates each one.

**Why the owner setup is scripted rather than documented.** n8n 2.x serves an *unauthenticated*
owner-setup screen until somebody claims it: whoever reaches the port first owns the credential
vault. Compose already binds the port to `127.0.0.1` (ADR-032, Phase 0 security review B2), which
closes the window to everything off this host. The script closes it to a human who forgets — and it
means the owner password is a generated value nobody ever types, which is the only kind a
development instance keeps.

**Idempotent, proved by running it.** Run 1 on a cleared instance: four workflows `created and
ACTIVE`. Run 2 immediately after: four workflows `updated and ACTIVE`, credentials PATCHed in place
(a rotation keeps the credential **id**, so it does not orphan the workflows that reference it).
The PowerShell twin was then run against the same instance: four `updated and ACTIVE`.

### Three things the API made us learn, all recorded in the scripts

| Symptom | Cause | What the script does |
|---|---|---|
| Workflow imported, webhook answers 404 | `PATCH {"active": true}` returns **200 and does nothing** in n8n 2.x. Activation is its own endpoint and needs the current `versionId`. | `POST /rest/workflows/{id}/activate` with `{versionId}`, and the result's `active` is checked rather than assumed |
| A re-run created a SECOND copy of every workflow | the create-vs-update match is by workflow **name**, and an em dash in the name came back mangled through Git Bash on Windows | workflow names are ASCII (`SUNIL - …`), pinned by `test_workflow_names_are_ascii` |
| PowerShell: every authenticated call 401s with a valid session | two PS 5.1 behaviours at once — n8n sets `n8n-auth` with `Secure` even over loopback HTTP (the automatic container then never sends it), and `Cookie` is a **restricted** request header that `-Headers` drops *silently* | the cookie is re-added to a `WebRequestSession` container as a `System.Net.Cookie` (Secure defaults to `$false`). Both paths were tested against the live container before the fix was written |

---

## 2. The three scheduled trigger workflows

`infra/n8n/workflows/sunil-{morning-brief,project-monitor,support-sweep}.json` — cron schedule →
`POST /api/v1/chat` on the ADR-035 service bearer → a Code node that records whether the trigger
landed. Nothing else. n8n supplies **the clock and the instruction**; every judgement happens inside
the turn the POST starts, and no workflow touches SUNIL's database (ADR-030 §5, TB9).

| workflow | cron (Australia/Melbourne) | `X-SUNIL-Channel-Label` |
|---|---|---|
| morning brief | `0 7 * * 1-5` | `n8n:morning-brief` |
| project monitor | `0 9-17/2 * * 1-5` | `n8n:project-monitor` |
| support sweep | `30 16 * * 1-5` | `n8n:support-sweep` |

The timezone is pinned per workflow in `settings.timezone`, not inherited from the container: a brief
that silently moves an hour on a DST boundary is a bug nobody reports.

**The instructions are real.** The support sweep asks for a *drafted* holding reply and says
explicitly not to send anything — anything leaving SUNIL for a client goes through C4's approval, and
a schedule must not become a way around that. The project monitor asks for exceptions only ("if
nothing qualifies, reply with exactly: all clear"), because a two-hourly schedule that always
produces prose is a two-hourly schedule nobody reads.

**They cannot post into the owner's chats.** C5 §2.3's ratified design: the bearer lane may only read
and extend conversations it created. The evidence run below lands in `conv-svc-2`, a service-channel
conversation, exactly as designed.

**Graceful failure is a property of the export, not a hope.** `onError: continueRegularOutput` +
`alwaysOutputData` + `neverError` + a 3-try retry + a 120 s timeout. Proved by killing the API and
firing the workflow again: execution **5** finished `status: success` with the outcome node reporting
the failure, instead of leaving a red execution and a retry storm.

### The host route, verified from inside the container

```
$ docker exec sunil-v2-e-n8n sh -c 'wget -q -O- --timeout=3 http://host.docker.internal:1/'
wget: can't connect to remote host (192.168.65.254): Connection refused
```

`host.docker.internal` resolves and routes from the n8n container on Docker Desktop for Windows
(192.168.65.254 is the host as the container sees it — "connection refused" on port 1 is the proof
that DNS and routing both work). That is the URL in the exports.

**On the ADR-032 deployment target this changes**, and it is the one line to edit when the app
container lands: when SUNIL runs in Compose alongside n8n, the URL becomes the in-network
`http://api:8000/api/v1/chat`, exactly as `infra/docker-compose.yml`'s commented stub already uses
service names for every other seam.

---

## 3. The MCP server workflow and its mount

`infra/n8n/workflows/sunil-mcp-server.json` — an **MCP Server Trigger** (node type
`@n8n/n8n-nodes-langchain.mcpTrigger`, typeVersion 2.1) at path `sunil`, publishing one `toolCode`
node named `post_update`. The node NAME is the MCP tool name from `toolCode` v1.2 onward, and it must
equal the operation name in `config/tools.yaml` — the startup drift check compares them.

The demo body deliberately writes nowhere. What is being proved is the **governance path** — plan →
SUNIL's params model → `ask_user` → owner approval → chokepoint → the tool — not the storage.
Replacing the body with a real write changes nothing about who may call it.

Mounted in `config/tools.yaml` under the existing `n8n_mcp` block (one MCP server is one tool,
ADR-034) and granted `post_update: ask_user` in `config/permissions.yaml`. **There is no `allow` row
on this server, by design:** n8n is the one tool whose own workflows can be rewritten in a browser,
so an unattended grant here would widen with an edit nobody reviews.

### Startup drift check, against the live endpoint

```
$ python - (real build_adapters over the repository's config/tools.yaml)
START OK: handshake + ADR-034 drift check passed against the LIVE n8n 2.38.5
operations: ['post_update']
ok: True | kind: mcp_http | ms: 69
data: {'content': [{'type': 'text', 'text': '{"ok":true,"project_key":"sunil",
       "summary":"Live governed call from the real adapter.",
       "recorded_at":"2026-09-12T11:45:08.633Z","recorded_by":"n8n:sunil-mcp-server"}'}]}
```

### DEFECT FOUND AND FIXED: `run_workflow` was taking the whole tool down

The first live run of that same command did **not** say `START OK`:

```
ToolAdapterStartupError: n8n_mcp: configured operation(s) ['run_workflow'] are not advertised
by the live server - refusing to start (ADR-034 drift check)
```

`config/tools.yaml` had declared `n8n_mcp.run_workflow` since wave 1 and **nothing ever implemented
it**. That is not a local failure: `start()` refuses, so the *entire* n8n tool leaves the registry —
one aspirational config row would have taken `post_update` down with it, at boot, on the deployment
target. It has been removed from both config files, with the reasoning and the re-add procedure in
place of the row.

It was also the wrong shape for a governed surface, which is the second reason it is not coming back
as-is: "run workflow X with payload Y" is a meta-tool whose blast radius is every workflow n8n holds
— including the three above, which carry SUNIL's service token — and whose approval card reads "run
something". Named actions are what an owner can actually consent to.

`sunil.tools.mcp.params:RunWorkflowParams` is left in the tree for whoever implements it properly.

---

## 4. THE SECURITY PROOF — deferred item 8, settled

**Question.** `docs/THREAT_MODEL.md` treats the n8n MCP endpoint as **unauthenticated** until proven
otherwise: `SUNIL_N8N_MCP_AUTH_TOKEN` is sent by SUNIL's HTTP adapter, but nobody had shown that n8n
does anything with it.

**Answer: n8n 2.38.5 enforces it.** The MCP Server Trigger node's `authentication` parameter offers
`none | n8nOAuth2 | bearerAuth | headerAuth`, and `bearerAuth` requires an `httpBearerAuth`
credential. The shipped workflow uses `bearerAuth`. Evidence, from OUTSIDE n8n, against the live
endpoint, both directions:

```
$ URL=http://127.0.0.1:5680/mcp/sunil
$ INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-06-18","capabilities":{},
        "clientInfo":{"name":"sunil-proof","version":"0"}}}'

=== A. NO Authorization header ===
HTTP/1.1 403 Forbidden
Authorization data is wrong!

=== B. WRONG bearer ===
HTTP/1.1 403 Forbidden
Authorization data is wrong!

=== C. CORRECT bearer ===
HTTP/1.1 200 OK
mcp-session-id: 74336fd2-6b2b-4c35-b923-90974166c5a8
content-type: text/event-stream

event: message
data: {"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{}},
       "serverInfo":{"name":"MCP_Server_Trigger","version":"0.1.0"}, ...},
       "jsonrpc":"2.0","id":1}
```

**D. A valid session id does NOT substitute for the token.** The obvious bypass — complete the
handshake once, then reuse the `mcp-session-id` — is refused:

```
=== tools/list with a VALID SESSION but NO bearer ===
HTTP/1.1 403 Forbidden
```

**E. The token is accepted only as a bearer**, not as anything else an attacker might find easier to
reach:

```
A_no_header        -> HTTP 403
B_wrong_token      -> HTTP 403
C_correct_token    -> HTTP 200
basic_auth         -> HTTP 403     (same token as HTTP Basic)
token_in_query     -> HTTP 403     (?token=… , no header)
```

**The authorised path works end to end** (same session, correct bearer):

```
tools/list  -> {"tools":[{"name":"post_update", "inputSchema":{... "required":["project_key","summary"],
                "additionalProperties":false}}]}
tools/call  -> {"content":[{"type":"text","text":"{\"ok\":true,\"project_key\":\"sunil\",
                \"summary\":\"...\",\"recorded_at\":\"2026-09-12T11:42:55.992Z\",
                \"recorded_by\":\"n8n:sunil-mcp-server\"}"}]}
```

### What this does and does NOT settle

**Settled:** the endpoint is authenticated, per request, including `tools/list` and `tools/call`, and
the credential lives in n8n's encrypted vault rather than in a file. The threat model's
"treat as unauthenticated" clause can be closed against n8n 2.38.5 with the MCP Server Trigger
configured as shipped.

**Not settled, and it is the part that matters operationally:** `authentication` **defaults to
`none`**, and `none` serves `initialize`, `tools/list` and `tools/call` to any unauthenticated caller
that can reach the port. The distance between the governed state and the ungoverned one is one
dropdown in a browser, and a browser change is not reviewable. So the compensating controls stay,
and they are now *three*, none of which depends on the other two:

1. **Loopback only.** `infra/docker-compose.yml` publishes n8n as `127.0.0.1:5680` (ADR-032), and CI
   already asserts `host_ip == 127.0.0.1` on every published port. An `authentication: none` accident
   is reachable from this host and nowhere else.
2. **The export is the reviewable artefact**, and a test enforces it:
   `test_the_mcp_server_trigger_requires_a_bearer` fails if `authentication` is anything but
   `bearerAuth`. Verified by flipping it to `"none"` (red), then reverting (green). Re-running
   `scripts/n8n-setup.*` re-imports the file over whatever the browser did.
3. **SUNIL fails closed on its side.** A wrong/absent token gets a 403, which the adapter turns into
   a `ToolAdapterStartupError` — so the tool is **absent from the registry**, never half-mounted
   (`test_the_recorded_403_takes_the_tool_out_of_the_registry`).

**Recommended follow-up for the security reviewer** (not this lane's to decide): add the workflow-
level `authentication` value to whatever periodic configuration audit the platform grows, since it is
the single setting that turns a governed connector fabric into an open one.

---

## 5. Tests

`apps/api/tests/unit/n8n/` — **42 tests, no container needed**.

| file | what it pins |
|---|---|
| `test_mount.py` | the repository's own `tools.yaml` + `permissions.yaml`, read through the production `decide()`: HTTP kind by Settings field name, `post_update`'s SUNIL-owned metadata, **every** `read_only: false` n8n operation is refused a bare `allow` (generic, so it fails on the next one added), an unconfigured operation is structurally denied, and the startup cross-validation |
| `test_recorded_handshake.py` | the C1 §2 lifecycle replayed through `httpx.MockTransport` from `fixtures/n8n_2_38_5_mcp.json`, a **verbatim recording of the live 2.38.5 server**: drift check against the repository's configured operations, the pinned protocol revision, the bearer on *every* request, the structured `post_update` payload, the recorded 403 → startup failure, and a pre-`start()` call that must not put the token on the wire |
| `test_credential_path.py` | condition **C-3** on the HTTP lane: the token resolves through `_settings_value`'s allowlist, and `auth_token_env: SUNIL_SERVICE_TOKEN` / `SESSION_SECRET` / `DATABASE_URL` is a named SKIP with no value in the message — against a `Settings` double that genuinely *has* all three fields, because an allowlist that only works when the field is absent is not an allowlist |
| `test_workflow_exports.py` | the exports as code: importable shape, ASCII names, **no token or `Authorization` string anywhere in the files**, `authentication: bearerAuth` on the MCP trigger, every configured operation has a node behind it, one governed POST per schedule, graceful-failure settings, and the ADR-035 channel label agreeing between header and body |

**Red first, and watched:** `test_post_update_is_a_configured_operation…` and
`test_post_update_is_granted…` failed with `KeyError: 'post_update'` / `DENY` before the two config
rows existed. `test_the_configured_operations_all_exist_on_the_recorded_server` failed with the
`run_workflow` drift — the same failure the live server had just produced — before §3's fix.
`test_the_mcp_server_trigger_requires_a_bearer` was verified red by setting `authentication: "none"`.

---

## 6. Suite, lint, secrets

| gate | result |
|---|---|
| SQLite leg (default), run 1 | **997 passed, 4 skipped** |
| SQLite leg, run 2 | **997 passed, 4 skipped** |
| Postgres leg (`SUNIL_TEST_DATABASE_URL` at the Compose database) | **1046 passed, 4 skipped** |
| `python -m compileall sunil` | clean |
| `yamllint -c .yamllint.yml config/ infra/` | clean for this lane's files. One pre-existing warning stands: `config/agents.yaml:25` line-length, Stream F's file, not touched |
| secret scan of the staged diff | clean — every real value from `.env` (both bearers, the owner password, the encryption key, the Postgres password) was grepped for by value and appears nowhere |

The four skips are the unchanged baseline (one in-memory-SQLite isolation case, three opt-in
live-gateway checks). The 42 new tests are all in `tests/unit/n8n/`; no existing test was modified.

Every generated value (owner password, both bearers) lives in `.env`, which `.gitignore` covers.
The workflow exports carry `__SUNIL_SERVICE_TOKEN_CREDENTIAL_ID__` /
`__SUNIL_MCP_BEARER_CREDENTIAL_ID__` placeholders and credential *names*.

---

## 7. Findings and things owed to other lanes

1. **`SUNIL_N8N_MCP_BASE_URL` must gain the workflow path.** `.env.example` and the compose stub say
   `…/mcp` and `http://n8n:5678/mcp`; the real endpoint is `…/mcp/sunil` — `/mcp` is a prefix and
   answers 404. n8n gives a webhook no way to be served at the bare prefix. Neither file is this
   lane's, so the exact change is recorded rather than made:
   * `.env.example:193` → `SUNIL_N8N_MCP_BASE_URL=http://localhost:5680/mcp/sunil`
   * `infra/docker-compose.yml:288` → `SUNIL_N8N_MCP_BASE_URL: http://n8n:5678/mcp/sunil`
   Both pass ADR-033's validator unchanged (loopback / the named host `n8n`).
2. **`apps/api/sunil/tools/mcp/params.py` gained `PostUpdateParams`** — additive, one class, no
   existing model touched. It is outside the file list this lane was given, and it is unavoidable:
   `params_ref:` must point at a real `extra="forbid"` model, and `post_update`'s arguments are what
   an owner reads on the approval card, so reusing `RunWorkflowParams`' free-form `payload` would
   have made the approval say "post something".
3. **Stale Compose volumes on this machine.** The first boot failed with *"Mismatching encryption
   keys"* — a `sunil-v2_n8n_data` volume left by an earlier round, whose `N8N_ENCRYPTION_KEY`
   predated this worktree's freshly generated `.env`. Rather than destroy another lane's data, this
   round ran under `COMPOSE_PROJECT_NAME=sunil-v2-e` (a `.env` value, gitignored) so its volumes are
   its own. Anyone hitting the same error on the default project name wants
   `./scripts/dev-down.sh --volumes`, and should know it takes the Postgres data with it.
4. **The evidence API is a scratchpad runner, not a repo artefact.** §8 explains exactly which seams
   were real.
5. **The `meta.sunil` block in each export is SUNIL's documentation, not n8n's.** The setup scripts
   strip it before POSTing, because n8n's API rejects unknown top-level keys. If you import one of
   these files through the editor's "Import from file", n8n ignores it harmlessly.

---

## 8. End-to-end evidence run

**What was REAL:** the n8n container (2.38.5, Postgres-backed, from `infra/docker-compose.yml`), all
four workflows imported and activated through the API, n8n's own scheduler and credential vault, the
live MCP endpoint and its auth, SUNIL's real `McpHttpAdapter` + `build_adapters` + `tools.yaml`
loader + drift check, and on the receiving end the real `create_app`, the real chat route and the
real `require_service_token` bearer lane.

**What was STUBBED:** everything *behind* the chat route — C5 §4's `StubTurnExecutor`,
`FakeConversationResolver`, `FakeProvider`, `FakeMemoryProvider`, `FakeApprovalsService`, on SQLite.
The same composition `tests/contracts/test_c5_chat.py` uses. The n8n trigger path touches none of
them, and a full governed turn is `S2-wiring`'s evidence, not this round's.

**The runner is in the scratchpad, not the repository** (the precedent `S2-wiring` §5 set with its
MCP stdio fixture server). It binds `0.0.0.0:8000` for the length of the run, because Docker
Desktop's `host.docker.internal` resolves to the host's LAN-side address and a `127.0.0.1`-only bind
does not answer it.

Trigger fired from the workflow's own schedule trigger node:

```
POST /rest/workflows/{morning-brief}/run  ->  {"data":{"executionId":"4"}}

# SUNIL's access record (chat.py's own log line):
{"request_id": "60b32987-f7a0-435e-88e0-aa74b45de5fb", "conversation_id": "conv-svc-2",
 "lane": "bearer", "outcome": "ok", "event": "chat_turn", "level": "info",
 "timestamp": "2026-09-12T11:48:26.900573Z"}
INFO: "POST /api/v1/chat HTTP/1.1" 200 OK
```

`lane: "bearer"` is the whole point: the workflow's n8n credential carried `SUNIL_SERVICE_TOKEN`
through the real ADR-035 dependency, and the turn landed in a **service-channel** conversation
(`conv-svc-2`), not in the owner's. The negative holds on the same endpoint:

```
$ curl -X POST …/api/v1/chat -H 'authorization: Bearer wrong-token' …   ->  401
```

Then the API was killed and the same workflow fired again:

```
execution 5 status: success
```

— the schedule degraded gracefully instead of going red, which is §2's claim, observed.

**The stack was left DOWN.**
