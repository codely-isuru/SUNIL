"""OpenAPI contract tests — the two frozen YAML surfaces.

Sources of truth: ``docs/contracts/C4-approvals-openapi.yaml`` and
``docs/contracts/C5-chat-openapi.yaml`` (both v1.0.0, FROZEN 2026-09-10).

These tests guard the machine-readable half of the contracts: both documents
parse, every local ``$ref`` resolves, the enums agree with each other and with
the Python transcription, and the specific defects the 2026-09-10 fix round
closed stay closed (``HeartbeatFrame``'s stray ``description`` property; the
deliberate absence of ``POST /api/v1/approvals``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sunil.core.approvals.base import ApprovalStatus

pytestmark = pytest.mark.contract


def contracts_dir() -> Path:
    """Locate ``docs/contracts`` by walking up from this file.

    Robust to the depth of ``apps/api/tests/contracts`` changing; fails loudly
    rather than silently testing nothing.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "docs" / "contracts"
        if candidate.is_dir():
            return candidate
    raise AssertionError("docs/contracts not found above this test file")


CONTRACTS = contracts_dir()
C4_YAML = CONTRACTS / "C4-approvals-openapi.yaml"
C5_YAML = CONTRACTS / "C5-chat-openapi.yaml"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def c4() -> dict:
    return load(C4_YAML)


@pytest.fixture(scope="module")
def c5() -> dict:
    return load(C5_YAML)


