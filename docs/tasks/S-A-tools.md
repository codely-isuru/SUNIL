# S-A-tools — Stream A: the tool chokepoint, for real (C1 implementation)

**Lane:** Stream A (tools) · **Branch:** `task/S-A-tools` · **Engineer:** backend
**Gate:** Gate 2 approved · **Contracts implemented:** C1 v1.1.1 (whole document), C4 §4 consumed via
the injected seam, ADR-034 (MCP mapping and trust), ARCHITECTURE_V2 §2/§5
**Never merged by its author.**

## What shipped

| Area | Module | What it is |
|---|---|---|
| The chokepoint | `apps/api/sunil/core/tool_framework/manager.py` | C1 §2.1's seven steps, in order, for every call: resolve → validate (`extra="forbid"`) → permission → **two-phase audit** → execute under `timeout_s` → finalise → §3 wrap. One composer, one hasher; the manager is the single consume owner. |
| Hasher | `.../tool_framework/canonical.py` | C1 §6.4's rule in production code (QA keeps an independent copy; contract test 4 compares them). |
| Params redaction | `.../tool_framework/redaction.py` | `params_redacted` for the audit row and the approval card. Key-name floor only — see "Integration requirements". |
| §3 posture | `.../tool_framework/untrusted.py` | 256 KiB cap with `data["truncated"] = true`; recursive, case-insensitive strip of `instructions`/`system`/`prompt` at every depth (lists included), each removal logged **by key path**. Applied by the manager to MCP kinds. |
| Tool registry | `.../tool_framework/tools_config.py` | `config/tools.yaml` loader (ADR-034 server blocks) + `cross_validate_permissions()`. |
| Permission engine | `apps/api/sunil/core/permissions/{engine,registry}.py` | M1's shape verbatim, returning C1 §2.2's `PermissionResult`. Structural default-deny; `PermissionEngineHook` is the production `PermissionHook`. |
| Native GitHub tool | `apps/api/sunil/tools/github/{adapter,projection}.py` | M1's read-only `list_recent_activity` ported; `projection.py` is M1's code **byte for byte** (see its header), including the delimiter-escaping. |
| MCP | `apps/api/sunil/tools/mcp/{protocol,adapter,stdio,http,config,credentials,params}.py` | Pinned protocol rev `2025-06-18`; server = tool, MCP tool = operation; startup handshake + **`tools/list` drift check** → `ToolAdapterStartupError`; minimal child env (C1 §5); streamable-HTTP with session id and SSE replies. |
| Config | `config/tools.yaml`, `config/permissions.yaml` | All three adapter kinds; `github_mcp.issues_close` granted `ask_user`, matching ARCHITECTURE_V2 §6's worked example. Env-variable **names** only — no secret values. |
| Test MCP server | `apps/api/tests/unit/tools/fixtures/mcp_stub_server.py` | A stdlib-only MCP-over-stdio stub (echo, env_dump, big, sneaky) with switches for drift, protocol mismatch, error results and abrupt death. Stream A's own fixture, not QA's tree. |

## Test evidence

Contract suite **`tests/contracts/test_c1_tool_adapter.py` — before: 29 passed, 11 skipped. After:
40 passed, 0 skipped.** All eleven import-guarded pipeline tests self-activated on `manager.py`
landing and passed, including contract tests 4/5 (the park-material equality assertions and the
single-use approval), test 7's ordering probe and the §2.1 step-3 ALLOW-burn rule.

