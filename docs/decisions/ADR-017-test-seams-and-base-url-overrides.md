# ADR-017 — Two test seams: a protocol-level fake for behaviour, and settings-driven base URLs for the adapters

**Status:** Accepted (Architect ruling, QA questions 1 and 2, 2026-08-14) · **Decider:** Solution Architect
**Context refs:** `ARCHITECTURE_V1.md` §4.3, §4.6, §9.3, §9.7, §14.4; `M1_BUILD_PLAN.md` §6.1, T6, T8, T18;
`THREAT_MODEL.md` T-24; FR-040, NFR-002.

## Context

QA built the T18 exit harness before any backend existed, and needed a way to make upstreams behave.
`M1_BUILD_PLAN.md` §6 froze only the browser↔SUNIL surface; §4.6 gestured at "a test that constructs
the router with a fake provider" without naming a constructor. Rather than guess at internals, QA
verified empirically that the pinned `anthropic==0.122.0` honours `ANTHROPIC_BASE_URL`, and drove the
whole suite through a local scripted HTTP double.

GitHub had no equivalent: `https://api.github.com` was hard-coded in prose. Fixture tests therefore
reached the **real** GitHub with a placeholder token, got a real 401, and surfaced `tool_failed` —
never a false pass, but never the test that was intended either.

## Decision

**Two seams, at two levels, with an explicit division of labour.**

### 1. `FakeProvider` — the protocol seam, for behaviour

`LLMProvider` is a Protocol precisely so the router, orchestrator and agents can be tested without
sockets. Backend engineers' own `tests/unit/` use it. It is fast, deterministic and has no ports.
It **cannot** test the Anthropic adapter, because it is what replaces the adapter.

### 2. Base URLs in `Settings` — the transport seam, for the adapters

| Setting | Env var | Default |
|---|---|---|
| `anthropic_base_url` | `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` |
| `github_api_base_url` | `GITHUB_API_BASE_URL` | `https://api.github.com` |

- **Both are passed explicitly** — `AsyncAnthropic(base_url=settings.anthropic_base_url, …)` and the
  GitHub adapter prefixing every path. Not left to the SDK's own environment reading.
- QA's harness is unchanged: pydantic-settings maps `anthropic_base_url` ↔ `ANTHROPIC_BASE_URL`, so
  setting the env var still drives it.

**Why explicit passing is a ruling and not a style preference.** Read from the installed SDK's
`_client.py` on 2026-08-14, base-URL precedence is **kwarg → `ANTHROPIC_BASE_URL` → credentials/
profile config → `https://api.anthropic.com`**. If T6 writes the natural
`base_url="https://api.anthropic.com"`, the kwarg wins and *every* exit test silently starts talking
to the real API with a real key — green tests, real spend, no signal. Passing the setting gives
identical production behaviour and cannot break the seam. It also removes a third surprise: a
`~/.anthropic` profile can inject a base URL when none is explicit.

### 3. The guard: non-canonical means loopback, or the app does not start

One validator on both fields. Value equals the canonical host → allowed. Host is `localhost`,
`127.0.0.0/8` or `::1` → allowed. Anything else → `ValidationError` at construction, so the
application refuses to boot.

This is not optional hardening. An env-settable API base is an exfiltration channel: redirect the
Anthropic URL and every prompt leaves; redirect the GitHub URL and the request carries
`Authorization: Bearer <PAT>` to the attacker's host — credential theft, not just disclosure. And
nothing in the audit trail would look wrong, because from SUNIL's side the call succeeded.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Leave `ANTHROPIC_BASE_URL` as an undocumented convention** | It works only while nobody passes `base_url=`, and the person most likely to pass it is the engineer writing the adapter this week. An unwritten seam is one refactor from a silent, expensive failure. |
| **Protocol-level `FakeProvider` only, no transport seam** | Then the Anthropic adapter — `output_config` wiring, usage parsing, `_request_id`, and the exception→`ProviderTransientError`/`Permanent` mapping that ET-8 is graded on — is never executed by a test. The fake would assert the fake. |
| **`respx` / `responses` HTTP mocking, or VCR cassettes** | A new dependency three days out (rule 3 of the build plan), and cassettes record a shape that then rots silently against the real API. A scripted local server driven by a base URL needs no library and is honest about being a double. |
| **Monkeypatching the module-level client in tests** | Reaches into internals, breaks the moment the provider is refactored, and gives QA a seam that only works from inside the same process — useless for the frontend-facing runs. |
| **`SUNIL_ENV=test` gating the override instead of the loopback rule** | Adds an environment concept whose only job is to be set correctly, and whose failure mode is a production instance quietly talking to an arbitrary host. The loopback rule cannot be forgotten because it is enforced by construction. |
| **Allowing any base URL and logging a warning** | A warning in a log nobody reads is not a control. |
| **No GitHub override at all** | Leaves fixture tests hitting the real API with a placeholder token — a test that passes for the wrong reason, which is worse than one that fails. |

## Consequences

- **V1 cannot use a forward proxy or an LLM gateway.** A real limitation, deliberately taken: nobody
  needs one today, and re-opening it is an ADR plus an explicit allow-list — which is the review that
  a new outbound destination deserves.
- `follow_redirects` stays `False` on the GitHub client, so a local double cannot bounce the PAT
  onward with a 302.
- Residual risk **T-24**: a hostile process on the owner's own machine could listen on loopback and
  harvest the PAT. That process can already read `.env`, so this adds no meaningful exposure.
- Neither value is a secret; both are logged at startup, which is how a wrong one becomes visible.
- Security test: `test_non_loopback_api_base_override_refuses_to_boot` (T19).
