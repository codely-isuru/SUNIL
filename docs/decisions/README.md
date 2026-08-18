# Architecture Decision Records

One decision per file. **Every ADR names its rejected alternatives — an ADR without a rejected
alternative is not an ADR.** A decision that changes an earlier decision is recorded as a *new* ADR
that supersedes it, or — where the decision survives and only part of it moves — as a dated
**amendment appended to the original**, never as a silent edit.

| ADR | Decision | Status |
|---|---|---|
| [000](ADR-000-gate-1-scope-decisions.md) | The seven Gate 1 scope decisions (owner) — settled, not reopened | Accepted 2026-08-14 |
| [001](ADR-001-database.md) | PostgreSQL is the V1 target; **SQLite is the M1 default**; one portable schema | **Accepted** (owner review 2026-08-14) |
| [002](ADR-002-orm-and-migrations.md) | SQLAlchemy 2.0 async + Alembic | **Accepted** (owner review 2026-08-14) |
| [003](ADR-003-provider-abstraction.md) | SUNIL owns the provider abstraction: `LLMProvider` protocol + capability-keyed Model Router | **Accepted** (owner review 2026-08-14) |
| [004](ADR-004-plan-validation.md) | Plan validation: constrained decoding → Pydantic → registry re-check → `ValidatedPlan` + **runtime guard** | **Accepted, amended once** (Amendment 1, 2026-08-14) |
| [005](ADR-005-m1-execution-model.md) | M1 runs the turn in-request: **no queue, no worker, no Redis** | **Accepted** (owner review 2026-08-14) |
| [006](ADR-006-secret-storage.md) | Secrets: env/`.env` as `SecretStr` + a value-registry redaction mechanism | **Accepted** (owner review 2026-08-14) |
| [007](ADR-007-authentication.md) | Single-owner auth: signed-cookie session + stdlib `scrypt` | **Accepted** (owner review 2026-08-14) |
| [008](ADR-008-frontend-api-topology.md) | Browser → FastAPI direct, cross-origin, strict CORS + mandatory client header | **Accepted** (owner review 2026-08-14) |
| [009](ADR-009-progress-events-channel.md) | M1 ships a real one-way **SSE stage-event channel** | **Accepted, amended** — T12 pre-classified **OPTIONAL / post-M1** |
| [010](ADR-010-cancel-semantics.md) | Cancel is **client-side only** in M1; the abort seam exists, unwired | **Accepted** (owner review 2026-08-14) |
| [011](ADR-011-repository-structure.md) | One installable `sunil` package under `apps/api`; `core/routing`, `core/agent_framework`, `core/tool_framework` | **Accepted** (owner review 2026-08-14, §2.2 renames explicitly approved) |
| [012](ADR-012-frontend-stack.md) | Next.js 16 + React 19 + Tailwind **pinned to 3.4.19**, pure client app | **Accepted** (owner review 2026-08-14) |
| [013](ADR-013-pgvector-deferred-to-m7.md) | No vector column and no pgvector in M1 | **Accepted** (owner review 2026-08-14) |
| [014](ADR-014-training-data-capture-policy.md) | **Training-data capture policy** — classify at capture time; `none / metadata_only / redacted_full / full_local_only` | **Accepted** (owner correction §10) |
| [015](ADR-015-m1-two-logical-llm-stages.md) | **M1 has two logical LLM stages**; the PM agent's analysis is the user-facing response | **Accepted** (owner correction §11) |
| [016](ADR-016-config-deployment-policy.md) | `config/*.yaml` is **mounted, never baked**; a change takes effect on restart | Proposed |
| [017](ADR-017-test-seams-and-base-url-overrides.md) | Two test seams: `FakeProvider` for behaviour, **settings-driven base URLs** for the adapters; non-canonical must be loopback | **Accepted** (Architect ruling, 2026-08-14) |
| [018](ADR-018-application-and-settings-lifecycle.md) | Settings/engine/clients are **per-application state**; `create_app(settings=None)`, `uvicorn --factory` | **Accepted** (Architect ruling, 2026-08-14) |
| [019](ADR-019-speech-adapters-are-not-the-model-router.md) | **STT/TTS live in `sunil/speech/`**, not the Model Router: own protocol, registry, `config/speech.yaml`, `speech_calls` table | Proposed (M9, 2026-08-19) |
| [020](ADR-020-voice-turn-reuses-the-chat-endpoint.md) | A voice turn is **three requests sharing one `request_id`**; `POST /api/v1/chat` is reused with one added, server-**verified** `input_modality` field | Proposed (M9, 2026-08-19) |
| [021](ADR-021-voice-capture-policy.md) | **Captured audio is discarded by default**; the transcript is the only survivor; `speech_call` is a new table-keyed `CaptureKind` defaulting to `metadata_only` | Proposed (M9, 2026-08-19) |
| [022](ADR-022-microphone-egress-guard.md) | **The egress guard extends to audio**: ADR-017's validator reused unchanged, plus an interlock — a loopback speech endpoint is a *separate* consent | Proposed (M9, 2026-08-19) |
| [023](ADR-023-twelve-trace-stages-unchanged-for-voice.md) | **The twelve trace stages are unchanged by voice.** `speech_calls` is a sibling record like `llm_calls`/`tool_calls`, not a stage; ET-6 is untouched | Proposed (M9, 2026-08-19) |
| [024](ADR-024-m9-latency-posture.md) | **M9 removes the silence, not the wait**: earcon + transcript + streamed TTS. Sentence-level pipelining needs M2's token streaming and is not promised | Proposed (M9, 2026-08-19) |
| [025](ADR-025-raw-body-audio-ingress.md) | Audio uploads as a **raw request body** (no `python-multipart`, no new dependency); the spoken answer is a **GET** guarded by `SameSite=Lax` + ownership | Proposed (M9, 2026-08-19) |