Whole suite, twice, identical: **280 passed, 14 skipped** (`pytest -q -m "not live"`,
`pytest -v --strict-markers`, `pytest -rs --strict-markers` — CI's three commands). Before this
task: 146 passed, 25 skipped. The 14 remaining skips are all other lanes' (C2 ×3, C3 ×1, C5 ×9);
**zero C1 debt rows remain**. Wall clock 1.3–2.4 s, no network, no database; the only real process
spawned is the stdio stub.

Unit tests added (114 of the new tests are this lane's): permission engine + loader (18), hasher and
redactor (6), §3 cap/strip (13), MCP credentials (8), MCP stdio against a real child (13), MCP HTTP
via `httpx.MockTransport` (16), native GitHub + projection (21), manager-side properties the contract
suite cannot reach (9), tools.yaml loader + cross-validation (14).

**Mutation proof** (the manager unit tests were written after the contract suite drove the pipeline,
so they were checked for bite rather than assumed):

| Mutation | Result |
|---|---|
| `_UNTRUSTED_KINDS = frozenset()` (no §3 sanitisation) | 2 failed (strip, cap) |
| manager trusts the adapter's own `ToolResultMeta` | 1 failed (provenance) |
| `f"unhandled adapter exception: {exc}"` (leaks raw text) | 1 failed (the token-bearing message) |

Reverted after each; green again. `yamllint -c .yamllint.yml config/tools.yaml
config/permissions.yaml` — clean.

## Decisions taken where the contract was silent

1. **The park path's attempt row carries the MINTED approval id.** C1 §2.2 describes
   `ToolCallAttempt.approval_id` as the supplied id, and on a first attempt there is none. Writing
   the id `park()` just returned makes the audit trail join to the approval a later continuation will
   present; the alternative (a `NULL`) leaves the parked call and its approval with nothing in
   common but a timestamp. The park commits first (C4 §1 restart safety), then the row.
2. **`ToolResultMeta` is re-stamped by the manager from the registry**, not taken from the adapter's
   result. `adapter_kind`/`server_id` land on `tool_calls` as facts (V2-A exit), and an MCP server's
   proxy must not be able to describe itself onto the audit trail. `duration_ms` is the manager's
   measurement, and it is the same number `finalise` reports.
3. **§3 is applied at the chokepoint, keyed on the resolved adapter kind**, not inside each adapter.
   Two adapters then cannot disagree about what "untrusted" means, and native results stay untouched
   (§3 scopes the cap and strip to MCP; a native result is SUNIL's own projection).
4. **`server_id` is read with `getattr`**, deliberately NOT added to C1 §2's `ToolAdapter` protocol —
   adding it would oblige every native adapter to declare a field whose only legal value is `None`.
5. **Protocol-revision drift fails startup.** The adapter announces the pinned MCP revision and
   refuses a server that answers with another one, rather than negotiating down: the §3 posture is
   written against one result shape.
6. **An HTTP 4xx from an MCP HTTP server is `upstream_error`, not `transport_error`.** C1 §4 names
   5xx explicitly; a 4xx was reached-and-refused, and `transport_error` is the only kind policy may
   auto-retry — hammering a 401 is not a retry strategy.
7. **An unknown `project_key` on the native GitHub tool is `invalid_params`.** M1's own
   `unknown_project` kind is not in C1 §4's closed set, and it *is* a bad parameter — the only one
   that operation has. The human detail survives in `error_message`.
8. **`credential_env` resolution happens on the `start()` path**, before the spawn, so its failure is
   "the adapter is absent from the registry" rather than an exception out of a constructor.
9. **`BOOTSTRAP_ENV_NAMES`** — a short, asserted-credential-free allowlist (`PATH`, `SystemRoot`, …)
   reaches the child in addition to its `credential_env` names, matched case-insensitively because
   Windows upper-cases `os.environ` keys. A child with no `PATH` cannot execute at all, and that
   failure presents as "the MCP server exited immediately", a long way from its cause.

## Integration requirements for the spine lane (not mine to land)

1. **Dependencies.** `apps/api/pyproject.toml` still declares only `pydantic`. This lane's
   production code needs **`pyyaml`** (both config loaders; imported lazily, with a clear error) and
   **`httpx`** (the native GitHub tool and the MCP HTTP transport; imported lazily inside the call
   path). Both are present in the dev environment, so the suite is green — but the runtime
   dependency list must gain them. I did not edit `pyproject.toml`: it is outside this lane's file
   scope and the spine lane is editing it.
2. **`Settings` fields.** `github_token`, `sunil_n8n_mcp_base_url`, `sunil_n8n_mcp_auth_token` —
   `SecretStr` for the two secrets, per ARCHITECTURE_V2 §5. The mapping rule is mechanical
   (`GITHUB_TOKEN` → `settings.github_token`) and enforced by
   `sunil/tools/mcp/credentials.py`; the ADR-033 URL validator stays Settings-side (the HTTP adapter
   only refuses a non-HTTP(S) base URL as its own floor).
3. **ADR-006 redaction registry.** `core/tool_framework/redaction.py` is a **key-name floor** and
   says so: it cannot know a secret by value. When the process-wide registry lands, the manager must
   call it **on top of** this, never instead of it.
4. **Wiring.** `load_tools_config()` + `load_permissions()` + `cross_validate_permissions()` are
   ready to be called at startup; adapters are constructed per block (`McpStdioAdapter`,
   `McpHttpAdapter`, `GitHubAdapter`) and a failed `start()` must leave that tool out of the
   registry (C1 §2). The native GitHub adapter takes a plain
   `Mapping[str, tuple[owner, repo]]` rather than a `ProjectRegistry`, so `config/projects.yaml`
   parsing stays with the registry lane.
5. **Import direction.** `core/tool_framework/tools_config.py` imports `sunil.tools.mcp.config`
   (the `McpOperationConfig` a loader produces). That is the tool_framework importing `tools/`,
   which the import law permits and M1's boundary test explicitly allowed; nothing in `tools/`
   imports `core/orchestrator`.

## Deferred / not in scope

- **The ADR-034 parity test** (native `github` vs `github_mcp` for the same triple → identical
  decision and audit row). The decision half is provable now and effectively covered by the engine
  tests; the audit-row half wants the real `AuditHook` implementation (core lane) rather than the
  recording fake, so it belongs with the first end-to-end wiring.
- **A live MCP server** (`npx @modelcontextprotocol/server-github`) has not been exercised; the
  stdio adapter is proven against a real child process speaking the pinned revision. First contact
  with the real server is a wiring-lane task, and the drift check is what will make a version
  surprise visible at startup.
- **Context-block assembly** (§3's first bullet — the delimited, role-tagged block) is the context
  builder's, not the adapter's. `projection.wrap_untrusted_tool_result()` is ported and tested and is
  the helper it should use.
- `docs/STATUS.md` and the worklog are the Delivery Manager's to update.
