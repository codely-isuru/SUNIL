"""The ONE module that knows OpenHands' HTTP shape.

These tests pin the vendor mapping so that correcting it after the first live
boot is a one-line change with a failing test to guide it — which is the whole
point of keeping the mapping in a single module (ADR-030: "every integrated
component is a replaceable vendor behind a SUNIL-owned seam").

They are honest about what they prove: that OUR adapter reads the shape it says
it reads, and that every deviation from that shape fails closed. They do NOT
prove the shape is OpenHands' — nothing offline can, and
``openhands_http.VENDOR_MAPPING_STATUS`` says so in the code.
"""

from __future__ import annotations

import json

import httpx
import pytest

from sunil.agents.developer.client import EngineError, EngineErrorKind, RunState, TaskSpec
from sunil.agents.developer.openhands_http import (
    MAX_GIT_INTENTS,
    VENDOR_MAPPING_STATUS,
    OpenHandsHttpClient,
)

pytestmark = pytest.mark.asyncio

SPEC = TaskSpec(
    project_key="sunil",
    instructions="fix the failing test",
    base_branch="main",
    branch_prefix="sunil/",
    timeout_s=900.0,
)
REPOS = {"sunil": "codely-isuru/SUNIL"}


def client(handler) -> OpenHandsHttpClient:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://openhands:3000"
    )
    return OpenHandsHttpClient(http, repositories=REPOS)


def report_body(payload: dict, *, status: str = "STOPPED") -> dict:
    return {
        "status": status,
        "final_message": "Done.\n\n```json\n" + json.dumps(payload) + "\n```",
    }


# --------------------------------------------------------------------------- #
# submit
# --------------------------------------------------------------------------- #
async def test_submit_posts_the_work_order_and_returns_the_engine_run_id():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"conversation_id": "conv-abc"})

    run_id = await client(handler).submit(SPEC)

    assert run_id == "conv-abc"
    assert seen["url"] == "http://openhands:3000/api/conversations"
    # The repository is resolved from the project registry, never carried in the
    # spec — a plan cannot name a repository.
    assert seen["body"]["repository"] == "codely-isuru/SUNIL"
    assert seen["body"]["selected_branch"] == "main"
    assert seen["body"]["initial_user_msg"] == "fix the failing test"
    # No credential is sent by this layer: the transport carries auth, the
    # sandbox holds its own git token (see the module docstring).
    assert not any("token" in key.lower() for key in seen["body"])


async def test_an_unknown_project_key_never_reaches_the_engine():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("the request must not have been made")

    with pytest.raises(EngineError) as exc:
        await client(handler).submit(
            TaskSpec(
                project_key="not-a-project",
                instructions="x",
                base_branch="main",
                branch_prefix="sunil/",
                timeout_s=1.0,
            )
        )
    assert exc.value.kind is EngineErrorKind.INVALID_PARAMS


async def test_a_submit_response_without_a_run_id_is_an_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "wrong-field"})

    with pytest.raises(EngineError) as exc:
        await client(handler).submit(SPEC)
    assert exc.value.kind is EngineErrorKind.UPSTREAM_ERROR


async def test_an_unreachable_engine_is_a_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(EngineError) as exc:
        await client(handler).submit(SPEC)
    assert exc.value.kind is EngineErrorKind.TRANSPORT_ERROR


async def test_a_server_error_is_an_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with pytest.raises(EngineError) as exc:
        await client(handler).submit(SPEC)
    assert exc.value.kind is EngineErrorKind.UPSTREAM_ERROR


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("vendor", "expected"),
    [
        ("STARTING", RunState.QUEUED),
        ("RUNNING", RunState.RUNNING),
        ("STOPPED", RunState.SUCCEEDED),
        ("ERROR", RunState.FAILED),
    ],
)
async def test_the_vendor_lifecycle_maps_onto_our_four_states(vendor, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/api/conversations/conv-abc")
        return httpx.Response(200, json={"status": vendor})

    assert await client(handler).status("conv-abc") == expected


async def test_an_unmapped_vendor_state_fails_rather_than_being_guessed():
    """A state we have never seen must not be read as "finished": the agent
    would then fetch a report for a run still writing to the branch."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "PAUSED_FOR_CONFIRMATION"})

    with pytest.raises(EngineError) as exc:
        await client(handler).status("conv-abc")
    assert exc.value.kind is EngineErrorKind.UPSTREAM_ERROR
    assert "PAUSED_FOR_CONFIRMATION" in exc.value.message


# --------------------------------------------------------------------------- #
# result — parsing OUR reporting contract out of the engine's final message
# --------------------------------------------------------------------------- #
async def test_the_report_block_becomes_a_run_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=report_body(
                {
                    "branch": "sunil/fix-thing",
                    "summary": "fixed it",
                    "git_intents": [
                        {"operation": "push_branch"},
                        {"operation": "merge_main", "branch": "sunil/fix-thing"},
                    ],
                }
            ),
        )

    result = await client(handler).result("conv-abc")

    assert result.run_id == "conv-abc"
    assert result.state is RunState.SUCCEEDED
    assert result.branch == "sunil/fix-thing"
    assert result.summary == "fixed it"
    assert [intent.operation for intent in result.git_intents] == [
        "push_branch",
        "merge_main",
    ]
    assert result.git_intents[1].branch == "sunil/fix-thing"


async def test_a_report_that_cannot_be_parsed_is_a_failed_run_not_an_exception():
    """A run that reported unusably ran, and the honest outcome is a failed run:
    the agent then performs no git operation. Raising would have been a lie
    about the engine being unreachable."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "STOPPED", "final_message": "all done!"})

    result = await client(handler).result("conv-abc")

    assert result.state is RunState.FAILED
    assert result.failure_kind == "unparsable_report"
    assert result.git_intents == ()


async def test_a_failed_run_keeps_the_engines_own_failure_word():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "ERROR", "last_error": "AgentStuckInLoopError"}
        )

    result = await client(handler).result("conv-abc")

    assert result.state is RunState.FAILED
    assert result.failure_kind == "AgentStuckInLoopError"


async def test_an_engine_cannot_request_an_unbounded_number_of_git_writes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=report_body(
                {
                    "branch": "sunil/x",
                    "git_intents": [{"operation": "push_branch"}] * (MAX_GIT_INTENTS + 5),
                }
            ),
        )

    result = await client(handler).result("conv-abc")
    assert len(result.git_intents) == MAX_GIT_INTENTS


async def test_a_report_whose_intents_are_not_objects_is_unparsable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=report_body({"branch": "sunil/x", "git_intents": "push_branch"})
        )

    result = await client(handler).result("conv-abc")
    assert result.state is RunState.FAILED
    assert result.failure_kind == "unparsable_report"


async def test_the_vendor_mapping_declares_itself_unverified():
    """Named in code, not only in a comment, so the DM's "is this live-ready?"
    question has a machine-readable answer."""
    assert VENDOR_MAPPING_STATUS == "unverified-until-first-live-boot"
