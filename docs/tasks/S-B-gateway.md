# Task — S-B-gateway: C2 v1.0.1 provider lanes + model router

Owner (backend_engineer) · Branch `task/S-B-gateway` · Status: **implementation complete —
awaiting QA/Security review**

**File ownership:** `apps/api/sunil/providers/{anthropic,openai,gateway,registry}.py`,
`apps/api/sunil/core/routing/**`, `config/models.yaml`, `apps/api/tests/unit/{providers,routing}/**`.
Two edits outside that set are declared in *Boundary exceptions* below.

## Static spec (from C2 v1.0.1 + ADR-033)

- **Objective:** real `LLMProvider` implementations over `httpx` (no vendor SDKs); the two lanes of
  C2 §3; a capability × privacy Model Router porting the M1 shapes; SUNIL-side retries per C2 §4;
  a startup `GET /v1/models` parity check against `config/models.yaml`.
- **Acceptance criteria:** all C2 contract tests green including the self-activating guarded ones;
  the ADR-033 lane-flag tripwire test present and passing; `yamllint config/models.yaml` clean;
  live parity + 401-without-credential probes run against a real LiteLLM when the daemon is up.
- **Security considerations:** ADR-033 named-host closed set; no credential ever logged or copied
  into an error message; `LOCAL_ONLY` must never silently downgrade to a remote model (§26.10).
- **Rollback:** revert the branch — nothing is wired into the app spine yet.

## What is implemented

| Area | Module | Notes |
| --- | --- | --- |
| Gateway lane (default) | `providers/gateway.py` | `POST {base}/v1/chat/completions` with the virtual key; startup `GET /v1/models` parity → `GatewayModelParityError`; HTTP→`ProviderError` classification that withholds the proxy's key-echoing body |
| Direct lane (fallback) | `providers/anthropic.py`, `providers/openai.py` | ADR-033 closed set; base URLs pinned to `https://api.anthropic.com` / `https://api.openai.com`, override admits loopback only |
| Lane selection | `providers/registry.py` | `NAMED_GATEWAY_HOSTS = frozenset({"litellm"})` is a **frozen code constant**, not config — adding a host is a reviewed code change. The lane flag is read *here* and nowhere in `core/routing` |
| Router | `core/routing/router.py` | capability × privacy; `LOCAL_ONLY` with no local provider raises before dispatch (zero provider calls) |
| Retries | `core/routing/retry.py` | C2 §4 policy; usage accumulates across **failed** attempts; `invalid_output` → exactly one re-ask when `json_schema` is set, never a third call |
| Catalogue / pricing | `core/routing/catalogue.py`, `pricing.py` | `config/models.yaml` is the single source of model ids, limits and prices |

## Test state (2026-09-12)

`python -m pytest` in `apps/api` → **326 passed, 26 skipped**. CI form (`-q -m "not live"`) identical.
`python -m yamllint config/models.yaml` → clean, exit 0.

**Live checks — actually run, not mocked.** Docker daemon up, `sunil-v2-litellm` healthy on
`127.0.0.1:4000`:

- `GET /v1/models` returned exactly `claude-haiku, claude-opus, claude-sonnet, gpt-flagship,
  gpt-mini` — equal to the five aliases in `config/models.yaml`, so the parity check passes against
  the real proxy.
- `POST /v1/chat/completions` with **no `Authorization` header** → **401** (security review deferred
  item 7, in its literal form).
- An unregistered-but-well-formed virtual key → `ProviderError(kind="auth", retryable=False)` with
  no `sk-` substring in the message.

Run them with: `SUNIL_LIVE_GATEWAY_TEST=1` plus `LITELLM_VIRTUAL_KEY_DEFAULT` taken from `.env`'s
`LITELLM_MASTER_KEY`; they skip by default so no other stream or CI job is affected.

## Boundary exceptions (flagged for review)

1. **`apps/api/tests/contracts/test_c2_provider.py`** — the two *self-activating guarded* tests
   (C2 test 3's retry clause, C2 test 5's routing rule) were placeholders that called
   `pytest.fail(...)` with a message commissioning the implementer to write the body once the
   guarded module landed. They could not go green otherwise, so the bodies were written **by the
   implementer of the module under test**, exactly to the commissioned assertions. Both docstrings
   say so. **QA must review these two bodies** — the usual "author ≠ asserter" separation does not
   hold for them.
2. **`apps/api/pyproject.toml`** — `httpx` and `pyyaml` added to `[project.dependencies]`. They were
   imported by Stream B runtime code but declared only in the `dev` extra (or nowhere), so CI's
   `pip install -e ".[dev]"` masked it and a production install would have raised
   `ModuleNotFoundError` at the first gateway call. The file's own comment anticipated this ("no
   httpx … those arrive with the Phase 2 implementations that need them"). Guarded going forward by
   `tests/unit/providers/test_runtime_dependencies.py`, which AST-walks Stream B modules — lazy
   in-function imports included — and fails on any undeclared third-party import.

## Handoff — what another stream must do

- **Spine / platform owner:** C2 contract test 6 is still skipped because it needs
  `sunil/settings.py`. When it lands, its `sunil_llm_gateway_base_url` validator must delegate to
  `sunil.providers.registry.validate_gateway_base_url` (do not re-implement the host rule — ADR-033
  wants exactly one closed set). The test activates by itself at that point.
- **Orchestrator owner:** C2 contract test 2's schema clause is skipped pending
  `sunil.core.orchestrator.plan_models`. Not Stream B's file.

## Progress

- [2026-09-11 | backend_engineer] Lanes, router, retries, catalogue, registry and `config/models.yaml`
  implemented with their unit suites; paused by the owner mid-way through rewriting the live 401
  probe. Committed as wip, explicitly not reviewed.
- [2026-09-12 | backend_engineer] Resumed. Merged `origin/V2` (docs only). Established ground truth
  before writing anything: suite was already green at 314 passed / 26 skipped and the live-probe
  rewrite turned out to be finished, not half-done. Ran the three live checks against the real
  LiteLLM (all pass). Found and fixed the undeclared-runtime-dependency defect test-first. Suite now
  326 passed / 26 skipped; yamllint clean; tripwire passing and non-vacuous.
