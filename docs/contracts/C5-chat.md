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
   **Conversation scoping / blast radius (normative — Security review 2026-09-10 item 7):** the
   service lane is restricted to conversations it created. A bearer-lane request may omit
   `conversation_id` (a new conversation is created with `channel="service"`) or name a
   conversation whose `channel="service"`; naming a cookie-lane (owner) conversation returns 404 —
   the same shape as unknown, no existence oracle. A leaked `SUNIL_SERVICE_TOKEN` can therefore
   start new governed turns (whose writes still park via C4) and read/extend service-created
   conversations only; it cannot read owner conversation history or any history-derived output.
   The cookie lane is symmetric in shape only where it matters: the owner sees ALL conversations
   (single-owner system), including service-created ones.
4. **Failure kinds** gain `approval_refused`, `approval_expired` and `continuation_interrupted` —
   terminal outcomes arriving on the *continuation's* record, never on a live turn's envelope (the
   original turn already returned `parked`; C4 §3). `continuation_interrupted` is minted only by
   the startup reconciliation of a `consumed`-but-unfinalised approval (C4 §3 rule 3; Security
   review 2026-09-10 item 2).

## 3. Error semantics

| Code | When | Body kind |
|---|---|---|
| 401 | no session and no/invalid bearer | `unauthenticated` |
| 403 | cookie lane: `X-SUNIL-Client` ≠ `web`, or Origin ≠ `WEB_ORIGIN` | `forbidden_client` |
| 404 | `conversation_id` unknown — or, on the bearer lane, not service-created (§2.3) | `not_found` |
| 422 | body shape, length bounds, unknown fields, unverifiable `voice` | `validation_error` |
| 200 + `outcome=failed` | turn machinery ran and failed (provider, tool, plan, project) | — |
| 200 + `outcome=parked` | ASK_USER parked (C4) | — |

Transport errors mid-stream: the connection drops without a `done` frame — clients treat missing
`done` as "turn state unknown, refetch the conversation"; the server treats client disconnect
before `done` as cancellation (ADR-029).

**Credential log redaction (normative — Security review 2026-09-10 item 5):** the values of inbound
`Authorization` and `Cookie` headers are NEVER written to logs, trace details, audit rows or error
messages — on any lane, for valid and invalid credentials alike (an invalid bearer is exactly the
value most worth not logging). Defence-in-depth: the configured `SUNIL_SERVICE_TOKEN` and
`SESSION_SECRET` values are registered with the ADR-006 redaction registry at startup, but the
load-bearing rule is the structural one above — header values are not inputs to any logging call.

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
| `NOPROJ:` | `outcome="failed"`, `failure={kind:"unknown_project", known_projects:[{key:"sunil", display_name:"SUNIL"}]}`, `task=null` (fix round 2026-09-10, QA should-fix: this kind previously had no fake behaviour and no test) |
| anything else | `outcome="ok"`, `message={id:"msg-1", role:"assistant", content:"STUB: "+message, created_at:<clock>}`, `task={id:"task-1", status:"completed", assigned_agent:"project_manager"}` |

Common to every response: `request_id` = ULID from the route; `conversation_id` = supplied or
lane-created (below); `usage={input_tokens:100, output_tokens:25, cost_usd:0.000125}`;
`trace` = exactly three entries `[{stage:"request_received",offset_ms:0},
{stage:"plan_created",offset_ms:10}, {stage:"final_response",offset_ms:20}]`.

Route-level fixture — `FakeConversationStore` (same module): the C5 suite runs against the REAL
route (auth deps + validation + envelope builder) with the stub behind it, so conversation
existence and lane scoping are route concerns the harness must fake. Seeded rows:
`conv-1 (channel="web")`, `conv-svc-1 (channel="service")`. Rules: unknown id → 404; bearer lane +
`channel="web"` id → 404 (§2.3 scoping); omitted id → create `conv-2` on the cookie lane /
`conv-svc-2` on the bearer lane, with the lane's channel.

Streaming fake: for `Accept: application/x-ndjson` the stub emits the three stage frames, then (ok
lane only) one `token` frame per element of the **C2 §5 partition** of the content
(`re.findall(r"\S+\s*|\s+", content)` — each maximal non-whitespace run plus its trailing
whitespace; a leading whitespace run is its own token), then the `done` frame with the identical
envelope. No heartbeats (the stub is never silent for 15 s).

Contract tests (`apps/api/tests/contracts/test_c5_chat.py`):
1. JSON lane: each of the six message prefixes → exact envelope shape; the exactly-one rule holds
   in all six (assert the other two of message/failure/approval are null); `known_projects` is
   non-null exactly in the `NOPROJ:` case.
2. NDJSON lane: frames parse line-by-line; token concatenation equals
   `done.envelope.message.content` **byte-for-byte**, asserted on a message containing a double
   space and a newline (the C2 §5 partition property); exactly one `done`, and it is last.
3. `message` of length 0 and 8001 → 422; unknown body key → 422; `input_modality:"voice"` → 422.
4. cookie lane without `X-SUNIL-Client` → 403; with header but no session → 401.
5. bearer lane: valid `SUNIL_SERVICE_TOKEN` + no cookie → 200; same token on
   `GET /api/v1/approvals` → 401 (structural scope probe, ADR-035).
6. unknown `conversation_id` → 404.
7. redaction (Security review 2026-09-10 item 5): with a log/trace capture attached, one request
   per lane with a VALID credential and one with an INVALID credential — assert the captured
   output contains neither the bearer value nor the cookie value (literal substring probe against
   everything captured, including the 401 bodies).
8. route-table scope (Security review 2026-09-10 item 6, build-time): iterate `app.routes` and
   assert the bearer dependency (`require_service_token`, by function identity — not name string)
   is registered on exactly one route: `POST /api/v1/chat`. A dependency slipped onto a router
   would fail this without any request being made.
9. bearer lane naming `conv-1` (a `channel="web"` conversation) → 404; naming `conv-svc-1` → 200;
   omitting `conversation_id` → 200 with a NEW service-channel conversation (§2.3 blast-radius
   rule).

## Changelog

- **v1.0.0 — 2026-09-10 fix round** (pre-merge; version unchanged because the freeze was never
  merged). Service-lane conversation scoping + blast-radius statement, with `FakeConversationStore`
  fixture and test 9 (Security item 7). Inbound `Authorization`/`Cookie` log-redaction rule + test
  7 (Security item 5). Route-table-wide bearer-scope test 8 (Security item 6). Failure kind
  `continuation_interrupted` added, reconciliation-only (Security item 2; also in the OpenAPI).
  `unknown_project` fake behaviour (`NOPROJ:`) + coverage in test 1 (QA should-fix). Streaming
  fake/test re-specified on the C2 §5 whitespace-preserving partition (QA should-fix). OpenAPI:
  `HeartbeatFrame`'s stray `description` **property** removed — it was a mis-indented schema
  description (QA should-fix).
