# C5 — Chat turn trigger: rationale and fake

**Version:** 1.0.0 · **Status:** FROZEN (Phase 0, 2026-09-10) · **Owner:** Solution Architect
**OpenAPI:** [`C5-chat-openapi.yaml`](C5-chat-openapi.yaml).
**Consumers:** Stream E (n8n triggers call it), Stream F (OpenHands task kickoff), the web app,
Stream D (renders parked outcomes), M2/M9 rebuilds (streaming + voice ride this endpoint).
**Informed by:** M1 `main:apps/api/sunil/api/schemas.py` + `routes/chat.py` (live-verified §6
envelope), ADR-020 (`input_modality`, server-verified), ADR-027 (NDJSON via `Accept`),
ADR-028 (only the analysis call streams), ADR-029 (disconnect = cancel).
**Related decisions:** ADR-031 (the `parked` outcome — the one deviation from M1's envelope),
ADR-035 (machine-caller lane).

---

## 1. What is kept from M1, verbatim

The rebuild keeps M1's proven decisions rather than re-litigating them:

- One endpoint, `POST /api/v1/chat`, for every turn — browser, voice (three requests sharing one
  `request_id`, ADR-020), and machine triggers. No second "trigger" endpoint to drift.
- `message` is `string(1..8000)`, 422 before any turn machinery runs; `additionalProperties: false`.
- The envelope fields `request_id, conversation_id, outcome, message, task, failure, trace, usage`
  with M1 semantics; `trace[].detail` carries enums and numbers only; `usage` sums every provider
  attempt including failures.
- Streaming by `Accept` negotiation with `stage | token | heartbeat | done` frames; the `done`
  frame carries the complete envelope; tokens are a projection (ADR-027, kept whole).
- The user's own message is persisted but never echoed back in the envelope.

## 2. What V2 adds (each argued in an ADR)

1. **`outcome: "parked"` + `approval` ref** (ADR-031). M1's `outcome` was `ok|failed` because M1
   had no write operations (FR-121). V2 has them, and ADR-005's in-request turn cannot block on a
   human for hours — so a turn that hits ASK_USER *ends*, honestly, with `outcome=parked` and the
   C4 approval reference. The exactly-one rule extends: `ok→message`, `failed→failure`,
   `parked→approval`; the other two of the three are null. No new frame type: a parked stream ends
   with the ordinary `done` frame whose envelope says `parked` (the twelve-stage spine does not
   grow — ADR-023's discipline).
2. **`input_modality` seam** (ADR-020 carried over as a requirement on the rebuilt gateway):
   additive, defaulted to `text`, server-verified. Until the voice milestone is rebuilt on V2,
   `voice` is always 422 — the field exists now so its presence is not a breaking change later.
3. **Service-token lane** (ADR-035): n8n triggers cannot hold a browser session. A static bearer
   token (`SUNIL_SERVICE_TOKEN`) authenticates machine callers **for this route only** —
   registered on this route's dependency, so the scope is structural: no token value grants
   approvals, memory or any other surface. `channel_label` records which workflow called.
   The cookie lane's CSRF pair (cookie + `X-SUNIL-Client` + Origin check) is unchanged for browsers.
4. **Failure kinds** gain `approval_refused` and `approval_expired` — the terminal outcomes of a
   parked approval arriving on the *continuation's* record (the original turn already returned
   `parked`; C4 §3).

## 3. Error semantics

| Code | When | Body kind |
|---|---|---|
| 401 | no session and no/invalid bearer | `unauthenticated` |
| 403 | cookie lane: `X-SUNIL-Client` ≠ `web`, or Origin ≠ `WEB_ORIGIN` | `forbidden_client` |
| 404 | `conversation_id` unknown | `not_found` |
| 422 | body shape, length bounds, unknown fields, unverifiable `voice` | `validation_error` |
| 200 + `outcome=failed` | turn machinery ran and failed (provider, tool, plan, project) | — |
| 200 + `outcome=parked` | ASK_USER parked (C4) | — |

Transport errors mid-stream: the connection drops without a `done` frame — clients treat missing
`done` as "turn state unknown, refetch the conversation"; the server treats client disconnect
before `done` as cancellation (ADR-029).

## 4. FAKE specification — `StubTurnExecutor` v2 (QA-buildable, no questions)

Module: `apps/api/tests/fakes/stub_turn_executor.py` — the rebuilt M1 pattern (endpoint real and
testable before the orchestrator exists), extended for the three outcomes. Deterministic, keyed on
the request `message`:

| `message` starts with | Behaviour (exact) |
|---|---|
| `PARK:` | `outcome="parked"`, `approval={approval_id: "apr-stub-1", expires_at: now+72h, summary: "fake_tool.write_item requires approval"}`, `task={id:"task-1", status:"parked", assigned_agent:"project_manager"}`, `message=null`, `failure=null` |
| `FAILP:` | `outcome="failed"`, `failure={kind:"provider_error"}`, `task=null` |
| `FAILT:` | `outcome="failed"`, `failure={kind:"tool_failed"}`, `task={id:"task-1", status:"failed", assigned_agent:"project_manager"}` |
| `REJECT:` | `outcome="failed"`, `failure={kind:"plan_rejected"}`, `task=null` |
| anything else | `outcome="ok"`, `message={id:"msg-1", role:"assistant", content:"STUB: "+message, created_at:<clock>}`, `task={id:"task-1", status:"completed", assigned_agent:"project_manager"}` |

Common to every response: `request_id` = ULID from the route; `conversation_id` = supplied or
`"conv-1"`; `usage={input_tokens:100, output_tokens:25, cost_usd:0.000125}`;
`trace` = exactly three entries `[{stage:"request_received",offset_ms:0},
{stage:"plan_created",offset_ms:10}, {stage:"final_response",offset_ms:20}]`.

Streaming fake: for `Accept: application/x-ndjson` the stub emits the three stage frames, then (ok
lane only) one `token` frame per whitespace-separated word of the content, then the `done` frame
with the identical envelope. No heartbeats (the stub is never silent for 15 s).

Contract tests (`apps/api/tests/contracts/test_c5_chat.py`):
1. JSON lane: each of the five message prefixes → exact envelope shape; the exactly-one rule holds
   in all five (assert the other two of message/failure/approval are null).
2. NDJSON lane: frames parse line-by-line; token concatenation equals
   `done.envelope.message.content` exactly (projection property — tokens carry a trailing space
   except the last, as in C2's `FakeProvider.stream`); exactly one `done`, and it is last.
3. `message` of length 0 and 8001 → 422; unknown body key → 422; `input_modality:"voice"` → 422.
4. cookie lane without `X-SUNIL-Client` → 403; with header but no session → 401.
5. bearer lane: valid `SUNIL_SERVICE_TOKEN` + no cookie → 200; same token on
   `GET /api/v1/approvals` → 401 (structural scope probe, ADR-035).
6. unknown `conversation_id` → 404.
