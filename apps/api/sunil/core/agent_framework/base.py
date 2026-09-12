"""What an agent is handed, and what it may hand back.

An agent is a **role** (§33.4): it receives a validated plan and a context of
seams, and it returns a result. It is deliberately given no ability to widen its
own authority —

* it never sees `Settings`, a credential or a base URL (transport is the
  provider's business);
* it reaches tools only through the injected C1 Tool Manager, which is the single
  chokepoint;
* it cannot mint a `ValidatedPlan`, and the plan it receives went through
  `require_validated_plan` at the orchestrator's door.

`UsageTally` lives here because both the agent's analysis call and the
orchestrator's plan call must add to the SAME total: C5's `usage` is summed
across every provider attempt including failed ones (M1's A-2 rule), and two
separate counters would quietly drop whichever side failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sunil.core.trace.context import TraceContext


@dataclass
class UsageTally:
    """Every provider attempt lands here — successes and failures alike."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    attempts: int = 0

    def add(self, usage: Any | None) -> None:
        """`usage` is a C2 `Usage` or `None` (a failure the provider could not
        price). The attempt is counted either way: "we called and it failed" is
        the fact the tally exists to keep."""
        self.attempts += 1
        if usage is None:
            return
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cost_usd += usage.cost_usd


@dataclass(frozen=True)
class AgentContext:
    """The seams and correlation ids one agent run needs."""

    agent_id: str
    request_id: str
    task_id: str
    conversation_id: str
    model: str
    privacy_class: str
    system_prompt: str
    user_message: str
    history: list[tuple[str, str]]  # (role, content), oldest first
    memory_items: list[dict[str, Any]]
    trace: TraceContext
    tool_manager: Any  # C1 ToolManagerProtocol
    #: The same `AuditHook` instance the Tool Manager was constructed with. The
    #: agent reads (never writes) its attempt records, so the
    #: `permission_decision` stage reports what the audit row says rather than a
    #: value the agent inferred.
    audit_hook: Any
    provider: Any  # C2 LLMProvider
    usage: UsageTally
    record_llm_call: Any  # async callable persisting one `llm_calls` row
    max_tokens: int = 1024


@dataclass
class AgentResult:
    """The honest outcomes of one agent run, mapped 1:1 to a C5 outcome."""

    kind: Literal["ok", "parked", "tool_failed", "provider_error"]
    content: str | None = None
    approval_id: str | None = None
    approval_expires_at: str | None = None
    approval_summary: str | None = None
    tool_calls: int = 0
    permission_decision: str | None = None
    tool_error_kind: str | None = None
    provider_error_kind: str | None = None
    steps_executed: int = 0
    tool_details: list[dict[str, Any]] = field(default_factory=list)


class Agent(Protocol):
    """Every agent implements exactly this."""

    id: str

    async def run(self, plan: object, ctx: AgentContext) -> AgentResult: ...