def iter_refs(node, trail: str = "$"):
    """Yield ``(json_path, ref)`` for every ``$ref`` in the document."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield trail, value
            else:
                yield from iter_refs(value, f"{trail}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from iter_refs(value, f"{trail}[{index}]")


def resolve(document: dict, ref: str):
    """Resolve a local JSON pointer (``#/a/b``); raise KeyError if it dangles."""
    assert ref.startswith("#/"), f"only local refs are expected, got {ref}"
    target = document
    for part in ref.removeprefix("#/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        target = target[part]
    return target


# --------------------------------------------------------------------------- #
# Parsing and reference integrity
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", [C4_YAML, C5_YAML])
def test_both_contracts_exist_and_parse(path: Path) -> None:
    """Both YAML surfaces parse as a single OpenAPI 3.1.0 document."""
    document = load(path)

    assert document["openapi"] == "3.1.0"
    assert document["info"]["version"] == "1.0.0"
    assert document["components"]["schemas"]


@pytest.mark.parametrize("path", [C4_YAML, C5_YAML])
def test_every_ref_resolves(path: Path) -> None:
    """Every ``$ref`` points at a node that exists — a dangling ref is a broken
    contract for every generator downstream."""
    document = load(path)
    refs = list(iter_refs(document))

    assert refs, "expected the document to use component refs"
    for trail, ref in refs:
        assert resolve(document, ref) is not None, f"{trail} → {ref} does not resolve"


@pytest.mark.parametrize("path", [C4_YAML, C5_YAML])
def test_no_component_schema_is_orphaned(path: Path) -> None:
    """Every declared schema is reachable from a path, a webhook or another
    schema — an unreferenced schema means a rename went half-done."""
    document = load(path)
    referenced = {ref for _, ref in iter_refs(document)}
    declared = {
        f"#/components/schemas/{name}" for name in document["components"]["schemas"]
    }

    assert declared - referenced == set()


# --------------------------------------------------------------------------- #
# Enum consistency: yaml ↔ yaml ↔ Python transcription
# --------------------------------------------------------------------------- #
def test_approval_status_enum_matches_the_python_transcription(c4: dict) -> None:
    """C4 §1 — the OpenAPI ``ApprovalStatus`` enum and
    ``sunil.core.approvals.base.ApprovalStatus`` are the same five values, in the
    same order."""
    yaml_enum = c4["components"]["schemas"]["ApprovalStatus"]["enum"]

    assert yaml_enum == [status.value for status in ApprovalStatus]
    assert yaml_enum == ["pending", "approved", "refused", "expired", "consumed"]
    # The status column carries no schema default (C4 §1 / the enum description).
    assert "default" not in c4["components"]["schemas"]["ApprovalStatus"]


def test_error_kinds_are_identical_across_both_contracts(c4: dict, c5: dict) -> None:
    """C4 §5 / C5 §3 — the ``ErrorResponse.kind`` enum is one shared vocabulary;
    a divergence would mean two different error languages on one API."""
    c4_kinds = c4["components"]["schemas"]["ErrorResponse"]["properties"]["error"][
        "properties"
    ]["kind"]["enum"]
    c5_kinds = c5["components"]["schemas"]["ErrorResponse"]["properties"]["error"][
        "properties"
    ]["kind"]["enum"]

    assert c4_kinds == c5_kinds
    assert c4_kinds == [
        "unauthenticated",
        "forbidden_client",
        "not_found",
        "validation_error",
    ]


def test_state_conflict_carries_the_status_and_the_only_conflict_kind(c4: dict) -> None:
    """C4 §5 — 409 ``state_conflict`` carrying ``current_status`` is the ONLY
    conflict shape (expiry at decision time is a 409, not a separate 410)."""
    error = c4["components"]["schemas"]["StateConflict"]["properties"]["error"]

    assert error["properties"]["kind"]["const"] == "state_conflict"
    assert error["properties"]["current_status"]["$ref"].endswith("/ApprovalStatus")
    assert set(error["required"]) == {"kind", "message", "current_status"}
    assert (
        "410"
        not in c4["paths"]["/api/v1/approvals/{approval_id}/decision"]["post"][
            "responses"
        ]
    )


def test_chat_outcome_and_failure_kinds(c5: dict) -> None:
    """C5 §2 — ``outcome`` is ``ok|failed|parked`` (ADR-031's one deviation from
    M1's envelope), and the failure vocabulary is M1's four kinds plus the three
    approval/continuation terminals."""
    schemas = c5["components"]["schemas"]

    assert schemas["ChatResponse"]["properties"]["outcome"]["enum"] == [
        "ok",
        "failed",
        "parked",
    ]
    assert schemas["ChatFailure"]["properties"]["kind"]["enum"] == [
        "provider_error",
        "tool_failed",
        "plan_rejected",
        "unknown_project",
        "approval_refused",
        "approval_expired",
        "continuation_interrupted",
    ]
    # known_projects is populated only for kind=unknown_project (C5 §4/test 1).
    assert "known_projects" in schemas["ChatFailure"]["properties"]
    assert schemas["ChatFailure"]["required"] == ["kind"]


def test_chat_envelope_requires_all_exactly_one_rule_members(c5: dict) -> None:
    """C5 §1/§2 — the envelope always carries all of
    ``message``/``task``/``failure``/``approval`` as keys (nullable), so the
    exactly-one rule is a value rule the response builder enforces, never a
    missing key the client has to probe for."""
    response = c5["components"]["schemas"]["ChatResponse"]

    assert set(response["required"]) == {
        "request_id",
        "conversation_id",
        "outcome",
        "message",
        "task",
        "failure",
        "approval",
        "trace",
        "usage",
    }
    for field in ("message", "task", "failure", "approval"):
        assert {"type": "null"} in response["properties"][field]["oneOf"]


def test_chat_request_bounds_and_closed_shape(c5: dict) -> None:
    """C5 §1 — ``message`` is ``string(1..8000)`` and the body is closed
    (``additionalProperties: false``), so an unknown field is a 422 before any
    turn machinery runs."""
    request = c5["components"]["schemas"]["ChatRequest"]

    assert request["additionalProperties"] is False
    assert request["required"] == ["message"]
    assert request["properties"]["message"]["minLength"] == 1
    assert request["properties"]["message"]["maxLength"] == 8000
    assert request["properties"]["input_modality"]["enum"] == ["text", "voice"]
    assert request["properties"]["input_modality"]["default"] == "text"


# --------------------------------------------------------------------------- #
# Fix-round regressions that must stay fixed
# --------------------------------------------------------------------------- #
def test_heartbeat_frame_has_no_stray_description_property(c5: dict) -> None:
    """C5 changelog 2026-09-10 — ``HeartbeatFrame``'s stray ``description``
    PROPERTY was a mis-indented schema description and was removed. The frame
    carries no payload beyond its timing offset (ADR-027)."""
    heartbeat = c5["components"]["schemas"]["HeartbeatFrame"]

    assert set(heartbeat["properties"]) == {"type", "offset_ms"}
    assert "description" not in heartbeat["properties"]
    assert isinstance(heartbeat["description"], str)  # the real, top-level one
    assert heartbeat["required"] == ["type", "offset_ms"]
    assert heartbeat["properties"]["type"]["const"] == "heartbeat"


def test_ndjson_frame_union_is_exactly_the_four_frames(c5: dict) -> None:
    """C5 §1/ADR-027 — stage | token | heartbeat | done, and the ``done`` frame
    carries the complete envelope (tokens are a projection)."""
    schemas = c5["components"]["schemas"]
    union = {ref["$ref"].rsplit("/", 1)[1] for ref in schemas["NdjsonFrame"]["oneOf"]}

    assert union == {"StageFrame", "TokenFrame", "HeartbeatFrame", "DoneFrame"}
    assert schemas["DoneFrame"]["properties"]["envelope"]["$ref"].endswith(
        "/ChatResponse"
    )
    for frame, const in (
        ("StageFrame", "stage"),
        ("TokenFrame", "token"),
        ("DoneFrame", "done"),
    ):
        assert schemas[frame]["properties"]["type"]["const"] == const


def test_approvals_api_has_no_creation_endpoint(c4: dict) -> None:
    """C4 §5 scope note — there is deliberately NO ``POST /api/v1/approvals``.
    Approvals are minted exclusively by the in-process ``park`` seam, inside the
    transaction that persists the continuation; the decision is the only mutating
    endpoint."""
    paths = c4["paths"]

    assert set(paths["/api/v1/approvals"]) == {"get"}
    assert set(paths["/api/v1/approvals/{approval_id}"]) == {"get"}
    assert set(paths["/api/v1/approvals/{approval_id}/decision"]) == {"post"}
    mutating = [
        (path, method)
        for path, operations in paths.items()
        for method in operations
        if method in {"post", "put", "patch", "delete"}
    ]
    assert mutating == [("/api/v1/approvals/{approval_id}/decision", "post")]


def test_webhook_payload_shape_cannot_carry_params(c4: dict) -> None:
    """C4 §2 / contract test 6 — the ``approval.requested`` payload is a redacted
    summary: ``params_redacted`` is not part of its schema at all (redaction by
    shape, not by filtering)."""
    event = c4["components"]["schemas"]["ApprovalRequestedEvent"]

    assert "params_redacted" not in event["properties"]
    assert set(event["required"]) == {
        "event",
        "approval_id",
        "agent_id",
        "tool",
        "operation",
        "summary",
        "created_at",
        "expires_at",
    }
    assert event["properties"]["event"]["const"] == "approval.requested"


def test_bearer_scheme_exists_only_on_the_chat_contract(c4: dict, c5: dict) -> None:
    """ADR-035 / C5 §2.3 — the service-token lane is declared on the chat contract
    only. The approvals contract offers cookie + client-header security, so no
    token value is even describable against it (the structural companion to C5
    contract test 5's runtime probe)."""
    assert "serviceToken" in c5["components"]["securitySchemes"]
    assert c5["paths"]["/api/v1/chat"]["post"]["security"] == [
        {"sessionCookie": [], "clientHeader": []},
        {"serviceToken": []},
    ]

    assert "serviceToken" not in c4["components"]["securitySchemes"]
    assert c4["security"] == [{"sessionCookie": [], "clientHeader": []}]
    assert "bearer" not in yaml.dump(c4["components"]["securitySchemes"]).lower()
