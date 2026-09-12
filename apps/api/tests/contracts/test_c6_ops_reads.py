"""C6 — Ops reads contract suite (the ten numbered tests of C6 §6).

Sources of truth: ``docs/contracts/C6-ops-reads.md`` v1.0.0 (FROZEN 2026-09-11)
and ``docs/contracts/C6-ops-reads-openapi.yaml``. Shapes are
``V2_DASHBOARD_SPEC.md`` §13.1–13.3 verbatim; the derivation, ordering and
partition rules are C6 §2.

Nine of the ten tests run entirely against ``tests/fakes/fake_ops_store.py``
(the store seam is in-process, C6 §5, so no route is needed to pin the laws).
Test 9 is route-level: its two request-free clauses carry FULL bodies (a route
table walk needs no session, no client and no fake), and the three clauses that
need a request harness C6 does not fix sit behind the F5 import guard — they
activate and fail loudly the moment the ops routes land, never a silent
forever-skip.

Every expected id sequence below is written out literally rather than computed
from the store, so a fake that changes its own answer cannot also change the
expectation (the P0-fakes F1/F8 lesson: never assert a fake against itself).
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from tests.fakes.fake_ops_store import (
    APPROVAL_LIFECYCLE_STAGES,
    DEFAULT_LIMIT,
    LIMIT_MAX,
    PROJECTION_KEYS,
    PROJECTION_PROBE_DETAIL,
    PROJECTION_PROBE_TASK,
    RECENT_CAP,
    SPINE_STAGES,
    TASK_STATUSES,
    TIE_AT,
    UNTRUSTED_EXCERPT,
    UNTRUSTED_OBJECTIVE,
    UNTRUSTED_SUMMARY,
    FakeOpsStore,
    ops_fixture,
)

pytestmark = pytest.mark.contract

# --------------------------------------------------------------------------- #
# The fixture's expected answers, written out (C6 §6 "Fixture")
# --------------------------------------------------------------------------- #
#: task-33 … task-13 — the 21 terminal recent-cap tasks, newest first.
FILLER_IDS_DESC = [f"task-{n}" for n in range(33, 12, -1)]
#: The twelve status-coverage tasks, newest first. task-9/task-10 share
#: ``TIE_AT``, so they are ordered by PLAIN STRING id desc: "task-9" > "task-10"
#: (the F8 reading of C4 §6.5, adopted unchanged by C6 §2.1).
BASE_IDS_DESC = [
    "task-12",
    "task-11",
    "task-9",
    "task-10",
    "task-8",
    "task-7",
    "task-6",
    "task-5",
    "task-4",
    "task-3",
    "task-2",
    "task-1",
]
ALL_IDS_DESC = FILLER_IDS_DESC + BASE_IDS_DESC
TOTAL_TASKS = 33

#: Terminal (completed + failed) tasks, newest first: the 21 fillers then the
#: four terminal rows among task-1…task-12.
TERMINAL_IDS_DESC = FILLER_IDS_DESC + ["task-12", "task-11", "task-7", "task-6", "task-4", "task-3"]

BY_STATUS: dict[str, list[str]] = {
    "pending": ["task-8", "task-1"],
    "in_progress": ["task-9", "task-2"],
    "parked": ["task-10", "task-5"],
    "completed": [f"task-{n}" for n in range(33, 12, -2)] + ["task-11", "task-7", "task-3"],
    "failed": [f"task-{n}" for n in range(32, 12, -2)] + ["task-12", "task-6", "task-4"],
}

BY_PROJECT: dict[str, list[str]] = {
    "sunil": ["task-12", "task-9", "task-5", "task-2", "task-1"],
    "easyclean": ["task-11", "task-8", "task-4", "task-3"],
    "sunil-archive": [],  # a near-miss key: the filter is EXACT, not a prefix
    "nope": [],
}

#: Both rows whose objective mentions invoices — one lower-case in the row, one
#: UPPER-case, so a single query proves case-insensitivity in both directions.
INVOICE_IDS_DESC = ["task-6", "task-3"]
TIE_IDS_DESC = ["task-9", "task-10"]

RUNNING_IDS = ["task-9", "task-8", "task-2", "task-1"]
PARKED_IDS = ["task-10", "task-5"]
#: The 20 newest terminal tasks; task-13 is the 21st newest and must fall off.
RECENT_IDS = FILLER_IDS_DESC[:RECENT_CAP]
RECENT_EXCLUDED = "task-13"

#: Audit index, newest first (started_at desc; seeded in the reverse of this
#: order, one second apart).
TURN_IDS_DESC = ["req-failed", "req-proj", "req-live", "req-parked", "req-full"]

# --------------------------------------------------------------------------- #
# Shapes, read out of the frozen OpenAPI document (no hand-copied key lists)
# --------------------------------------------------------------------------- #


def contracts_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "docs" / "contracts"
        if candidate.is_dir():
            return candidate
    raise AssertionError("docs/contracts not found above this test file")


C6_YAML = contracts_dir() / "C6-ops-reads-openapi.yaml"


@pytest.fixture(scope="module")
def c6() -> dict:
    return yaml.safe_load(C6_YAML.read_text(encoding="utf-8"))


def resolve(document: dict, ref: str):
    target = document
    for part in ref.removeprefix("#/").split("/"):
        target = target[part]
    return target


def required_keys(document: dict, name: str) -> set[str]:
    """Every key the named schema requires, following ``allOf`` composition.

    ``TaskDetail`` and ``ActivityItem`` are ``allOf: [Task, {…}]``, so the
    Task's thirteen always-present keys are part of their required set too.
    """
    schema = resolve(document, f"#/components/schemas/{name}")
    keys = set(schema.get("required", ()))
    for member in schema.get("allOf", ()):
        target = resolve(document, member["$ref"]) if "$ref" in member else member
        keys |= set(target.get("required", ()))
    return keys


@pytest.fixture
def store() -> FakeOpsStore:
    return ops_fixture()


def ids(rows: list[dict]) -> list[str]:
    return [row["id"] for row in rows]


def sort_keys(rows: list[dict]) -> list[tuple[str, str]]:
    return [(row["created_at"], row["id"]) for row in rows]


# --------------------------------------------------------------------------- #
# C6 contract test 1 — order law (§2.1 clauses 1 and 6)
# --------------------------------------------------------------------------- #
async def test_c6_1_default_order_is_created_at_desc_then_id_desc(
    store: FakeOpsStore,
) -> None:
    """C6 §2.1(1) — ``created_at desc, id desc`` over the whole fixture."""
    page = await store.list_tasks(limit=LIMIT_MAX)

    assert ids(page["tasks"]) == ALL_IDS_DESC
    assert len(page["tasks"]) == TOTAL_TASKS
    # The law as a property, not just as a literal list.
    assert sort_keys(page["tasks"]) == sorted(sort_keys(page["tasks"]), reverse=True)


async def test_c6_1_equal_created_at_pair_orders_lexicographically(
    store: FakeOpsStore,
) -> None:
    """C6 §2.1(1) / F8 — ``task-9`` sorts ABOVE ``task-10`` on equal
    ``created_at``, because the id column is compared as a plain string. The
    fixture seeds the tie deliberately (an explicit equal ``created_at``), since
    the seed helpers otherwise advance the clock one second per row and no tie
    would ever occur."""
    page = await store.list_tasks(q="Tie row", limit=LIMIT_MAX)

    assert [row["created_at"] for row in page["tasks"]] == [TIE_AT, TIE_AT]
    assert ids(page["tasks"]) == TIE_IDS_DESC
    # And in the full list the pair keeps that relative order.
    everything = ids((await store.list_tasks(limit=LIMIT_MAX))["tasks"])
    assert everything.index("task-9") < everything.index("task-10")


async def test_c6_1_order_oldest_reverses_both_keys(store: FakeOpsStore) -> None:
    """C6 §2.1(6) — ``order=oldest`` is ``created_at asc, id asc``: the exact
    reverse of the default, tie included (``task-10`` before ``task-9``)."""
    newest = ids((await store.list_tasks(limit=LIMIT_MAX))["tasks"])
    oldest = ids((await store.list_tasks(order="oldest", limit=LIMIT_MAX))["tasks"])

    assert oldest == list(reversed(newest))
    tie = ids((await store.list_tasks(order="oldest", q="Tie row"))["tasks"])
    assert tie == list(reversed(TIE_IDS_DESC))


async def test_c6_1_default_limit_is_the_contract_default(store: FakeOpsStore) -> None:
    """C6 §2.1(5) — default ``limit`` is 50 (C4's bounds), so the 33-row fixture
    comes back in one short page."""
    page = await store.list_tasks()

    assert DEFAULT_LIMIT == 50
    assert len(page["tasks"]) == TOTAL_TASKS
    assert page["next_cursor"] is None


# --------------------------------------------------------------------------- #
# C6 contract test 2 — cursor law (§2.1 clauses 2, 3, 4, 5)
# --------------------------------------------------------------------------- #
async def test_c6_2_exactly_full_final_page_returns_a_cursor_then_an_empty_page(
    store: FakeOpsStore,
) -> None:
    """C6 §2.1(3) — with ``limit`` dividing the total exactly (33 = 3 × 11),
    EVERY page including the last full one returns a non-null ``next_cursor``;
    the walk ends on a following EMPTY page with a null cursor. No look-ahead."""
    seen: list[str] = []
    cursors: list[str | None] = []
    cursor: str | None = None
    pages = 0

    while True:
        page = await store.list_tasks(limit=11, cursor=cursor)
        pages += 1
        assert pages <= 5, "the walk did not terminate"
        cursors.append(page["next_cursor"])
        if not page["tasks"]:
            assert page["next_cursor"] is None
            break
        assert len(page["tasks"]) == 11
        assert page["next_cursor"] == page["tasks"][-1]["id"]  # §2.1(2)
        seen += ids(page["tasks"])
        cursor = page["next_cursor"]

    assert pages == 4  # three exactly-full pages, then the empty one
    assert cursors == ["task-23", "task-12", "task-1", None]
    assert seen == ALL_IDS_DESC
    assert len(seen) == len(set(seen))  # no row served twice


async def test_c6_2_short_page_ends_the_walk_with_a_null_cursor(
    store: FakeOpsStore,
) -> None:
    """C6 §2.1(3) — ``next_cursor`` is null ONLY when the page is short."""
    first = await store.list_tasks(limit=20)
    assert first["next_cursor"] == "task-14"

    second = await store.list_tasks(limit=20, cursor=first["next_cursor"])

    assert len(second["tasks"]) == 13  # short
    assert second["next_cursor"] is None
    assert ids(first["tasks"]) + ids(second["tasks"]) == ALL_IDS_DESC


async def test_c6_2_unknown_cursor_is_a_validation_error(store: FakeOpsStore) -> None:
    """C6 §2.1(4)/§5 — an unknown cursor raises ``ValueError`` in the store (the
    HTTP layer's 422); it is NEVER a silent page one."""
    with pytest.raises(ValueError):
        await store.list_tasks(cursor="task-nope")


async def test_c6_2_a_cursor_outside_the_filtered_set_is_a_validation_error(
    store: FakeOpsStore,
) -> None:
    """C6 §2.1(2) — filters apply BEFORE ordering and pagination, so a page walk
    is a walk over the FILTERED set: ``task-1`` is a real id but is not in the
    ``completed`` set, so it is an unknown cursor there (422), not a restart."""
    with pytest.raises(ValueError):
        await store.list_tasks(status="completed", cursor="task-1")


@pytest.mark.parametrize("limit", [0, -1, 201, 1000])
async def test_c6_2_limit_outside_1_to_200_is_a_validation_error(
    store: FakeOpsStore, limit: int
) -> None:
    """C6 §2.1(5) — ``limit`` is 1..200; outside is a 422 (``ValueError`` at the
    store seam, the same mapping as an unknown cursor)."""
    with pytest.raises(ValueError):
        await store.list_tasks(limit=limit)


@pytest.mark.parametrize("limit", [1, 200])
async def test_c6_2_limit_bounds_themselves_are_accepted(
    store: FakeOpsStore, limit: int
) -> None:
    """The bounds are inclusive — an off-by-one in the guard would reject 1 or
    200, both of which the contract allows."""
    page = await store.list_tasks(limit=limit)

    assert len(page["tasks"]) == min(limit, TOTAL_TASKS)


async def test_c6_2_the_cursor_walk_holds_a_filter_constant(
    store: FakeOpsStore,
) -> None:
    """C6 §2.1(2) — the walk over a filtered set returns exactly that set, in
    the one order, and the filter is not re-applied differently per page."""
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        page = await store.list_tasks(status="completed", limit=5, cursor=cursor)
        seen += ids(page["tasks"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == BY_STATUS["completed"]  # 14 rows: 5 + 5 + 4 (short) → done


# --------------------------------------------------------------------------- #
# C6 contract test 3 — filters (§2.2)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", TASK_STATUSES)
async def test_c6_3_status_filter_matches_each_enum_value(
    store: FakeOpsStore, status: str
) -> None:
    """C6 §2.2 — every ``TaskStatus`` value filters exactly, in the §2.1 order."""
    page = await store.list_tasks(status=status, limit=LIMIT_MAX)

    assert ids(page["tasks"]) == BY_STATUS[status]
    assert {row["status"] for row in page["tasks"]} == {status}


async def test_c6_3_the_five_status_sets_partition_the_fixture(
    store: FakeOpsStore,
) -> None:
    """A filter test only means something if the fixture covers the enum: the
    five sets are disjoint and sum to every seeded task."""
    covered = [task_id for status in TASK_STATUSES for task_id in BY_STATUS[status]]

    assert sorted(covered) == sorted(ALL_IDS_DESC)
    assert len(covered) == TOTAL_TASKS
    for status in TASK_STATUSES:
        assert BY_STATUS[status], f"the fixture seeds no {status} task"


@pytest.mark.parametrize("key", sorted(BY_PROJECT))
async def test_c6_3_project_key_is_an_exact_match_and_excludes_null_rows(
    store: FakeOpsStore, key: str
) -> None:
    """C6 §2.2/§3 — ``project_key`` is exact (not a prefix, not a fuzzy match);
    rows whose ``project_key`` is null are excluded from every keyed filter."""
    page = await store.list_tasks(project_key=key, limit=LIMIT_MAX)

    assert ids(page["tasks"]) == BY_PROJECT[key]
    assert {row["project_key"] for row in page["tasks"]} <= {key}
    assert None not in {row["project_key"] for row in page["tasks"]}


async def test_c6_3_null_project_rows_exist_so_the_exclusion_means_something(
    store: FakeOpsStore,
) -> None:
    everything = (await store.list_tasks(limit=LIMIT_MAX))["tasks"]

    assert any(row["project_key"] is None for row in everything)
    assert {row["project_key"] for row in everything} == {"sunil", "easyclean", None}


@pytest.mark.parametrize("q", ["invoices", "INVOICES", "Invoices", "iNvOiCeS"])
async def test_c6_3_q_is_a_case_insensitive_substring_over_objective(
    store: FakeOpsStore, q: str
) -> None:
    """C6 §2.2 — ``q`` is ``q.lower() in objective.lower()``: one fixture row
    spells it lower-case and one UPPER-case, so any casing finds both."""
    page = await store.list_tasks(q=q, limit=LIMIT_MAX)

    assert ids(page["tasks"]) == INVOICE_IDS_DESC


async def test_c6_3_q_matches_the_untrusted_markup_bytes_verbatim(
    store: FakeOpsStore,
) -> None:
    """§4 — the search runs over the stored bytes; a server that escaped or
    stripped the objective on the way in could not match this query."""
    page = await store.list_tasks(q="<b>bold</b>", limit=LIMIT_MAX)

    assert ids(page["tasks"]) == ["task-1"]
    assert page["tasks"][0]["objective"] == UNTRUSTED_OBJECTIVE


async def test_c6_3_q_does_not_search_any_other_field(store: FakeOpsStore) -> None:
    """C6 §2.2 — ``q`` is "substring over ``objective``", so a value that only
    occurs in another column (the agent key, the project key, the id) matches
    nothing."""
    for probe in ("project_manager", "easyclean", "task-1", "req-full"):
        page = await store.list_tasks(q=probe, limit=LIMIT_MAX)
        assert page["tasks"] == [], f"q matched outside objective on {probe!r}"


async def test_c6_3_filters_compose_with_and(store: FakeOpsStore) -> None:
    """C6 §2.2 — "filters compose with AND"."""
    both = await store.list_tasks(status="completed", q="invoices", limit=LIMIT_MAX)
    assert ids(both["tasks"]) == ["task-3"]

    other = await store.list_tasks(status="failed", q="invoices", limit=LIMIT_MAX)
    assert ids(other["tasks"]) == ["task-6"]

    keyed = await store.list_tasks(
        status="completed", project_key="easyclean", limit=LIMIT_MAX
    )
    assert ids(keyed["tasks"]) == ["task-11", "task-3"]

    triple = await store.list_tasks(
        status="completed", project_key="easyclean", q="invoices", limit=LIMIT_MAX
    )
    assert ids(triple["tasks"]) == ["task-3"]

    empty = await store.list_tasks(
        status="pending", project_key="easyclean", q="invoices", limit=LIMIT_MAX
    )
    assert empty == {"tasks": [], "next_cursor": None}


@pytest.mark.parametrize("status", ["bogus", "PENDING", "", "pending "])
async def test_c6_3_status_outside_the_enum_is_a_validation_error(
    store: FakeOpsStore, status: str
) -> None:
    """C6 §2.2 — ``status`` outside the enum is 422, never an empty page (an
    empty page would read as "no such tasks" and hide a client bug)."""
    with pytest.raises(ValueError):
        await store.list_tasks(status=status)


@pytest.mark.parametrize("order", ["bogus", "NEWEST", "asc"])
async def test_c6_3_order_outside_the_enum_is_a_validation_error(
    store: FakeOpsStore, order: str
) -> None:
    """The OpenAPI declares ``order`` as ``enum: [newest, oldest]``; anything
    else is a 422 rather than a silent fall-back to ``newest``."""
    with pytest.raises(ValueError):
        await store.list_tasks(order=order)


async def test_c6_3_list_rows_carry_exactly_the_task_shape(
    store: FakeOpsStore, c6: dict
) -> None:
    """§2.2 — "every key always present; absence = null". Asserted against the
    frozen OpenAPI ``required`` list, so a shape drift in either direction (a
    dropped key, a leaked extra one) fails here."""
    expected = required_keys(c6, "Task")
    page = await store.list_tasks(limit=LIMIT_MAX)

    assert len(expected) == 13
    for row in page["tasks"]:
        assert set(row) == expected
    assert set(page) == required_keys(c6, "TaskListResponse")


# --------------------------------------------------------------------------- #
# C6 contract test 4 — task detail + status_events (§2.2)
# --------------------------------------------------------------------------- #
async def test_c6_4_detail_is_the_task_plus_its_status_events(
    store: FakeOpsStore, c6: dict
) -> None:
    detail = await store.get_task("task-3")

    assert set(detail) == required_keys(c6, "TaskDetail")
    assert detail["id"] == "task-3"
    event_keys = required_keys(c6, "TaskStatusEvent")
    for event in detail["status_events"]:
        assert set(event) == event_keys


async def test_c6_4_status_events_ascend_by_at_with_the_creation_event_first(
    store: FakeOpsStore,
) -> None:
    """C6 §2.2 — ascending ``at`` (a timeline), ``from_status`` null on the
    creation event. ``task-9``'s two transitions are seeded in REVERSE ``at``
    order, so a fake that returned write order rather than ``at`` order fails
    here."""
    detail = await store.get_task("task-9")
    events = detail["status_events"]

    assert [event["at"] for event in events] == sorted(event["at"] for event in events)
    assert events[0]["from_status"] is None
    assert events[0]["to_status"] == "pending"
    assert events[0]["at"] == TIE_AT
    assert [(event["from_status"], event["to_status"]) for event in events] == [
        (None, "pending"),
        ("pending", "in_progress"),
        ("parked", "in_progress"),
    ]
    assert [event["from_status"] for event in events].count(None) == 1
    # The last write materialised the row's status (C6 §6 helper 2).
    assert detail["status"] == "in_progress"


async def test_c6_4_status_event_ties_keep_write_order(store: FakeOpsStore) -> None:
    """C6 §6(3) — "ties keep write order": ``task-3``'s two transitions carry an
    identical explicit ``at``, so only a stable sort produces the real
    timeline."""
    events = (await store.get_task("task-3"))["status_events"]
    tied = [event for event in events if event["at"] == "2026-01-01T00:02:00Z"]

    assert len(tied) == 2
    assert [(event["from_status"], event["to_status"]) for event in tied] == [
        ("pending", "in_progress"),
        ("in_progress", "completed"),
    ]
    assert events[-1]["to_status"] == "completed"


async def test_c6_4_a_task_with_no_transitions_still_has_its_creation_event(
    store: FakeOpsStore,
) -> None:
    detail = await store.get_task("task-1")

    assert detail["status_events"] == [
        {"from_status": None, "to_status": "pending", "at": detail["created_at"]}
    ]


async def test_c6_4_unknown_task_id_is_none_for_the_404_mapping(
    store: FakeOpsStore,
) -> None:
    """C6 §5 — ``None`` from the getter maps to 404 in the HTTP layer and
    nowhere else; the store does not raise."""
    assert await store.get_task("task-nope") is None
    assert await store.get_task("") is None
    assert await store.get_task("TASK-1") is None  # ids are case-sensitive


# --------------------------------------------------------------------------- #
# C6 contract test 5 — activity partition + projection (§2.3)
# --------------------------------------------------------------------------- #
async def test_c6_5_partition_is_exactly_by_task_status(store: FakeOpsStore) -> None:
    """C6 §2.3 — ``running`` = pending + in_progress, ``parked`` = parked,
    ``recent`` = completed + failed (capped)."""
    snapshot = await store.activity()

    assert ids(snapshot["running"]) == RUNNING_IDS
    assert ids(snapshot["parked"]) == PARKED_IDS
    assert {row["status"] for row in snapshot["running"]} == {"pending", "in_progress"}
    assert {row["status"] for row in snapshot["parked"]} == {"parked"}
    assert {row["status"] for row in snapshot["recent"]} <= {"completed", "failed"}
    # Disjoint: no task appears in two lists.
    everywhere = ids(snapshot["running"]) + ids(snapshot["parked"]) + ids(snapshot["recent"])
    assert len(everywhere) == len(set(everywhere))


async def test_c6_5_recent_is_capped_at_the_twenty_newest_terminal_tasks(
    store: FakeOpsStore,
) -> None:
    """C6 §2.3 — ``recent`` is truncated to 20 AFTER ordering, so the excluded
    row is the OLDEST terminal one and the 21st-newest (``task-13``) falls off
    while every newer one stays."""
    snapshot = await store.activity()

    assert RECENT_CAP == 20
    assert len(snapshot["recent"]) == RECENT_CAP
    assert ids(snapshot["recent"]) == RECENT_IDS
    assert RECENT_EXCLUDED not in ids(snapshot["recent"])
    assert len(TERMINAL_IDS_DESC) == 27  # the cap is doing real work
    assert ids(snapshot["recent"]) == TERMINAL_IDS_DESC[:RECENT_CAP]


async def test_c6_5_running_and_parked_are_complete_not_capped(
    store: FakeOpsStore,
) -> None:
    """The OpenAPI puts ``maxItems: 20`` on ``recent`` ALONE (spec §7.1)."""
    snapshot = await store.activity()

    assert len(snapshot["running"]) == len(RUNNING_IDS)
    assert len(snapshot["parked"]) == len(PARKED_IDS)


async def test_c6_5_all_three_lists_use_the_one_ordering_law(
    store: FakeOpsStore,
) -> None:
    """C6 §2.3 — all three lists use ``created_at desc, id desc``; the partition
    does not depend on ``completed_at`` being set on failed rows."""
    snapshot = await store.activity()

    for key in ("running", "parked", "recent"):
        keys = sort_keys(snapshot[key])
        assert keys == sorted(keys, reverse=True), f"{key} is not in the §2.1 order"
    assert any(
        row["status"] == "failed" and row["completed_at"] is None
        for row in snapshot["recent"]
    )


async def test_c6_5_latest_stage_comes_from_the_highest_seq_audit_row(
    store: FakeOpsStore,
) -> None:
    """C6 §2.3 — the fold-in is the HIGHEST-seq row for the task's
    ``request_id``, not the first row and not the last one written."""
    snapshot = await store.activity()
    parked = {row["id"]: row for row in snapshot["parked"]}["task-5"]

    # req-parked's highest seq is the continuation's tool_result (seq 14),
    # NOT its final_response (seq 11).
    assert parked["latest_stage"] == "tool_result"
    assert parked["latest_stage_at"] == "2026-01-01T00:00:57Z"


async def test_c6_5_latest_detail_projects_only_the_three_contracted_keys(
    store: FakeOpsStore,
) -> None:
    """C6 §2.3 — the projection is onto exactly
    ``{project_display_name?, tool?, operation?}``. Other ``detail`` keys MUST
    NOT pass through: the seeded row carries ``secret_excerpt`` beside ``tool``
    and only ``tool`` may survive. This is the endpoint's trusted-detail
    promise, so the assertion is exact equality, not a subset."""
    snapshot = await store.activity()
    probe = {row["id"]: row for row in snapshot["running"]}[PROJECTION_PROBE_TASK]

    assert PROJECTION_PROBE_DETAIL == {"tool": "github_mcp", "secret_excerpt": "x"}
    assert probe["latest_detail"] == {"tool": "github_mcp"}
    assert "secret_excerpt" not in probe["latest_detail"]
    assert set(probe["latest_detail"]) <= PROJECTION_KEYS


async def test_c6_5_the_projection_passes_all_three_contracted_keys(
    store: FakeOpsStore,
) -> None:
    """The complement of the leak probe: a row carrying all three contracted
    keys (plus an untrusted excerpt) projects all three and drops the
    excerpt — the filter is a key allow-list, not a "first key wins".

    Probed on the PARKED row: its latest audit row is the continuation's
    ``tool_result``, which carries all three contracted keys beside the lineage
    key and an untrusted excerpt. (It cannot be probed on ``task-12``: the
    fixture seeds 21 newer terminal tasks, so the §2.3 cap of 20 removes
    ``task-12`` from ``recent`` — as the cap test above proves.)"""
    snapshot = await store.activity()
    row = {item["id"]: item for item in snapshot["parked"]}["task-5"]

    assert row["latest_detail"] == {
        "project_display_name": "SUNIL",
        "tool": "github_mcp",
        "operation": "create_issue",
    }
    assert UNTRUSTED_EXCERPT not in json.dumps(row["latest_detail"], ensure_ascii=False)


async def test_c6_5_no_audit_row_yields_null_latest_fields(
    store: FakeOpsStore,
) -> None:
    """C6 §2.3 — both ``latest_*`` fields are null when no audit row exists
    (defensive). ``latest_detail`` is a non-nullable object in the OpenAPI, so
    its absence is the empty object."""
    snapshot = await store.activity()
    bare = {row["id"]: row for row in snapshot["running"]}["task-1"]

    assert bare["latest_stage"] is None
    assert bare["latest_stage_at"] is None
    assert bare["latest_detail"] == {}


async def test_c6_5_activity_items_carry_exactly_the_activity_item_shape(
    store: FakeOpsStore, c6: dict
) -> None:
    snapshot = await store.activity()
    expected = required_keys(c6, "ActivityItem")

    assert set(snapshot) == required_keys(c6, "ActivityResponse")
    assert len(expected) == 16  # Task's 13 + the three latest_* keys
    for key in ("running", "parked", "recent"):
        for row in snapshot[key]:
            assert set(row) == expected


# --------------------------------------------------------------------------- #
# C6 contract test 6 — audit derivations (§2.4)
# --------------------------------------------------------------------------- #
async def turn(store: FakeOpsStore, request_id: str) -> dict:
    page = await store.list_audit_turns(request_id=request_id)
    assert len(page["turns"]) == 1, f"{request_id} did not resolve to one turn"
    return page["turns"][0]


async def test_c6_6_in_flight_turn_has_null_ended_at_and_outcome(
    store: FakeOpsStore,
) -> None:
    """C6 §2.4 — ``ended_at``/``outcome``/``failure_kind`` are null while in
    flight (no ``final_response`` row), ``agent`` is null before
    ``plan_created``, and ``conversation_id``/``task_id`` are null in the window
    before a task exists. ``req-live`` is exactly that window: five spine rows,
    no plan, no task."""
    live = await turn(store, "req-live")

    assert live["ended_at"] is None
    assert live["outcome"] is None
    assert live["failure_kind"] is None
    assert live["agent"] is None
    assert live["conversation_id"] is None
    assert live["task_id"] is None
    assert live["stage_count"] == 5
    assert live["started_at"] == "2026-01-01T00:00:58Z"


async def test_c6_6_stage_count_counts_the_twelve_spine_names_only(
    store: FakeOpsStore,
) -> None:
    """C6 §2.4 — ``stage_count`` counts rows whose ``stage`` is one of the twelve
    NFR-020 spine names; approval-episode rows are NOT counted, "so the view's
    'n of 12' reading stays honest".

    ``req-parked`` carries 14 rows: ten spine rows of its own, two approval
    lifecycle rows (not spine names) and two CONTINUATION rows, one of which
    (``tool_result``) does carry a spine name and is an episode row by the
    ``resumed_from_approval_id`` rule. It must not be counted — counting it
    would report 11 of 12 for a turn that ran ten stages, which is the exact
    dishonesty the clause exists to prevent."""
    parked = await turn(store, "req-parked")
    detail = await store.get_audit_turn("req-parked")

    assert len(detail["events"]) + len(detail["approval_events"]) == 14
    assert parked["stage_count"] == 10
    assert parked["stage_count"] == len(
        [row for row in detail["events"] if row["stage"] in SPINE_STAGES]
    )
    # The naive reading (every spine-named row, episode or not) would be 11.
    everything = detail["events"] + detail["approval_events"]
    assert len([row for row in everything if row["stage"] in SPINE_STAGES]) == 11


async def test_c6_6_a_complete_turn_counts_all_twelve_stages(
    store: FakeOpsStore,
) -> None:
    full = await turn(store, "req-full")

    assert full["stage_count"] == 12
    assert len(SPINE_STAGES) == 12
    assert full["started_at"] == "2026-01-01T00:00:32Z"
    assert full["ended_at"] == "2026-01-01T00:00:43Z"


async def test_c6_6_outcome_failure_kind_and_agent_come_from_contracted_keys(
    store: FakeOpsStore,
) -> None:
    """C6 §2.4 — ``outcome``/``failure_kind`` from
    ``final_response.detail``, ``agent`` from ``plan_created.detail.agent``."""
    failed = await turn(store, "req-failed")

    assert failed["outcome"] == "failed"
    assert failed["failure_kind"] == "tool_failed"
    assert failed["agent"] == "developer"

    ok = await turn(store, "req-full")
    assert ok["outcome"] == "ok"
    assert ok["failure_kind"] is None
    assert ok["agent"] == "project_manager"

    parked = await turn(store, "req-parked")
    assert parked["outcome"] == "parked"  # C5's third outcome (ADR-031)
    assert parked["failure_kind"] is None


async def test_c6_6_started_at_is_the_first_row_and_ended_at_is_final_response(
    store: FakeOpsStore,
) -> None:
    """C6 §2.4 — ``started_at`` is the LOWEST-seq row's ``at``; ``ended_at`` is
    the ``final_response`` row's ``at``, which for a parked turn is NOT the last
    row (the continuation rows come after it)."""
    detail = await store.get_audit_turn("req-parked")
    parked = await turn(store, "req-parked")
    rows = sorted(detail["events"] + detail["approval_events"], key=lambda r: r["seq"])

    assert parked["started_at"] == rows[0]["at"]
    assert parked["ended_at"] == next(
        row["at"] for row in rows if row["stage"] == "final_response"
    )
    assert parked["ended_at"] < rows[-1]["at"]


async def test_c6_6_conversation_and_task_resolve_through_the_turns_task(
    store: FakeOpsStore,
) -> None:
    """C6 §2.4/§6(5) — ``conversation_id`` resolves via the store's
    request_id → conversation_id map, and ``task_id`` through the turn's task."""
    full = await turn(store, "req-full")

    assert full["task_id"] == "task-3"
    assert full["conversation_id"] == "conv-3"


async def test_c6_6_turns_carry_exactly_the_audit_turn_shape(
    store: FakeOpsStore, c6: dict
) -> None:
    page = await store.list_audit_turns(limit=LIMIT_MAX)
    expected = required_keys(c6, "AuditTurn")

    assert set(page) == required_keys(c6, "AuditTurnListResponse")
    assert len(expected) == 9
    for row in page["turns"]:
        assert set(row) == expected
    assert [row["request_id"] for row in page["turns"]] == TURN_IDS_DESC


# --------------------------------------------------------------------------- #
# C6 contract test 7 — audit filters, half-open window, cursor law (§2.4)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("request_id", [*TURN_IDS_DESC, "req-nope", ""])
async def test_c6_7_request_id_filter_returns_zero_or_one_turn(
    store: FakeOpsStore, request_id: str
) -> None:
    """C6 §2.4 — ``request_id`` exact returns 0 or 1 turn (the primary way in).
    An unknown id is an EMPTY page here, not a 404: the 404 belongs to
    ``getAuditTurn`` (§5)."""
    page = await store.list_audit_turns(request_id=request_id)

    expected = [request_id] if request_id in TURN_IDS_DESC else []
    assert [row["request_id"] for row in page["turns"]] == expected
    assert page["next_cursor"] is None


async def test_c6_7_index_order_is_started_at_desc_then_request_id_desc(
    store: FakeOpsStore,
) -> None:
    """C6 §2.1(1) — the audit index's keys are ``started_at desc,
    request_id desc`` (plain string)."""
    page = await store.list_audit_turns(limit=LIMIT_MAX)
    keys = [(row["started_at"], row["request_id"]) for row in page["turns"]]

    assert [row["request_id"] for row in page["turns"]] == TURN_IDS_DESC
    assert keys == sorted(keys, reverse=True)


async def test_c6_7_from_is_inclusive_and_to_is_exclusive(
    store: FakeOpsStore,
) -> None:
    """C6 §2.4 — ``from``/``to`` are half-open on ``started_at``
    (``from <= started_at < to``), probed with a row exactly on each edge."""
    at_live = "2026-01-01T00:00:58Z"  # req-live's started_at
    at_failed = "2026-01-01T00:01:04Z"  # req-failed's started_at

    from_edge = await store.list_audit_turns(from_at=at_live, limit=LIMIT_MAX)
    assert [row["request_id"] for row in from_edge["turns"]] == [
        "req-failed",
        "req-proj",
        "req-live",
    ]

    to_edge = await store.list_audit_turns(to_at=at_failed, limit=LIMIT_MAX)
    assert [row["request_id"] for row in to_edge["turns"]] == [
        "req-proj",
        "req-live",
        "req-parked",
        "req-full",
    ]

    window = await store.list_audit_turns(
        from_at=at_live, to_at=at_failed, limit=LIMIT_MAX
    )
    assert [row["request_id"] for row in window["turns"]] == ["req-proj", "req-live"]


async def test_c6_7_a_degenerate_window_is_empty(store: FakeOpsStore) -> None:
    """Half-open means ``from == to`` selects nothing — the row exactly on the
    edge is included by ``from`` and excluded by ``to``, and exclusion wins."""
    at_live = "2026-01-01T00:00:58Z"

    page = await store.list_audit_turns(from_at=at_live, to_at=at_live, limit=LIMIT_MAX)

    assert page == {"turns": [], "next_cursor": None}


@pytest.mark.parametrize(
    "outcome,expected",
    [
        ("ok", ["req-full"]),
        ("failed", ["req-failed"]),
        ("parked", ["req-parked"]),
    ],
)
async def test_c6_7_outcome_filter(
    store: FakeOpsStore, outcome: str, expected: list[str]
) -> None:
    """C6 §2.4 — the ``outcome`` filter; in-flight turns (null outcome) match no
    value of it."""
    page = await store.list_audit_turns(outcome=outcome, limit=LIMIT_MAX)

    assert [row["request_id"] for row in page["turns"]] == expected


@pytest.mark.parametrize(
    "agent,expected",
    [
        ("project_manager", ["req-parked", "req-full"]),
        ("developer", ["req-failed"]),
        ("nobody", []),
    ],
)
async def test_c6_7_agent_filter_is_exact(
    store: FakeOpsStore, agent: str, expected: list[str]
) -> None:
    page = await store.list_audit_turns(agent=agent, limit=LIMIT_MAX)

    assert [row["request_id"] for row in page["turns"]] == expected


async def test_c6_7_audit_filters_compose_with_and(store: FakeOpsStore) -> None:
    page = await store.list_audit_turns(
        agent="project_manager", outcome="ok", limit=LIMIT_MAX
    )

    assert [row["request_id"] for row in page["turns"]] == ["req-full"]


async def test_c6_7_cursor_law_holds_on_the_audit_index(store: FakeOpsStore) -> None:
    """C6 §2.1(2)(3) re-asserted on ``request_id desc``: the cursor is the last
    row's ``request_id``, an exactly-full final page still returns it, and the
    following page is empty."""
    walked: list[str] = []
    cursor: str | None = None
    pages = 0

    while True:
        page = await store.list_audit_turns(limit=5, cursor=cursor)
        pages += 1
        assert pages <= 3
        if not page["turns"]:
            assert page["next_cursor"] is None
            break
        assert page["next_cursor"] == page["turns"][-1]["request_id"]
        walked += [row["request_id"] for row in page["turns"]]
        cursor = page["next_cursor"]

    assert pages == 2  # 5 turns, limit 5: one exactly-full page then an empty one
    assert walked == TURN_IDS_DESC


async def test_c6_7_audit_cursor_walk_one_row_at_a_time(store: FakeOpsStore) -> None:
    walked: list[str] = []
    cursor: str | None = None
    for _ in range(len(TURN_IDS_DESC)):
        page = await store.list_audit_turns(limit=1, cursor=cursor)
        assert len(page["turns"]) == 1
        walked.append(page["turns"][0]["request_id"])
        cursor = page["next_cursor"]
        assert cursor == walked[-1]

    assert walked == TURN_IDS_DESC
    assert (await store.list_audit_turns(limit=1, cursor=cursor))["turns"] == []


async def test_c6_7_unknown_audit_cursor_is_a_validation_error(
    store: FakeOpsStore,
) -> None:
    with pytest.raises(ValueError):
        await store.list_audit_turns(cursor="req-nope")


async def test_c6_7_a_cursor_outside_the_filtered_audit_set_is_a_validation_error(
    store: FakeOpsStore,
) -> None:
    with pytest.raises(ValueError):
        await store.list_audit_turns(outcome="ok", cursor="req-live")


@pytest.mark.parametrize("limit", [0, -1, 201])
async def test_c6_7_audit_limit_bounds(store: FakeOpsStore, limit: int) -> None:
    with pytest.raises(ValueError):
        await store.list_audit_turns(limit=limit)


@pytest.mark.parametrize("outcome", ["OK", "bogus", "done"])
async def test_c6_7_outcome_outside_the_enum_is_a_validation_error(
    store: FakeOpsStore, outcome: str
) -> None:
    """The OpenAPI declares ``outcome`` as ``enum: [ok, failed, parked]``."""
    with pytest.raises(ValueError):
        await store.list_audit_turns(outcome=outcome)


# --------------------------------------------------------------------------- #
# C6 contract test 8 — detail partition (§2.4 "Detail partition (normative)")
# --------------------------------------------------------------------------- #
async def test_c6_8_parked_turn_splits_its_episode_out_of_events(
    store: FakeOpsStore,
) -> None:
    """C6 §2.4 — ``approval_events`` = the lifecycle rows PLUS the continuation
    rows; ``events`` = every other row. Both ascending ``seq``."""
    detail = await store.get_audit_turn("req-parked")

    assert [row["seq"] for row in detail["events"]] == list(range(1, 10)) + [11]
    assert [row["seq"] for row in detail["approval_events"]] == [10, 12, 13, 14]
    assert [row["stage"] for row in detail["approval_events"]] == [
        "approval_requested",
        "approval_approved",
        "tool_call",
        "tool_result",
    ]
    assert all(row["stage"] in SPINE_STAGES for row in detail["events"])


async def test_c6_8_continuation_rows_land_there_by_detail_not_by_stage_name(
    store: FakeOpsStore,
) -> None:
    """C6 §2.4 — the continuation's rows are episode rows because their
    ``detail`` carries ``resumed_from_approval_id`` (C4 §3's lineage rule), NOT
    because of their stage name: one of them (``tool_result``) shares a name
    with a spine stage that also appears in ``events``."""
    detail = await store.get_audit_turn("req-parked")
    lifecycle = [
        row for row in detail["approval_events"] if row["stage"] in APPROVAL_LIFECYCLE_STAGES
    ]
    by_lineage = [
        row
        for row in detail["approval_events"]
        if (row["detail"] or {}).get("resumed_from_approval_id") is not None
    ]

    assert [row["seq"] for row in lifecycle] == [10, 12]
    assert [row["seq"] for row in by_lineage] == [13, 14]
    assert {row["stage"] for row in by_lineage} == {"tool_call", "tool_result"}
    assert not {row["stage"] for row in by_lineage} & APPROVAL_LIFECYCLE_STAGES
    assert all(
        row["detail"]["resumed_from_approval_id"] == "apr-1" for row in by_lineage
    )
    # The same stage name appears on a non-episode row, so the partition cannot
    # have been done by name.
    assert "tool_result" in {row["stage"] for row in detail["events"]}


async def test_c6_8_a_turn_without_an_episode_has_null_approval_events(
    store: FakeOpsStore,
) -> None:
    """C6 §2.4 — ``approval_events`` is NULL (not an empty list) when the turn
    had no approval episode: the view renders the second segment only when the
    key is non-null."""
    for request_id, count in (("req-full", 12), ("req-live", 5), ("req-proj", 1)):
        detail = await store.get_audit_turn(request_id)

        assert detail["approval_events"] is None, request_id
        assert [row["seq"] for row in detail["events"]] == list(range(1, count + 1))


async def test_c6_8_unknown_request_id_is_none_for_the_404_mapping(
    store: FakeOpsStore,
) -> None:
    """C6 §2.4/§5 — zero audit rows for the id → ``None`` → 404."""
    assert await store.get_audit_turn("req-nope") is None
    assert await store.get_audit_turn("") is None
    # A task's request_id with no audit rows is equally a 404, not an empty turn.
    assert await store.get_audit_turn("req-t7") is None


async def test_c6_8_events_carry_exactly_the_audit_event_shape(
    store: FakeOpsStore, c6: dict
) -> None:
    detail = await store.get_audit_turn("req-parked")
    expected = required_keys(c6, "AuditEvent")

    assert set(detail) == required_keys(c6, "AuditTurnDetail")
    assert len(expected) == 7
    for row in detail["events"] + detail["approval_events"]:
        assert set(row) == expected
        assert isinstance(row["seq"], int)
    seqs = [row["seq"] for row in detail["events"] + detail["approval_events"]]
    assert len(seqs) == len(set(seqs)), "seq is unique per request_id"


# --------------------------------------------------------------------------- #
# C6 contract test 9 — per-route auth posture (§1, ADR-035)
# --------------------------------------------------------------------------- #
ROUTE_PENDING = (
    "needs the real C6 routes: sunil/api/routes/{tasks,activity,audit}.py "
    "(ARCHITECTURE_V2 §2 Amendment 1) + api/deps.py "
    "(require_owner_session / require_client_header / require_service_token) "
    "and a test client. Phase 2 production code, not a QA deliverable."
)

#: The five C6 operations, as paths (C6 OpenAPI ``paths``).
C6_PATHS = [
    "/api/v1/tasks",
    "/api/v1/tasks/{task_id}",
    "/api/v1/activity",
    "/api/v1/audit",
    "/api/v1/audit/{request_id}",
]


def ops_lane(*modules: str):
    """Import the named ops-lane modules, or skip with a loud reason (F5).

    While the modules are absent this skips; the moment they exist every test
    below runs and either asserts or fails — never a silent forever-skip.
    """
    from importlib import import_module  # noqa: PLC0415

    imported = []
    for module in modules:
        try:
            imported.append(import_module(module))
        except ModuleNotFoundError:
            pytest.skip(f"C6 route suite {ROUTE_PENDING} (missing: {module})")
    return imported if len(imported) > 1 else imported[0]


def pending(clause: str, assertions: str) -> None:
    """Fail with the assertion list this clause must grow, now that its modules
    exist. Deliberately a failure, not a skip: the debt is due."""
    pytest.fail(
        f"the ops lane now exists — C6 contract test 9 ({clause}) must be "
        f"written: {assertions}"
    )


def test_c6_9_no_c6_route_accepts_the_adr_035_service_bearer() -> None:
    """C6 §1 / ADR-035, structural half — the bearer dependency is registered on
    ``POST /api/v1/chat`` ALONE, so no C6 route can accept a service token. The
    walk matches ``require_service_token`` by FUNCTION IDENTITY through
    FastAPI's flattened dependency tree (the C5 test 8 pattern), which is what
    catches the dangerous version of this bug: a dependency added to a ROUTER
    rather than a route, making every path under it bearer-reachable.

    Full body, unlike its three siblings below: a route-table walk needs no
    request, no session and no fake.
    """
    main, deps = ops_lane("sunil.main", "sunil.api.deps")
    app = main.create_app()
    target = deps.require_service_token

    def uses(dependant, seen: set[int] | None = None) -> bool:
        if dependant is None:
            return False
        seen = seen if seen is not None else set()
        if id(dependant) in seen:
            return False
        seen.add(id(dependant))
        if getattr(dependant, "call", None) is target:
            return True
        return any(uses(child, seen) for child in getattr(dependant, "dependencies", []))

    bearer_routes = {
        route.path for route in app.routes if uses(getattr(route, "dependant", None))
    }

    assert bearer_routes & set(C6_PATHS) == set(), (
        "an ADR-035 bearer credential must never be valid on a C6 route "
        f"(C6 §1); found it registered on: {sorted(bearer_routes & set(C6_PATHS))}"
    )
    assert bearer_routes <= {"/api/v1/chat"}


def test_c6_9_the_five_operations_are_read_only() -> None:
    """C6 §1 — "No mutating verb exists on this surface; a POST/PUT/DELETE on
    these paths is 405 from the framework, not a handler." Asserted on the route
    table, so it holds without a request: each of the five paths is registered
    for GET only."""
    main = ops_lane("sunil.main", "sunil.api.routes.tasks")
    app = main.create_app() if hasattr(main, "create_app") else ops_lane("sunil.main").create_app()

    registered: dict[str, set[str]] = {}
    for route in app.routes:
        methods = {
            method
            for method in (getattr(route, "methods", None) or set())
            if method not in {"HEAD", "OPTIONS"}
        }
        if methods:
            registered.setdefault(route.path, set()).update(methods)

    for path in C6_PATHS:
        assert path in registered, f"{path} is not registered (C6 OpenAPI paths)"
        assert registered[path] == {"GET"}, (
            f"{path} must be GET-only (C6 §1); found {sorted(registered[path])}"
        )


#: The five C6 paths with their path parameters filled in. The ids name nothing
#: that exists: every assertion below is about a refusal that must happen BEFORE
#: the handler runs, so a 404 anywhere here would itself be the failure.
C6_REQUESTS = [
    path.replace("{task_id}", "task-1").replace("{request_id}", "req-1")
    for path in C6_PATHS
]


async def test_c6_9_no_session_is_401_on_every_operation() -> None:
    """C6 §1/§6 test 9, clause 1 — no session → 401 (``unauthenticated``) on all
    five operations.

    Body completed at integration-w1 by the backend lane, to QA's embedded
    assertion list, against the harness C6 §6 leaves to the implementer
    (``tests/ops_harness.py`` — the real ``create_app``, the real session
    middleware, the real dependencies; the cookie is absent because none was
    ever minted, not because one was deleted).

    ``Origin`` is sent, so this clause grades the SESSION check rather than the
    Origin decision C6 deliberately does not fix.
    """
    ops_lane("sunil.main", "sunil.api.deps", "fastapi.testclient")
    from tests.ops_harness import WEB_HEADERS, ops_client

    async with ops_client(sign_in=False) as (client, _app):
        for path in C6_REQUESTS:
            answered = await client.get(path, headers=WEB_HEADERS)
            assert answered.status_code == 401, f"{path}: {answered.text}"
            assert answered.json()["error"]["kind"] == "unauthenticated", path


async def test_c6_9_session_without_the_client_header_is_403_on_every_operation() -> None:
    """C6 §1/§6 test 9, clause 2 — a valid session without ``X-SUNIL-Client``
    → 403 (``forbidden_client``), the ADR-008 CSRF control, on all five.

    Body completed at integration-w1 (see clause 1). The session is real: minted
    by ``POST /api/v1/auth/login`` and signed by ADR-007's middleware, so the
    403 is the header control refusing a request that WOULD otherwise have been
    authorised — which is the only version of this test that proves anything.
    """
    ops_lane("sunil.main", "sunil.api.deps", "fastapi.testclient")
    from tests.ops_harness import WEB_ORIGIN, ops_client

    async with ops_client(sign_in=True) as (client, _app):
        for header in ({}, {"X-SUNIL-Client": "curl"}):
            for path in C6_REQUESTS:
                answered = await client.get(
                    path, headers={**header, "Origin": WEB_ORIGIN}
                )
                assert answered.status_code == 403, f"{path} {header}: {answered.text}"
                assert answered.json()["error"]["kind"] == "forbidden_client", path


async def test_c6_9_service_bearer_without_a_cookie_is_401_on_every_route() -> None:
    """C6 §1/§6 test 9, clause 3 — a VALID ``SUNIL_SERVICE_TOKEN`` bearer with no
    cookie → 401 on each C6 route (the ADR-035 structural-scope probe at request
    level, complementing C5 test 8 and the route-table walk above).

    Body completed at integration-w1 (see clause 1). The token is the one the
    app is configured with, so this grades the LANE and not a bad credential.
    Asserted with and without the browser headers: C6 §1 says "a bearer-only
    request is 401", and QA's list says never 403, so the bearer must be refused
    by the absent machine lane rather than by the CSRF pair — which is what
    ``routes/approvals.py::refuse_service_bearer`` now does.
    """
    ops_lane("sunil.main", "sunil.api.deps", "fastapi.testclient")
    from tests.ops_harness import SERVICE_TOKEN, WEB_HEADERS, ops_client

    bearer = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
    async with ops_client(service_token=SERVICE_TOKEN, sign_in=False) as (client, _app):
        for headers in (bearer, {**WEB_HEADERS, **bearer}):
            for path in C6_REQUESTS:
                answered = await client.get(path, headers=headers)
                assert answered.status_code == 401, f"{path}: {answered.text}"
                assert answered.json()["error"]["kind"] == "unauthenticated", path


# --------------------------------------------------------------------------- #
# C6 contract test 10 — byte-fidelity (§4 containment-by-shape)
# --------------------------------------------------------------------------- #
async def surfaces(store: FakeOpsStore) -> dict[str, object]:
    return {
        "list": await store.list_tasks(limit=LIMIT_MAX),
        "detail": await store.get_task("task-1"),
        "activity": await store.activity(),
        "audit_index": await store.list_audit_turns(limit=LIMIT_MAX),
        "audit_detail": await store.get_audit_turn("req-parked"),
    }


@pytest.mark.parametrize("surface", ["list", "detail", "activity"])
async def test_c6_10_untrusted_objective_is_byte_identical(
    store: FakeOpsStore, surface: str
) -> None:
    """C6 §4 — the server MUST NOT sanitise, escape or strip: the objective
    comes back byte-identical through list, detail and activity. A future
    "helpful" sanitiser fails here rather than silently hiding the raw value the
    owner is entitled to inspect."""
    payload = (await surfaces(store))[surface]

    def objectives(node) -> list[str]:
        if isinstance(node, dict):
            found = [node["objective"]] if "objective" in node else []
            return found + [o for value in node.values() for o in objectives(value)]
        if isinstance(node, list):
            return [o for value in node for o in objectives(value)]
        return []

    found = [value for value in objectives(payload) if "bold" in value]

    assert found, f"the untrusted objective did not appear in the {surface} surface"
    for value in found:
        assert value == UNTRUSTED_OBJECTIVE
        assert value.encode("utf-8") == UNTRUSTED_OBJECTIVE.encode("utf-8")


async def test_c6_10_untrusted_summary_and_detail_excerpt_survive_the_audit_read(
    store: FakeOpsStore,
) -> None:
    """C6 §4 — ``AuditEvent.summary`` (an ``approval_requested`` row carries the
    C4 summary verbatim) and an UNTRUSTED excerpt inside ``detail`` are returned
    byte-faithful; the detail excerpt keeps its raw JSON shape for the ``<pre>``
    renderer."""
    detail = await store.get_audit_turn("req-parked")
    requested = next(
        row for row in detail["approval_events"] if row["stage"] == "approval_requested"
    )
    excerpt_row = next(
        row
        for row in detail["events"] + detail["approval_events"]
        if row["detail"] and "excerpt" in row["detail"]
    )

    assert requested["summary"] == UNTRUSTED_SUMMARY
    assert excerpt_row["detail"]["excerpt"] == UNTRUSTED_EXCERPT
    assert excerpt_row["detail"]["excerpt"].encode("utf-8") == UNTRUSTED_EXCERPT.encode(
        "utf-8"
    )


async def test_c6_10_no_surface_escapes_encodes_or_strips_anything(
    store: FakeOpsStore,
) -> None:
    """The containment rule as one negative probe over every surface: the raw
    markup is present and NONE of the classic server-side "helpful" transforms
    (HTML entity encoding, backslash escaping, tag stripping) has happened."""
    blob = json.dumps(await surfaces(store), ensure_ascii=False, sort_keys=True)

    # Compared in their JSON-ENCODED form. A `"` inside a JSON string is escaped
    # by the SYNTAX of JSON — every conformant encoder does it and every parser
    # undoes it, so it is not a transform of the value. The transforms this test
    # exists to catch are not syntax: HTML entity encoding, \uXXXX escaping of
    # printable characters (ruled out by ensure_ascii=False), and tag stripping.
    # None of them survives either the comparison here or the sweep below.
    for raw in (UNTRUSTED_OBJECTIVE, UNTRUSTED_SUMMARY, UNTRUSTED_EXCERPT):
        assert json.dumps(raw, ensure_ascii=False)[1:-1] in blob
    for forbidden in ("&lt;", "&gt;", "&amp;", "&quot;", "&#", "\\u003c", "[removed]"):
        assert forbidden not in blob, f"a surface encoded the payload ({forbidden})"


async def test_c6_10_the_untrusted_fixtures_actually_carry_dangerous_bytes(
    store: FakeOpsStore,
) -> None:
    """A byte-fidelity probe is only a probe if the payload is hostile: each
    seeded string carries markup, a quote and a non-ASCII character, so an
    encoder of any kind changes it."""
    assert "<b>" in UNTRUSTED_OBJECTIVE and "](" in UNTRUSTED_OBJECTIVE
    assert "<script>" in UNTRUSTED_SUMMARY and '"' in UNTRUSTED_SUMMARY
    assert "onerror=" in UNTRUSTED_EXCERPT
    assert any(ord(char) > 127 for char in UNTRUSTED_SUMMARY + UNTRUSTED_EXCERPT)


# --------------------------------------------------------------------------- #
# House rule F1 — everything the fake returns is a deep copy
# --------------------------------------------------------------------------- #
async def test_c6_f1_task_pages_are_deep_copies(store: FakeOpsStore) -> None:
    """C6 §6(7) / the F1 lesson — a caller that mutates a returned page must not
    be able to change the store's answer to the next call. Asserted against a
    pre-mutation SNAPSHOT, never against the live seed (comparing to the seed is
    the assertion that passes while both sides rot)."""
    first = await store.list_tasks(limit=LIMIT_MAX)
    snapshot = deepcopy(first)

    first["tasks"][0]["objective"] = "MUTATED"
    first["tasks"][0]["status"] = "MUTATED"
    first["tasks"].clear()
    first["next_cursor"] = "MUTATED"

    second = await store.list_tasks(limit=LIMIT_MAX)
    assert second == snapshot
    assert store.tasks["task-33"]["objective"] != "MUTATED"


async def test_c6_f1_task_detail_and_status_events_are_deep_copies(
    store: FakeOpsStore,
) -> None:
    first = await store.get_task("task-9")
    snapshot = deepcopy(first)

    first["status_events"][0]["to_status"] = "MUTATED"
    first["status_events"].append({"from_status": None, "to_status": "x", "at": "x"})

    assert await store.get_task("task-9") == snapshot
    assert all(
        event["to_status"] != "MUTATED" for event in store.status_events
    )


async def test_c6_f1_activity_snapshots_are_deep_copies(store: FakeOpsStore) -> None:
    first = await store.activity()
    snapshot = deepcopy(first)

    first["running"][0]["latest_detail"]["tool"] = "MUTATED"
    first["recent"].pop()
    first["parked"][0]["objective"] = "MUTATED"

    assert await store.activity() == snapshot


async def test_c6_f1_audit_reads_are_deep_copies(store: FakeOpsStore) -> None:
    index = await store.list_audit_turns(limit=LIMIT_MAX)
    detail = await store.get_audit_turn("req-parked")
    index_snapshot, detail_snapshot = deepcopy(index), deepcopy(detail)

    index["turns"][0]["stage_count"] = -1
    detail["events"][0]["summary"] = "MUTATED"
    detail["approval_events"][2]["detail"]["resumed_from_approval_id"] = "MUTATED"

    assert await store.list_audit_turns(limit=LIMIT_MAX) == index_snapshot
    assert await store.get_audit_turn("req-parked") == detail_snapshot
    assert all(row["summary"] != "MUTATED" for row in store.audit_rows)


# --------------------------------------------------------------------------- #
# Determinism — the fixture is the same fixture on every run and machine
# --------------------------------------------------------------------------- #
async def test_c6_fixture_is_deterministic_across_instances() -> None:
    """C6 §6 — "Fixture … deterministic". Two independent builds agree on every
    byte of every surface, so a CI failure is a real failure and never seeding
    order, clock drift or dict iteration."""
    first, second = ops_fixture(), ops_fixture()

    assert await surfaces(first) == await surfaces(second)
    assert first.tasks == second.tasks
    assert first.audit_rows == second.audit_rows
    assert first.status_events == second.status_events
    assert first.conversations == second.conversations


async def test_c6_fixture_seeds_the_shapes_the_contract_names(
    store: FakeOpsStore,
) -> None:
    """C6 §6's fixture clauses, pinned so a future edit cannot quietly remove
    the coverage the ten tests depend on."""
    assert len(store.tasks) == TOTAL_TASKS
    parked = [row for row in store.tasks.values() if row["status"] == "parked"]
    failed = [row for row in store.tasks.values() if row["status"] == "failed"]

    assert any(row["approval_id"] == "apr-1" for row in parked)
    assert len([row for row in failed if row["failure_kind"]]) >= 2
    assert {row["failure_kind"] for row in failed} >= {"provider_error", "tool_failed"}
    assert {row["project_key"] for row in store.tasks.values()} == {
        "sunil",
        "easyclean",
        None,
    }
    assert sum(1 for row in store.tasks.values() if row["status"] in {"completed", "failed"}) == 27
