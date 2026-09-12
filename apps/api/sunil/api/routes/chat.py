"""`POST /api/v1/chat` — the single turn trigger (C5).

One endpoint for every turn: browser, machine trigger (ADR-035) and, later, voice
(ADR-020's three requests sharing one `request_id`). There is deliberately no
second "trigger" endpoint to drift from this one.

Order of operations, and why it is this order:

1. **Authentication** (`authenticate_chat_caller`) — before anything reads the
   body, so an unauthenticated caller cannot exercise the validator.
2. **Body validation** — `ChatRequest`'s bounds are a 422 before any turn
   machinery runs (M1's rule).
3. **Conversation resolution** — a 404 for an unknown *or out-of-lane* id, which
   is an authorisation answer and must not wait for the orchestrator.
4. **The turn**, through the injected `TurnExecutor` seam.
5. **The envelope**, in one of two representations.

**Streaming is a projection, not a second truth** (ADR-027). The NDJSON lane
replays the completed turn's stages, then one `token` frame per element of C2
§5's partition of the answer, then exactly one `done` frame carrying the same
envelope a JSON client would have received. A client reading only `done` behaves
identically to a JSON client, and a dropped token frame cannot corrupt the
answer.

**Deferred, recorded:** true incremental streaming of the analysis call (ADR-028
— only that call streams) is M2 work. Until then the response is produced first
and projected second, so `Accept: application/x-ndjson` is honest about frame
CONTENT and not yet about frame TIMING.
"""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from sunil.api.deps import CallerIdentity, authenticate_chat_caller
from sunil.api.envelope import build_envelope
from sunil.api.errors import ApiError
from sunil.api.schemas import ChatRequest, ChatResponse, DoneFrame, StageFrame, TokenFrame
from sunil.core.conversations.gateway import ConversationNotFound
from sunil.db.base import new_uuid

router = APIRouter(tags=["chat"])

NDJSON_MEDIA_TYPE = "application/x-ndjson"

#: C2 §5's partition, reused verbatim so the two contracts cannot drift.
_PARTITION = re.compile(r"\S+\s*|\s+")


@router.post("/api/v1/chat")
async def chat_turn(
    request: Request,
    body: ChatRequest,
    caller: CallerIdentity = Depends(authenticate_chat_caller),
) -> Any:
    state = request.app.state

    try:
        conversation = await state.conversation_resolver.resolve(
            lane=caller.lane,
            conversation_id=body.conversation_id,
            user_id=caller.user_id,
            channel_label=_channel_label(caller, body),
        )
    except ConversationNotFound as exc:
        # The same shape for "unknown" and "not yours" — no existence oracle
        # (C5 §2.3, Security review item 7).
        raise ApiError(404, "not_found", "conversation not found") from exc

    result = await state.turn_executor.run(
        message=body.message,
        conversation=conversation,
        request_id=new_uuid(),
        lane=caller.lane,
        user_id=caller.user_id,
        channel_label=_channel_label(caller, body),
    )
    envelope = build_envelope(result)
    # The access record. Ids, a lane and an outcome — never the message, never a
    # header value (C5 §3).
    state.logger.info(
        "chat_turn",
        request_id=envelope.request_id,
        conversation_id=envelope.conversation_id,
        lane=caller.lane,
        outcome=envelope.outcome,
    )

    if _wants_ndjson(request):
        return StreamingResponse(
            _project(envelope), media_type=NDJSON_MEDIA_TYPE, status_code=200
        )
    return JSONResponse(status_code=200, content=envelope.model_dump(mode="json"))


def _channel_label(caller: CallerIdentity, body: ChatRequest) -> str | None:
    """ADR-035: the label records WHICH workflow called. On the cookie lane it is
    ignored — a browser cannot be allowed to label its own turns as a service
    workflow, because that label is what an audit reader trusts."""
    if caller.lane != "bearer":
        return None
    return body.channel_label or caller.channel_label


def _wants_ndjson(request: Request) -> bool:
    """C5 OpenAPI: any Accept other than `application/x-ndjson` is served JSON."""
    return NDJSON_MEDIA_TYPE in request.headers.get("Accept", "")


async def _project(envelope: ChatResponse) -> AsyncIterator[bytes]:
    for entry in envelope.trace:
        yield _line(StageFrame(stage=entry.stage, offset_ms=entry.offset_ms))
    if envelope.message is not None:
        for token in _PARTITION.findall(envelope.message.content):
            yield _line(TokenFrame(token=token))
    yield _line(DoneFrame(envelope=envelope))


def _line(frame: Any) -> bytes:
    return (json.dumps(frame.model_dump(mode="json"), separators=(",", ":")) + "\n").encode()
