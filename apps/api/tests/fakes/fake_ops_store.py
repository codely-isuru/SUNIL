"""``FakeOpsStore`` — C6 §6's fake specification, verbatim.

Source of truth: ``docs/contracts/C6-ops-reads.md`` v1.0.0 (FROZEN 2026-09-11)
and its OpenAPI companion. This module is THE ops-reads fake: Stream D builds
the Tasks, Agent-activity and Audit views against it, and the C6 contract suite
(``tests/contracts/test_c6_ops_reads.py``) pins the §2 laws against it.

House rules carried from the P0 fakes round:

* **F1 — deep copy.** Every page, snapshot and detail the store returns is a
  ``deepcopy``. A caller that mutates a result cannot change the store's answer
  to the next call, and cannot reach into the seeds.
* **F2 — no Protocol inheritance.** ``FakeOpsStore`` does NOT inherit
  ``OpsReadStore``; the module-level ``_check`` assignment at the bottom is the
  static conformance witness, and ``test_fake_conformance.py`` is the runtime
  one. Inheriting a Protocol would give the fake inherited ``...`` bodies that
  silently return ``None``.
* **F8 — one pagination law.** Order is ``created_at desc, id desc`` with
  **plain string** id comparison (``task-9`` above ``task-10``); the cursor is
  the last row's sort id; ``next_cursor`` is null **iff the page is short**, so
  an exactly-full final page still returns a cursor and the walk ends on a
  following empty page; an unknown cursor raises ``ValueError`` (the HTTP
  layer's 422), never a silent page one.

Clock convention (C6 §6 "each advances the clock +1 s unless an explicit
timestamp is passed"): a seed helper **stamps with the current clock value and
then advances one second**; passing an explicit timestamp stamps with that value
and does not advance. Whole seconds only, so every fixture timestamp is
byte-stable across runs and machines.

Validation lives at the store seam, exactly as C6 §5 says: ``ValueError`` for
everything the HTTP layer must turn into a 422 (unknown cursor, out-of-enum
filter, out-of-range limit), ``None`` from the two getters for the 404. The fake
never raises for absence.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tests.fakes.clock import FakeClock
from tests.fakes.ops_seam import OpsReadStore

# --------------------------------------------------------------------------- #
# Vocabularies — each transcribed from a frozen document, not invented here
# --------------------------------------------------------------------------- #
#: ``TaskStatus`` (C6 OpenAPI): the M1 four plus V2's ``parked`` (ADR-031).
TASK_STATUSES: tuple[str, ...] = (
    "pending",
    "in_progress",
    "completed",
    "failed",
    "parked",
)

#: ``AuditTurn.outcome`` (C6 OpenAPI) = C5's three outcomes.
OUTCOMES: tuple[str, ...] = ("ok", "failed", "parked")

#: ``listTasks``'s ``order`` enum (C6 OpenAPI). The only sort control.
ORDERS: tuple[str, ...] = ("newest", "oldest")

#: The twelve NFR-020 spine names, in order (``M1_BUILD_PLAN.md`` §"stage ∈",
#: V2_DASHBOARD_SPEC §10.2 table). ``stage_count`` counts these and only these.
#: Note what is NOT here: ``tool_call`` is the CONTINUATION's row name
#: (ARCHITECTURE_V2 §6 Leg 6), not a spine stage — while ``tool_result`` IS a
#: spine stage and also occurs on a continuation row. That overlap is what makes
#: the §2.4 partition-by-lineage rule observable instead of decorative.
SPINE_STAGES: tuple[str, ...] = (
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

#: C6 §2.4 — the approval lifecycle kinds. A row with one of these stages is an
#: episode row by NAME; a row whose ``detail`` carries
#: ``resumed_from_approval_id`` is one by LINEAGE (C4 §3).
APPROVAL_LIFECYCLE_STAGES: frozenset[str] = frozenset(
    {
        "approval_requested",
        "approval_approved",
        "approval_refused",
        "approval_expired",
        "continuation_reconciled",
    }
)

#: C6 §2.3 — ``latest_detail`` is the projection onto exactly these keys.
#: Everything else in the audit row's ``detail`` is dropped: audit ``detail`` may
#: embed untrusted excerpts, and this projection is what keeps the activity
#: endpoint's trusted-detail promise true.
PROJECTION_KEYS: frozenset[str] = frozenset(
    {"project_display_name", "tool", "operation"}
)

#: C4 §6.5 / C6 §2.1(5) pagination bounds.
LIMIT_MIN = 1
LIMIT_MAX = 200
DEFAULT_LIMIT = 50

#: C6 §2.3 — ``recent`` is capped at the 20 most recent (spec §7.1).
RECENT_CAP = 20

#: The thirteen always-present ``Task`` keys (C6 OpenAPI ``Task.required``).
#: Absence is expressed as null, never as a missing key.
TASK_KEYS: tuple[str, ...] = (
    "id",
    "objective",
    "status",
    "assigned_agent",
    "priority",
    "project_key",
    "request_id",
    "conversation_id",
    "approval_id",
    "created_at",
    "started_at",
    "completed_at",
    "failure_kind",
)

#: The seven ``AuditEvent`` keys (C6 OpenAPI). ``request_id`` is the grouping
#: column and is deliberately NOT one of them — it is on the turn, not the row.
AUDIT_EVENT_KEYS: tuple[str, ...] = (
    "seq",
    "stage",
    "actor",
    "summary",
    "detail",
    "at",
    "task_id",
)

# --------------------------------------------------------------------------- #
# Untrusted seeds — C6 §4's byte-fidelity probes
# --------------------------------------------------------------------------- #
# Each string carries markup, an attribute-breaking quote and (for two of them) a
# non-ASCII character, so ANY server-side "help" — HTML entity encoding, unicode
# escaping, tag stripping — changes the bytes and fails contract test 10. The
# server must return them byte-faithful; containment is a rendering duty.
#: ``Task.objective`` — UNTRUSTED plan text (spec §7.2). C6 §6's literal value.
UNTRUSTED_OBJECTIVE = "<b>bold</b> [x](http://x.invalid)"
#: ``AuditEvent.summary`` on an ``approval_requested`` row — carries the C4
#: summary verbatim, so it is UNTRUSTED-INFLUENCED.
UNTRUSTED_SUMMARY = 'Approve <script>alert("pwned")</script> for café Ezy'
#: A truncated UNTRUSTED excerpt inside ``AuditEvent.detail``
#: (ARCHITECTURE_V1 §3.4, T-32).
UNTRUSTED_EXCERPT = '<img src=x onerror="fetch(\'//x.invalid\')"> naïve'

#: The equal ``created_at`` shared by ``task-9`` and ``task-10`` — the deliberate
#: lexicographic tie. The seed helpers advance one second per row, so a tie can
#: only be built with the explicit-timestamp override.
TIE_AT = "2026-01-01T00:00:08Z"

#: The activity projection leak probe (C6 §6 test 5): the seeded ``detail``
#: carries a key beside ``tool`` that MUST NOT survive the projection.
PROJECTION_PROBE_TASK = "task-8"
PROJECTION_PROBE_DETAIL: dict[str, Any] = {"tool": "github_mcp", "secret_excerpt": "x"}


class FakeOpsStore:
    """C6 §6 fake. In-memory, deterministic, no HTTP, no database."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        self._clock = clock if clock is not None else FakeClock()
        #: task_id -> the thirteen-key Task row, in insertion order.
        self.tasks: dict[str, dict[str, Any]] = {}
        #: every audit row, each carrying its ``request_id`` beside the seven
        #: AuditEvent keys.
        self.audit_rows: list[dict[str, Any]] = []
        #: every status transition, each carrying its ``task_id``.
        self.status_events: list[dict[str, Any]] = []
        #: request_id -> conversation_id, fed by ``add_task``.
        self.conversations: dict[str, str] = {}
        self._next_task_number = 1

    # ----------------------------------------------------------------- #
    # Clock
    # ----------------------------------------------------------------- #
    def _stamp(self, explicit: str | None) -> str:
        """Stamp with the clock and advance, unless an explicit value is given."""
        if explicit is not None:
            return explicit
        moment = self._clock.iso()
        self._clock.advance(seconds=1)
        return moment

    # ----------------------------------------------------------------- #
    # Seed helpers (C6 §6 items 1-3)
    # ----------------------------------------------------------------- #
    def add_task(
        self,
        objective: str,
        *,
        status: str = "pending",
        assigned_agent: str = "project_manager",
        priority: str = "normal",
        project_key: str | None = None,
        request_id: str,
        conversation_id: str,
        approval_id: str | None = None,
        created_at: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        failure_kind: str | None = None,
    ) -> str:
        """Seed one task; ids are ``task-1``, ``task-2``, … in call order."""
        task_id = f"task-{self._next_task_number}"
        self._next_task_number += 1
        moment = self._stamp(created_at)
        self.tasks[task_id] = {
            "id": task_id,
            "objective": objective,
            "status": status,
            "assigned_agent": assigned_agent,
            "priority": priority,
            "project_key": project_key,
            "request_id": request_id,
            "conversation_id": conversation_id,
            "approval_id": approval_id,
            "created_at": moment,
            "started_at": started_at,
            "completed_at": completed_at,
            "failure_kind": failure_kind,
        }
        self.conversations[request_id] = conversation_id
        # The creation event: from_status is null (C6 §2.2).
        self.status_events.append(
            {
                "task_id": task_id,
                "from_status": None,
                "to_status": status,
                "at": moment,
            }
        )
        return task_id

    def add_status_event(
        self,
        task_id: str,
        from_status: str | None,
        to_status: str,
        at: str | None = None,
    ) -> None:
        """Seed a transition; also materialises the task's current status."""
        self.status_events.append(
            {
                "task_id": task_id,
                "from_status": from_status,
                "to_status": to_status,
                "at": self._stamp(at),
            }
        )
        self.tasks[task_id]["status"] = to_status

    def add_audit_row(
        self,
        request_id: str,
        stage: str,
        *,
        actor: str = "core",
        summary: str = "",
        detail: dict[str, Any] | None = None,
        task_id: str | None = None,
        at: str | None = None,
    ) -> int:
        """Seed one audit row; ``seq`` auto-increments per ``request_id`` from 1."""
        seq = 1 + sum(1 for row in self.audit_rows if row["request_id"] == request_id)
        self.audit_rows.append(
            {
                "request_id": request_id,
                "seq": seq,
                "stage": stage,
                "actor": actor,
                "summary": summary,
                # deepcopy on the way IN as well: a caller that keeps a handle on
                # the dict it passed must not be able to edit the seed later.
                "detail": deepcopy(detail),
                "at": self._stamp(at),
                "task_id": task_id,
            }
        )
        return seq

    # ----------------------------------------------------------------- #
    # The §2.1 pagination law — one implementation, used by both indexes
    # ----------------------------------------------------------------- #
    @staticmethod
    def _check_limit(limit: int) -> None:
        # bool is an int subclass; a True slipping in here would page by one row.
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError(f"limit must be an integer, got {limit!r}")
        if not LIMIT_MIN <= limit <= LIMIT_MAX:
            raise ValueError(
                f"limit must be {LIMIT_MIN}..{LIMIT_MAX} (C6 §2.1), got {limit}"
            )

    @staticmethod
    def _paginate(
        ordered: list[dict[str, Any]], id_key: str, limit: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """C6 §2.1(2)(3)(4) on an already-filtered, already-ordered list.

        The cursor is resolved INSIDE the filtered set, so a walk is a walk over
        that set and a cursor from another filter is unknown here — a 422, not a
        silent restart at page one.
        """
        if cursor is not None:
            position = next(
                (
                    index
                    for index, row in enumerate(ordered)
                    if row[id_key] == cursor
                ),
                None,
            )
            if position is None:
                raise ValueError(
                    f"unknown cursor {cursor!r} for the current filters (C6 §2.1)"
                )
            ordered = ordered[position + 1 :]
        page = ordered[:limit]
        # Null ONLY when the page is short. An exactly-full final page returns a
        # cursor and the client learns it is done from the following empty page.
        next_cursor = page[-1][id_key] if len(page) == limit else None
        return page, next_cursor

    # ----------------------------------------------------------------- #
    # listTasks
    # ----------------------------------------------------------------- #
    async def list_tasks(
        self,
        *,
        status: str | None = None,
        project_key: str | None = None,
        q: str | None = None,
        order: str = "newest",
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._check_limit(limit)
        if order not in ORDERS:
            raise ValueError(f"order must be one of {ORDERS}, got {order!r}")
        if status is not None and status not in TASK_STATUSES:
            raise ValueError(f"status must be one of {TASK_STATUSES}, got {status!r}")

        rows = list(self.tasks.values())
        # Filters compose with AND, and apply BEFORE ordering and pagination.
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        if project_key is not None:
            # Exact match. A null project_key never matches a keyed filter.
            rows = [row for row in rows if row["project_key"] == project_key]
        if q is not None:
            needle = q.lower()
            rows = [row for row in rows if needle in row["objective"].lower()]

        newest = order == "newest"
        rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=newest)
        page, next_cursor = self._paginate(rows, "id", limit, cursor)
        return deepcopy({"tasks": page, "next_cursor": next_cursor})

    # ----------------------------------------------------------------- #
    # getTask
    # ----------------------------------------------------------------- #
    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        task = self.tasks.get(task_id)
        if task is None:
            return None
        # Ascending `at`; ties keep write order, so the sort must be stable and
        # must key on `at` alone.
        events = [
            {key: event[key] for key in ("from_status", "to_status", "at")}
            for event in self.status_events
            if event["task_id"] == task_id
        ]
        events.sort(key=lambda event: event["at"])
        return deepcopy({**task, "status_events": events})

    # ----------------------------------------------------------------- #
    # getActivity
    # ----------------------------------------------------------------- #
    def _latest_audit_row(self, request_id: str) -> dict[str, Any] | None:
        """The HIGHEST-seq audit row for the request_id — not the first row and
        not the last one written."""
        rows = [row for row in self.audit_rows if row["request_id"] == request_id]
        return max(rows, key=lambda row: row["seq"]) if rows else None

    def _activity_item(self, task: dict[str, Any]) -> dict[str, Any]:
        latest = self._latest_audit_row(task["request_id"])
        detail = (latest or {}).get("detail") or {}
        return {
            **task,
            "latest_stage": latest["stage"] if latest else None,
            "latest_stage_at": latest["at"] if latest else None,
            # A key ALLOW-LIST, never a deny-list: a detail key nobody thought of
            # cannot leak through an allow-list.
            "latest_detail": {
                key: value for key, value in detail.items() if key in PROJECTION_KEYS
            },
        }

    async def activity(self) -> dict[str, Any]:
        def partition(statuses: set[str]) -> list[dict[str, Any]]:
            rows = [row for row in self.tasks.values() if row["status"] in statuses]
            # The ONE ordering law, on all three lists. It does not consult
            # completed_at, so a failed row without one still sorts correctly.
            rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
            return [self._activity_item(row) for row in rows]

        return deepcopy(
            {
                "running": partition({"pending", "in_progress"}),
                "parked": partition({"parked"}),
                # Truncated to 20 AFTER ordering, so the rows that fall off are
                # the oldest ones.
                "recent": partition({"completed", "failed"})[:RECENT_CAP],
            }
        )

    # ----------------------------------------------------------------- #
    # listAuditTurns / getAuditTurn
    # ----------------------------------------------------------------- #
    def _rows_for(self, request_id: str) -> list[dict[str, Any]]:
        rows = [row for row in self.audit_rows if row["request_id"] == request_id]
        rows.sort(key=lambda row: row["seq"])
        return rows

    @staticmethod
    def _is_episode_row(row: dict[str, Any]) -> bool:
        """C6 §2.4 — an episode row by lifecycle NAME or by C4 §3 LINEAGE."""
        if row["stage"] in APPROVAL_LIFECYCLE_STAGES:
            return True
        return (row["detail"] or {}).get("resumed_from_approval_id") is not None

    def _task_for(self, request_id: str) -> dict[str, Any] | None:
        return next(
            (row for row in self.tasks.values() if row["request_id"] == request_id),
            None,
        )

    def _turn(self, request_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """The §2.4 derivation table, as code."""
        first = next(
            (row for row in rows if row["stage"] == "final_response"), None
        )
        plan = next((row for row in rows if row["stage"] == "plan_created"), None)
        final_detail = (first or {}).get("detail") or {}
        task = self._task_for(request_id)
        conversation_id = self.conversations.get(request_id)
        if conversation_id is None and task is not None:
            conversation_id = task["conversation_id"]
        return {
            "request_id": request_id,
            # The turn's FIRST row is the lowest seq — rows are seq-sorted.
            "started_at": rows[0]["at"],
            # Null while in flight. For a parked turn this is NOT the last row:
            # the continuation's rows come after it.
            "ended_at": first["at"] if first else None,
            # Spine names only, and only on rows that are not part of the
            # approval episode — so the view's "n of 12" reading stays honest.
            "stage_count": sum(
                1
                for row in rows
                if row["stage"] in SPINE_STAGES and not self._is_episode_row(row)
            ),
            "outcome": final_detail.get("outcome"),
            "failure_kind": final_detail.get("failure_kind"),
            "agent": ((plan or {}).get("detail") or {}).get("agent"),
            "conversation_id": conversation_id,
            "task_id": task["id"] if task else None,
        }

    def _turns(self) -> list[dict[str, Any]]:
        # dict preserves insertion order, so grouping is deterministic before the
        # sort even runs.
        request_ids: list[str] = list(
            dict.fromkeys(row["request_id"] for row in self.audit_rows)
        )
        return [
            self._turn(request_id, self._rows_for(request_id))
            for request_id in request_ids
        ]

    async def list_audit_turns(
        self,
        *,
        request_id: str | None = None,
        from_at: str | None = None,
        to_at: str | None = None,
        outcome: str | None = None,
        agent: str | None = None,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._check_limit(limit)
        if outcome is not None and outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")

        turns = self._turns()
        if request_id is not None:
            turns = [turn for turn in turns if turn["request_id"] == request_id]
        if from_at is not None:  # half-open: from <= started_at
            turns = [turn for turn in turns if turn["started_at"] >= from_at]
        if to_at is not None:  # half-open: started_at < to
            turns = [turn for turn in turns if turn["started_at"] < to_at]
        if outcome is not None:
            turns = [turn for turn in turns if turn["outcome"] == outcome]
        if agent is not None:
            turns = [turn for turn in turns if turn["agent"] == agent]

        turns.sort(
            key=lambda turn: (turn["started_at"], turn["request_id"]), reverse=True
        )
        page, next_cursor = self._paginate(turns, "request_id", limit, cursor)
        return deepcopy({"turns": page, "next_cursor": next_cursor})

    async def get_audit_turn(self, request_id: str) -> dict[str, Any] | None:
        rows = self._rows_for(request_id)
        if not rows:
            return None
        events, episode = [], []
        for row in rows:
            projected = {key: row[key] for key in AUDIT_EVENT_KEYS}
            (episode if self._is_episode_row(row) else events).append(projected)
        return deepcopy(
            {
                "events": events,
                # NULL, not an empty list, when the turn had no episode: the view
                # renders its second segment only when the key is non-null.
                "approval_events": episode or None,
            }
        )


#: F2 static conformance witness — a type checker reads this as "FakeOpsStore
#: must satisfy OpsReadStore", and it proves the fake constructs at import time.
#: ``test_fake_conformance.py`` pins it so it cannot be dropped as "unused".
_check: OpsReadStore = FakeOpsStore()


# --------------------------------------------------------------------------- #
# The fixture (C6 §6 "Fixture") — deterministic, no randomness, no wall clock
# --------------------------------------------------------------------------- #
def ops_fixture() -> FakeOpsStore:
    """Build C6 §6's fixture: 33 tasks and five audit turns.

    Layout, and why each piece is here:

    * ``task-1``…``task-12`` cover every ``TaskStatus``, a ``project_key`` mix of
      ``sunil``/``easyclean``/None, a parked row carrying ``apr-1``, and two
      failed rows carrying C5 failure kinds.
    * ``task-9``/``task-10`` share ``TIE_AT`` — the deliberate lexicographic
      tie, which is the only way to observe that ``task-9`` sorts ABOVE
      ``task-10``.
    * ``task-13``…``task-33`` are 21 terminal filler tasks, so the activity
      ``recent`` cap of 20 has something to cut.
    * Five audit turns: ``req-full`` (all twelve spine stages), ``req-parked``
      (spine rows + an approval episode + a continuation), ``req-live`` (in
      flight), ``req-proj`` (the projection leak probe) and ``req-failed`` (the
      failed-outcome derivations). C6 §6 names the first three; the last two are
      the minimum needed to probe §2.4's ``outcome``/``agent`` filters and the
      projection allow-list, which the ten tests require.

    The timeline is a consequence of the one-second cadence: the 33 task rows
    consume ``00:00:00``…``00:00:31`` (``task-9``'s explicit ``TIE_AT`` spends no
    tick), so the audit rows run from ``00:00:32``.
    """
    store = FakeOpsStore()

    # -- task-1 … task-12: the status/project/tie coverage ----------------- #
    # Objectives are chosen so that `q` probes mean something: exactly two rows
    # mention invoices (one lower-case, one UPPER), exactly two are tie rows, and
    # NO objective contains "project_manager", "easyclean", "task-1" or
    # "req-full" — the four values contract test 3 proves `q` does not search.
    store.add_task(  # task-1 — the untrusted markup row, and the no-audit row
        UNTRUSTED_OBJECTIVE,
        status="pending",
        project_key="sunil",
        request_id="req-t1",
        conversation_id="conv-1",
    )
    store.add_task(  # task-2
        "Draft the weekly status summary",
        status="in_progress",
        project_key="sunil",
        request_id="req-t2",
        conversation_id="conv-2",
        started_at="2026-01-01T00:00:30Z",
    )
    store.add_task(  # task-3 — walked by req-full; two tied status events
        "Reconcile the invoices for March",
        status="pending",
        project_key="easyclean",
        request_id="req-full",
        conversation_id="conv-3",
        started_at="2026-01-01T00:00:33Z",
        completed_at="2026-01-01T00:00:43Z",
    )
    store.add_task(  # task-4
        "Migrate the staging database",
        status="failed",
        project_key="easyclean",
        request_id="req-t4",
        conversation_id="conv-4",
        started_at="2026-01-01T00:00:20Z",
        completed_at="2026-01-01T00:00:25Z",
        failure_kind="provider_error",
    )
    store.add_task(  # task-5 — the parked row, linked to the C4 approval
        "Deploy the pricing change",
        status="parked",
        project_key="sunil",
        request_id="req-parked",
        conversation_id="conv-5",
        approval_id="apr-1",
        started_at="2026-01-01T00:00:45Z",
    )
    store.add_task(  # task-6 — UPPER-case invoices
        "Chase overdue INVOICES from the portal",
        status="failed",
        request_id="req-t6",
        conversation_id="conv-6",
        started_at="2026-01-01T00:00:21Z",
        completed_at="2026-01-01T00:00:26Z",
        failure_kind="tool_failed",
    )
    store.add_task(  # task-7 — its request_id has NO audit rows (a 404 probe)
        "Rotate the signing keys",
        status="completed",
        request_id="req-t7",
        conversation_id="conv-7",
        started_at="2026-01-01T00:00:22Z",
        completed_at="2026-01-01T00:00:27Z",
    )
    store.add_task(  # task-8 — the activity projection leak probe
        "Prepare the quarterly board pack",
        status="pending",
        project_key="easyclean",
        request_id="req-proj",
        conversation_id="conv-8",
    )
    store.add_task(  # task-9 — the tie's first half, seeded EXPLICITLY
        "Tie row A, seeded with an equal timestamp",
        status="pending",
        project_key="sunil",
        request_id="req-t9",
        conversation_id="conv-9",
        created_at=TIE_AT,
        started_at="2026-01-01T00:00:29Z",
    )
    store.add_task(  # task-10 — the tie's second half, from the clock
        "Tie row B, seeded from the clock",
        status="parked",
        request_id="req-t10",
        conversation_id="conv-10",
    )
    store.add_task(  # task-11
        "Publish the release notes",
        status="completed",
        project_key="easyclean",
        request_id="req-t11",
        conversation_id="conv-11",
        started_at="2026-01-01T00:00:23Z",
        completed_at="2026-01-01T00:00:28Z",
    )
    store.add_task(  # task-12 — walked by req-failed
        "Import the supplier catalogue",
        status="failed",
        assigned_agent="developer",
        project_key="sunil",
        request_id="req-failed",
        conversation_id="conv-12",
        started_at="2026-01-01T00:01:05Z",
        completed_at="2026-01-01T00:01:07Z",
        failure_kind="tool_failed",
    )

    # ``task-10`` must land on the same second as ``task-9``'s explicit TIE_AT —
    # that equality IS the tie the order law is tested against. Checked rather
    # than assumed: if the seeding cadence above ever changes, this fails here
    # with a clear reason instead of surfacing as a baffling order-law failure.
    if store.tasks["task-10"]["created_at"] != TIE_AT:
        raise AssertionError(
            "ops_fixture: task-10 was expected to land on TIE_AT "
            f"({TIE_AT}) but landed on {store.tasks['task-10']['created_at']} — "
            "the one-second seeding cadence above changed, so the deliberate "
            "lexicographic tie no longer exists"
        )

    # -- transitions (all with explicit `at`, so they spend no clock tick) -- #
    # task-3: two transitions sharing ONE timestamp — only a stable sort keyed on
    # `at` alone reproduces the real timeline.
    store.add_status_event("task-3", "pending", "in_progress", at="2026-01-01T00:02:00Z")
    store.add_status_event(
        "task-3", "in_progress", "completed", at="2026-01-01T00:02:00Z"
    )
    # task-9: written in REVERSE `at` order, so a fake that returned write order
    # instead of `at` order is caught.
    store.add_status_event("task-9", "parked", "in_progress", at="2026-01-01T00:03:00Z")
    store.add_status_event(
        "task-9", "pending", "in_progress", at="2026-01-01T00:02:30Z"
    )

    # -- task-13 … task-33: 21 terminal fillers for the recent cap --------- #
    # Odd ids completed, even ids failed. The failed ones deliberately carry NO
    # completed_at: C6 §2.3 says the partition must not depend on it.
    for number in range(13, 34):
        completed = number % 2 == 1
        store.add_task(
            f"Filler terminal task number {number}",
            status="completed" if completed else "failed",
            request_id=f"req-t{number}",
            conversation_id=f"conv-{number}",
            completed_at="2026-01-01T00:00:31Z" if completed else None,
            failure_kind=None if completed else "provider_error",
        )

    # -- req-full: a clean twelve-stage turn (00:00:32 … 00:00:43) --------- #
    for index, stage in enumerate(SPINE_STAGES):
        detail: dict[str, Any] | None = None
        if stage == "plan_created":
            detail = {
                "agent": "project_manager",
                "project_key": "easyclean",
                "project_display_name": "EasyClean",
            }
        elif stage == "final_response":
            detail = {"outcome": "ok"}
        store.add_audit_row(
            "req-full",
            stage,
            summary=f"{stage} on the clean turn",
            detail=detail,
            # The task exists from plan_created onwards.
            task_id="task-3" if index >= SPINE_STAGES.index("plan_created") else None,
        )

    # -- req-parked: ten spine rows + an approval episode (00:00:44 … :57) - #
    # seq 1-9 are spine rows; permission_decision is absent because the first
    # tool needed no decision, and the SECOND tool's decision is the approval
    # episode itself (ARCHITECTURE_V2 §6 Leg 3).
    for stage in (
        "message_received",
        "context_loaded",
        "memory_retrieved",
        "model_selected",
        "llm_io",
        "plan_created",
        "agent_started",
        "tool_requested",
        "tool_result",
    ):
        store.add_audit_row(
            "req-parked",
            stage,
            summary=f"{stage} before the park",
            detail=(
                {
                    "agent": "project_manager",
                    "project_key": "sunil",
                    "project_display_name": "SUNIL",
                }
                if stage == "plan_created"
                else None
            ),
            task_id="task-5",
        )
    store.add_audit_row(  # seq 10 — episode by lifecycle NAME
        "req-parked",
        "approval_requested",
        actor="approvals",
        summary=UNTRUSTED_SUMMARY,
        detail={"approval_id": "apr-1", "tool": "github_mcp", "operation": "create_issue"},
        task_id="task-5",
    )
    store.add_audit_row(  # seq 11 — the turn ends parked, BEFORE the episode ends
        "req-parked",
        "final_response",
        summary="parked awaiting your decision",
        detail={"outcome": "parked"},
        task_id="task-5",
    )
    store.add_audit_row(  # seq 12 — episode by lifecycle NAME
        "req-parked",
        "approval_approved",
        actor="approvals",
        summary="you approved the tool call",
        detail={"approval_id": "apr-1", "decision": "approve"},
        task_id="task-5",
    )
    store.add_audit_row(  # seq 13 — episode by LINEAGE; tool_call is NOT a spine name
        "req-parked",
        "tool_call",
        actor="continuation",
        summary="continuation called the tool",
        detail={
            "resumed_from_approval_id": "apr-1",
            "tool": "github_mcp",
            "operation": "create_issue",
        },
        task_id="task-5",
    )
    store.add_audit_row(  # seq 14 — episode by LINEAGE, on a SPINE name
        "req-parked",
        "tool_result",
        actor="continuation",
        summary="continuation got a result",
        detail={
            "resumed_from_approval_id": "apr-1",
            "ok": True,
            # All three contracted keys, so the activity projection has something
            # to PASS on this row as well as an untrusted excerpt to DROP.
            "project_display_name": "SUNIL",
            "tool": "github_mcp",
            "operation": "create_issue",
            "excerpt": UNTRUSTED_EXCERPT,
        },
        task_id="task-5",
    )

    # -- req-live: in flight, no plan, no task (00:00:58 … 00:01:02) ------- #
    for stage in (
        "message_received",
        "context_loaded",
        "memory_retrieved",
        "model_selected",
        "llm_io",
    ):
        store.add_audit_row("req-live", stage, summary=f"{stage} in flight")

    # -- req-proj: one row, the projection leak probe (00:01:03) ----------- #
    store.add_audit_row(
        "req-proj",
        "tool_requested",
        summary="asked to use a tool",
        detail=PROJECTION_PROBE_DETAIL,
        task_id="task-8",
    )

    # -- req-failed: the failed-outcome derivations (00:01:04 … 00:01:07) -- #
    store.add_audit_row(
        "req-failed", "message_received", summary="received", task_id="task-12"
    )
    store.add_audit_row(
        "req-failed",
        "plan_created",
        summary="planned",
        detail={
            "agent": "developer",
            "project_key": "sunil",
            "project_display_name": "SUNIL",
        },
        task_id="task-12",
    )
    store.add_audit_row(
        "req-failed",
        "tool_requested",
        summary="asked to use a tool",
        detail={"tool": "github_mcp", "operation": "create_issue"},
        task_id="task-12",
    )
    store.add_audit_row(
        "req-failed",
        "final_response",
        summary="the tool failed",
        # Carries all three contracted keys AND an untrusted excerpt, so the
        # activity projection has something to pass and something to drop.
        detail={
            "outcome": "failed",
            "failure_kind": "tool_failed",
            "project_display_name": "SUNIL",
            "tool": "github_mcp",
            "operation": "create_issue",
            "excerpt": UNTRUSTED_EXCERPT,
        },
        task_id="task-12",
    )

    return store
