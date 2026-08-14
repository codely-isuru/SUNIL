"""The twelve NFR-020 trace stage names.

These are the frozen §6 contract's `stage` enum, the twelve stage names of
`ARCHITECTURE_V1.md` §3.4, and the ordering ET-6 is graded against. Every
downstream lane (T4's emitter, T5/T11a/T11b's stage emissions, T16's phase
map, QA's ET-6 assertions) imports this module. Changing a member's name,
value or position is a frozen-contract change and requires an Architect
ruling (`docs/M1_BUILD_PLAN.md` §0.2 rule 2, §6).

**Each stage is emitted at most once per turn.** Retries — provider
attempts and whole re-planning attempts alike — are recorded in a stage's
`detail` (`detail.provider_attempts`, `detail.plan_attempts`), never as an
extra stage event.
"""

from __future__ import annotations

from enum import StrEnum


class TraceStage(StrEnum):
    """One member per turn stage, in pipeline order (ARCHITECTURE_V1.md §3.4)."""

    MESSAGE_RECEIVED = "message_received"
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


# The canonical pipeline order, derived from declaration order rather than
# restated by hand — so this tuple can never drift out of sync with the
# enum itself. QA's ET-6 "all twelve, in order, from logs alone" assertion
# is checked against this.
ALL_STAGES_IN_ORDER: tuple[TraceStage, ...] = tuple(TraceStage)
