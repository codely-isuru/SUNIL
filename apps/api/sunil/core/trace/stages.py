"""The twelve trace stage names — the spine of everything SUNIL claims about
itself (ROADMAP §28 / NFR-020; ADR-023).

`SELECT stage, seq FROM audit_events WHERE request_id = :rid ORDER BY seq` must
return these stages, in this order, for a turn to be reconstructable from stored
records alone. Every emitting lane imports this module; changing a member's
name, value or position is a frozen-contract change and needs an Architect
ruling.

**Each stage is emitted at most once per turn.** Retries — provider attempts and
whole re-planning attempts alike — are recorded in a stage's `detail`
(`detail.provider_attempts`, `detail.plan_attempts`), never as an extra stage
event. `LiveTraceContext.emit()` enforces that structurally.

**`llm_calls`, `tool_calls` and `approvals` are NOT stages** (ADR-023's
structural observation): they are sibling records that stages point at, joined
by `request_id`. That is why an ASK_USER park adds no thirteenth stage — the
approval is a sibling row and the turn still ends at `final_response`, with
`outcome="parked"` (ADR-031, C5 §2.1).

**Deviation from M1, recorded (Architect sign-off wanted, nothing blocked):**
stage 1 is `request_received`, where M1's enum said `message_received`. Both V2
sources name it `request_received` — `ARCHITECTURE_V2.md` §6's audit chain
("`request_received … plan_created`") and C5 §4's frozen fake trace, which a
contract test asserts byte-for-byte on the wire. ADR-023's actual rule is that
the SET of twelve does not grow; it does not survive here as a spelling.
"""

from __future__ import annotations

from enum import StrEnum


class TraceStage(StrEnum):
    """One member per turn stage, in pipeline order."""

    REQUEST_RECEIVED = "request_received"
    CONTEXT_LOADED = "context_loaded"
    MEMORY_RETRIEVED = "memory_retrieved"
    MODEL_SELECTED = "model_selected"
    LLM_IO = "llm_io"
    PLAN_CREATED = "plan_created"
    AGENT_STARTED = "agent_started"
    TOOL_REQUESTED = "tool_requested"
    PERMISSION_DECISION = "permission_decision"
    TOOL_RESULT = "tool_result"
    AGENT_RESULT = "agent_result"
    FINAL_RESPONSE = "final_response"


#: The canonical pipeline order, DERIVED from declaration order rather than
#: restated by hand — so it can never drift out of sync with the enum itself.
ALL_STAGES_IN_ORDER: tuple[TraceStage, ...] = tuple(TraceStage)