ADR-017 and ADR-018 answer questions raised by QA against the running build, not by a review. They
are Architect rulings issued mid-flight because T5, T6 and T8 were still open and the cost of ruling
late is rework.

**ADR-019 … ADR-025 are M9 (voice).** They are `Proposed`, not `Accepted`: they are the Architect's
design, awaiting the owner's review, and `docs/M9_BUILD_PLAN.md` §8 lists the four questions that are
his and not an engineer's. Their companion document is
[`docs/ARCHITECTURE_M9_VOICE.md`](../ARCHITECTURE_M9_VOICE.md), and the threat model additions are
`THREAT_MODEL.md` §12. **ADR-022 extends ADR-017 without amending it** — ADR-017's rule is unchanged and
still correct; what ADR-022 adds is that its loopback *exception* was argued on a fact about prompts
that does not hold for microphone audio.

ADR-001 … ADR-018 are the Solution Architect's. **ADR-001 … ADR-013 were approved by the owner's
architecture review on 2026-08-14** ("approve the architecture direction after targeted
corrections"); the corrections are recorded as ADR-004 Amendment 1, the ADR-009 amendment, and the
new ADR-014/015/016. ADR-001, ADR-005 and ADR-013 are the three that together keep Docker off M1's
critical path — still true now that the daemon is running, which makes the no-Docker path a
contingency rather than a constraint.

**Amendment index** — where a decision moved after it was first written:

| Record | Amendment | Date |
|---|---|---|
| ADR-004 | Amendment 1 — "unforgeable"/"no expressible code path" withdrawn; runtime guard + `ExecutionMetadata` added; stored-plan check deferred to M5 as DC-14 | 2026-08-14 |
| ADR-005 | Context line re-stated: two logical LLM stages, 7.5–17.5 s nominal | 2026-08-14 |
| ADR-009 | T12 pre-classified OPTIONAL / post-M1; `SUNIL_PROGRESS_EVENTS` defaults `false` | 2026-08-14 |
| `ARCHITECTURE_V1.md` | Amendment log A-1 … A-14 at the head of the document | 2026-08-14 |
