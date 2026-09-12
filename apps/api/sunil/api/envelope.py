"""`TurnResult` → the C5 envelope. One mapping, in the layer that owns the wire.

The orchestrator speaks `core.orchestrator.result.TurnResult` (the import law:
`core/` never imports `sunil.api`), so this is where a turn becomes the frozen
contract shape — and where the exactly-one rule is enforced a second time, by
`ChatResponse`'s own validator, on the way out.
"""

from __future__ import annotations

from sunil.api.schemas import (
    ApprovalRef,
    ChatFailure,
    ChatResponse,
    ChatTaskOut,
    ChatUsage,
    MessageOut,
    ProjectSummary,
    TraceEntryOut,
)
from sunil.core.orchestrator.result import TurnResult


def build_envelope(result: TurnResult) -> ChatResponse:
    """Map a finished turn onto `C5-chat-openapi.yaml`'s `ChatResponse`."""
    return ChatResponse(
        request_id=result.request_id,
        conversation_id=result.conversation_id,
        outcome=result.outcome,
        message=(
            MessageOut(
                id=result.message.id,
                content=result.message.content,
                created_at=result.message.created_at,
            )
            if result.message is not None
            else None
        ),
        task=(
            ChatTaskOut(
                id=result.task.id,
                status=result.task.status,
                assigned_agent=result.task.assigned_agent,
            )
            if result.task is not None
            else None
        ),
        failure=(
            ChatFailure(
                kind=result.failure.kind,
                known_projects=(
                    [
                        ProjectSummary(key=key, display_name=name)
                        for key, name in result.failure.known_projects
                    ]
                    if result.failure.known_projects is not None
                    else None
                ),
            )
            if result.failure is not None
            else None
        ),
        approval=(
            ApprovalRef(
                approval_id=result.approval.approval_id,
                expires_at=result.approval.expires_at,
                summary=result.approval.summary,
            )
            if result.approval is not None
            else None
        ),
        trace=[
            TraceEntryOut(stage=entry.stage, offset_ms=entry.offset_ms, detail=entry.detail)
            for entry in result.trace
        ],
        usage=ChatUsage(
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cost_usd=result.usage.cost_usd,
        ),
    )
