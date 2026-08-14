"""Constants copied verbatim from the frozen §6 contract (docs/M1_BUILD_PLAN.md §6) and
NFR-020 (docs/REQUIREMENTS_V1.md). Changing any of these is an Architect escalation per
the build plan's own rule 2 -- so tests assert against this one shared copy, never
against a value re-typed independently in each test file.
"""

from __future__ import annotations

# The twelve NFR-020 stages, in their canonical order. "Each appears at most once per
# turn" (§6) -- ET-6 grades both presence AND uniqueness against this exact list.
TRACE_STAGES: tuple[str, ...] = (
    "message_received",
    "context_loaded",
    "memory_retrieved",
    "model_selected",
    "llm_io",
    "plan_created",
    "agent_started",
    "tool_requested",
    "permission_decision",
    "tool_result",
    "agent_result",
    "final_response",
)

# failure.kind ∈ this set (§6). The turn-deadline breach maps to provider_error --
# "no new kind, no new copy".
FAILURE_KINDS: tuple[str, ...] = (
    "provider_error",
    "tool_failed",
    "plan_rejected",
    "unknown_project",
)

# M1 writes llm_calls.purpose ∈ {plan, analysis} only (ADR-015, A-4). `final_response`
# is in the enum but no M1 code path writes it -- an assertion finding it would be a
# real defect, not a test bug.
M1_LLM_PURPOSES: tuple[str, ...] = ("plan", "analysis")
NEVER_WRITTEN_IN_M1_PURPOSE = "final_response"
