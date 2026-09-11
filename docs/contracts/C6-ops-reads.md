# C6 — Ops reads: rationale, derivations, and fake

**Version:** 1.0.0 · **Status:** FROZEN (Phase 1 / Stream D precursor, 2026-09-11) ·
**Owner:** Solution Architect
**OpenAPI:** [`C6-ops-reads-openapi.yaml`](C6-ops-reads-openapi.yaml) (the HTTP surface).
**Consumers:** Stream D (Tasks §8, Agent activity §7, Audit browser §10, Dashboard §16 of
`V2_DASHBOARD_SPEC.md`), QA (fake + contract suite).
**Provenance:** the shapes are `V2_DASHBOARD_SPEC.md` §13.1–13.3 **verbatim**, frozen by the
owner's Gate 2 ruling on Q1 (2026-09-11: freeze, do not cut). This document adds only what a
shape cannot carry: derivation rules, ordering/pagination law, the Q2 ruling, and the fake.
**Related decisions:** ADR-036 (this freeze + rejected alternatives), ADR-031 (parked tasks),
ADR-035 (why there is no bearer lane here), ADR-023 (the twelve-stage spine does not grow).

---

## 1. Scope and posture (normative)

- **Read-only.** Five operations, all `GET`: `listTasks`, `getTask`, `getActivity`,
  `listAuditTurns`, `getAuditTurn`. No mutating verb exists on this surface; a `POST`/`PUT`/
  `DELETE` on these paths is 405 from the framework, not a handler.
- **Owner-session only** — the exact C4 lane: `sessionCookie` (`sunil_session`, ADR-007) +
  `X-SUNIL-Client: web` + Origin check (ADR-008). The ADR-035 service bearer is **never** valid
  here (it is registered on `POST /api/v1/chat` alone, structurally); a bearer-only request is
  401. C5 contract test 8 (route-table walk) is the structural guarantee; C6 test 9 probes it
  per route.
- **Error envelope** = C4's `ErrorResponse` (`unauthenticated`, `forbidden_client`, `not_found`,
  `validation_error`). No 409 — nothing here has state to conflict with.
- **Raw material:** `tasks`, `task_status_events`, `audit_events` (`ARCHITECTURE_V1.md` §7.3 —
  carried into V2), plus the Q2 column (§3). C6 never exposes `params_redacted`, continuation
  state, or any C4 field beyond `approval_id` linkage.

## 2. The three surfaces — semantics the shapes cannot say

### 2.1 Ordering and pagination — ONE law, C4 §6.5's, as QA pinned it

The C4 fakes round (F8, `docs/tasks/P0-fakes.md`) pinned the literal reading of C4 §6.5 and
Stream D builds on it; C6 adopts it unchanged so the codebase has one pagination law:

1. **Order** is `created_at desc, id desc` — id comparison is **plain string (lexicographic)**
   (`task-9` sorts above `task-10`), the plain meaning of `ORDER BY created_at DESC, id DESC`
   on a string column. For the audit index the keys are `started_at desc, request_id desc`.
2. **Cursor** = the last returned row's sort id (`id` / `request_id`), opaque to clients. A
   request with a cursor returns rows strictly after that row in the current order. Filters
   apply BEFORE ordering and pagination — a page walk is a walk over the filtered set, and the
   cursor is only meaningful with the same filters held constant.
3. **`next_cursor` is `null` ONLY when the returned page is short** (fewer than `limit` rows).
   An exactly-full final page returns a non-null cursor; the client learns it is done from the
   following empty page (`{items: [], next_cursor: null}`). No look-ahead query.
4. **Unknown cursor → 422** (`validation_error`), never a silent page one.
5. `limit` is 1..200, default 50 (C4's bounds).
6. `order=oldest` (tasks only — §13.1 is the only shape that carries `order`) reverses both
   sort keys (`created_at asc, id asc`); the cursor law is unchanged in the reversed order.

### 2.2 Tasks (`/api/v1/tasks`, `/api/v1/tasks/{task_id}`)

- `Task` maps 1:1 onto the `tasks` row; every key always present, absence = null (house style,
  C5 envelope). `status` includes V2's `parked` (ADR-031). `failure_kind` is C5's
  `ChatFailure.kind` set and does not fork here.
- Filters compose with AND: `status` (enum, 422 outside it), `project_key` (exact, §3),
  `q` (case-insensitive substring over `objective`, server-side — spec §8.1's search).
- `getTask` adds `status_events` from `task_status_events`, ascending `at` (a timeline, spec
  §8.1); `from_status` is null on the creation event. Unknown id → 404.

### 2.3 Activity (`/api/v1/activity`)

One request for the whole snapshot — the alternative (list tasks, then a trace per task) is an
N+1 on a 10-second poll (spec §13.2). No parameters.

- **Partition by `tasks.status`:** `running` = `pending` + `in_progress`; `parked` = `parked`;
  `recent` = `completed` + `failed`, capped at the **20** most recent (spec §7.1). All three
  lists use the §2.1 order (`created_at desc, id desc`) — one ordering law, and it does not
  depend on `completed_at` being set on failed rows.
- `ActivityItem` = `Task` + the fold-in from the **highest-seq** `audit_events` row for the
  task's `request_id`: `latest_stage` (the row's `stage`), `latest_stage_at` (its `at`), and
  `latest_detail` = the projection of its `detail` onto exactly
  `{project_display_name?, tool?, operation?}` — contracted keys (`ARCHITECTURE_V1.md` §3.4),
  trusted config/registry values. **Other detail keys MUST NOT pass through the projection**
  (audit `detail` may embed untrusted excerpts — the projection is what keeps this endpoint's
  trusted-detail promise true). Both `latest_*` fields are null only if no audit row exists
  (defensive; a task is created by `plan_created`, so the case should not occur).

### 2.4 Audit (`/api/v1/audit`, `/api/v1/audit/{request_id}`)

The index groups `audit_events` by `request_id`; derivations are frozen:

| Field | Derivation |
|---|---|
| `started_at` | `at` of the turn's first row (lowest `seq`) |
| `ended_at` | `at` of the `final_response` row; **null while in flight** |
| `stage_count` | count of rows whose `stage` is one of the **twelve NFR-020 spine names** (`message_received` … `final_response`, spec §10.2 table) — approval-episode rows are NOT counted, so the view's "n of 12" reading stays honest |
| `outcome` / `failure_kind` | `final_response.detail.outcome` / `.failure_kind`; null while in flight |
| `agent` | `plan_created.detail.agent` (contracted key, trusted); null before `plan_created` |
| `conversation_id`, `task_id` | resolved through the turn's task; null in the window before a task exists |

Filters: `request_id` exact (returns 0 or 1 turn — the primary way in, spec §10.1); `from`/`to`
half-open on `started_at` (`from <= started_at < to`); `outcome`; `agent`. Pagination per §2.1
on `started_at desc, request_id desc`.

**Detail partition (normative).** `getAuditTurn` splits the turn's rows into two seq-ascending
arrays:

- `approval_events` = rows whose `stage` is an approval lifecycle kind (`approval_requested`,
  `approval_approved`, `approval_refused`, `approval_expired`, `continuation_reconciled`) **or**
  whose `detail` carries `resumed_from_approval_id` (the continuation's rows — C4 §3's lineage
  rule). Null when the turn had no approval episode. This is spec §10.2's second segment
  ("AFTER YOUR DECISION — continuation"), one story on one `request_id`
  (`ARCHITECTURE_V2.md` §6 Legs 3–6).
- `events` = every other row.

Unknown `request_id` (zero audit rows) → 404. Open question **Q9** (does a parked turn emit all
twelve stages?) changes observed *counts*, never these *shapes* — the contract reports facts and
the UI already renders any count ≠ 12 as a `warning` (spec §10.3).

## 3. Q2 ruling — `tasks.project_key` (normative schema delta)

**Ruled: add the column.** `tasks` gains `project_key` (string, nullable), written **once at
task creation** from the `ValidatedPlan` (the same value `plan_created.detail.project_key`
records) and never updated. Null when the plan carried no project, and for any row predating
the column.

*Reasoning:* the frozen §13.1 shape already carries `project_key` in both the `Task` row and
the filter, so "no project filter in v1" would contradict the shape the owner froze; and the
value is known exactly once (plan validation) and immutable, so deriving it per-row from
`audit_events.detail` at list time is the same N+1-on-a-poll that §13.2 exists to kill.
Consequences: spec §8.1 column 4 reads a real column; §9's and §16.2's per-project counts ride
`GET /api/v1/tasks?project_key=…` with no new endpoint; `GET /api/v1/projects` (spec §13.4) is
untouched — it already exists in the module layout and returns C5's `ProjectSummary`.

## 4. Untrusted content — containment carried into every row

The C4 §4 / spec §6.3 rule applies wherever these fields are rendered — list rows, dashboard
summary tiers, cards, tooltips, exports:

| Field | Trust | Rule |
|---|---|---|
| `Task.objective` (and in `ActivityItem`) | **UNTRUSTED** (plan text derived from user/LLM strings, spec §7.2) | plain text node only; `UntrustedText` treatment; never markup, never interpolated into an attribute |
| `AuditEvent.summary` | **UNTRUSTED-INFLUENCED** (an `approval_requested` row carries the C4 `summary` verbatim) | same rule |
| `AuditEvent.detail` values | **may embed truncated UNTRUSTED excerpts** (`ARCHITECTURE_V1.md` §3.4, T-32) | spec §6.3 rules; raw JSON in a `<pre>` as text; **no exception for developer-facing screens** |
| `latest_detail`, `agent`, `assigned_agent`, `actor`, `tool`, `operation`, enums, ids, timestamps | trusted (SUNIL/registry-written) | may be styled as identifiers |

**The server MUST NOT sanitise, escape or strip these values** — they are returned
byte-faithful. Containment is a *rendering* duty; a server that "helpfully" encodes would hide
the raw value the owner is entitled to inspect and would tempt a renderer to un-escape. (Same
posture as C4; Q5's character-policy question stays open with Security and is unchanged by C6.)

## 5. In-process seam (what the routes call)

```python
class OpsReadStore(Protocol):
    async def list_tasks(self, *, status: str | None = None,
                         project_key: str | None = None, q: str | None = None,
                         order: str = "newest", limit: int = 50,
                         cursor: str | None = None) -> TaskPage: ...
    async def get_task(self, task_id: str) -> TaskDetail | None: ...
    async def activity(self) -> ActivitySnapshot: ...
    async def list_audit_turns(self, *, request_id: str | None = None,
                               from_at: str | None = None, to_at: str | None = None,
                               outcome: str | None = None, agent: str | None = None,
                               limit: int = 50,
                               cursor: str | None = None) -> AuditTurnPage: ...
    async def get_audit_turn(self, request_id: str) -> AuditTurnDetail | None: ...
```

`None` from the two getters maps to 404 in the HTTP layer and nowhere else — the C4 §6.2
blessed shape. `from_at`/`to_at` are the HTTP `from`/`to` query params (`from` is a Python
reserved word; the route layer maps the names — the wire shape is §13.3's). An unknown `cursor` raises `ValueError` in the store; the HTTP layer maps it to
422 (the C4 fakes-round rule). Page/snapshot return types are the OpenAPI response shapes
(`{tasks, next_cursor}`, `{running, parked, recent}`, `{turns, next_cursor}`,
`{events, approval_events}`).

## 6. FAKE specification — `FakeOpsStore` + fixture (QA-buildable, no questions)

Module: `apps/api/tests/fakes/fake_ops_store.py`. Implements `OpsReadStore` per the F2 rule
(does NOT inherit the Protocol; module-level `_check: OpsReadStore = FakeOpsStore()` witness)
and provides the HTTP layer's store so Stream D builds the three views against a running fake.

Constructor: `FakeOpsStore(clock: FakeClock | None = None)` — the shared
`tests/fakes/clock.py::FakeClock` (default start `2026-01-01T00:00:00Z`).

State: `self.tasks: dict[str, dict]` (insertion-ordered), `self.audit_rows: list[dict]`,
`self.status_events: list[dict]`, `self.conversations: dict[str, str]`
(request_id → conversation_id, fed by `add_task`).

Seed helpers (each advances the clock **+1 s** unless an explicit timestamp is passed — the
C4-fake convention; the override exists so tie tests can construct equal timestamps):

1. `add_task(objective, *, status="pending", assigned_agent="project_manager",
   priority="normal", project_key=None, request_id, conversation_id, approval_id=None,
   created_at=None, started_at=None, completed_at=None, failure_kind=None) -> str` — ids
   `task-1`, `task-2`, … in call order; appends the creation `status_event`
   (`from_status=None → status`).
2. `add_status_event(task_id, from_status, to_status, at=None)` — also materialises
   `tasks[task_id]["status"] = to_status`.
3. `add_audit_row(request_id, stage, *, actor="core", summary="", detail=None, task_id=None,
   at=None) -> int` — `seq` auto-increments per `request_id` from 1.

Exact behaviours — each is the §2 law restated as executable fact:

1. **Ordering/cursor/next_cursor/unknown-cursor** exactly §2.1 (the F8 law). `next_cursor` is
   computed from page length alone — `None` iff `len(page) < limit`.
2. `list_tasks` filters AND-compose; `status` outside the enum raises `ValueError` (→ 422);
   `q` is `q.lower() in objective.lower()`; `order="oldest"` reverses both keys.
3. `get_task` returns the task + its `status_events` ascending `at` (ties keep write order);
   unknown id → `None`.
4. `activity()` partitions per §2.3, `recent` truncated to 20 AFTER ordering; `latest_*` from
   the highest-seq audit row for the task's `request_id`; `latest_detail` projects **only** the
   three contracted keys (extra seeded keys must not appear).
5. `list_audit_turns` groups `audit_rows` by `request_id` and derives per §2.4's table;
   `conversation_id` resolves via `self.conversations`, else the linked task, else `None`.
6. `get_audit_turn` partitions per §2.4 (lifecycle-kind set ∪ `detail` carrying
   `resumed_from_approval_id`); both arrays ascending `seq`; no episode rows →
   `approval_events=None`; zero rows for the id → `None`.
7. Every returned page/snapshot is a **deep copy** (the F1 lesson — no shared mutable state
   between calls or with the seeds).

**Fixture** (`ops_fixture()` in the same module, deterministic): 12 tasks `task-1`…`task-12`
covering every status (≥1 parked with `approval_id="apr-1"`, ≥2 failed with C5 kinds,
`project_key` mix of `"sunil"`/`"easyclean"`/None, objectives including
`"<b>bold</b> [x](http://x.invalid)"` for the byte-fidelity probe); `task-9`/`task-10` seeded
with an **equal explicit `created_at`** (the deliberate lexicographic tie); 21 additional
terminal tasks `task-13`…`task-33` (the recent-cap probe); three audit turns — `req-full`
(twelve spine rows), `req-parked` (spine rows + `approval_requested` + `approval_approved` +
two continuation rows whose `detail` carries `resumed_from_approval_id="apr-1"`), `req-live`
(five spine rows, no `final_response`).

Contract tests (`apps/api/tests/contracts/test_c6_ops_reads.py`):

1. **Order law:** default list is `created_at desc, id desc`; the seeded equal-timestamp pair
   orders `task-9` before `task-10` (plain-string desc — the F8 reading); `order=oldest`
   reverses both keys.
2. **Cursor law:** with `limit` dividing the filtered total exactly, every page **including the
   exactly-full final page** returns a non-null `next_cursor`, and the following call returns
   `{tasks: [], next_cursor: null}`; a short page returns `null`; an unknown cursor → 422;
   `limit=0` and `limit=201` → 422.
3. **Filters:** each `TaskStatus` value; `project_key` exact (and `None`-keyed rows excluded);
   `q` case-insensitive substring; combined filters AND; out-of-enum `status` → 422.
4. **Task detail:** `status_events` ascending `at`, `from_status=None` first; unknown id → 404.
5. **Activity partition:** exact tri-partition by status; `recent` is 20 items with the newest
   21st excluded; `latest_stage`/`latest_stage_at` from the highest-seq row; a seeded detail
   with an extra key (`{"tool": "github_mcp", "secret_excerpt": "x"}`) yields `latest_detail`
   containing `tool` only (projection probe).
6. **Audit derivations:** `req-live` → `ended_at`/`outcome` null, `stage_count=5`;
   `req-parked` → `stage_count` counts spine rows ONLY (episode rows excluded);
   `outcome`/`failure_kind`/`agent` extracted from the contracted detail keys.
7. **Audit filters + pagination:** `request_id` exact returns 0-or-1 turn; `from`/`to`
   half-open boundaries probed with a row exactly at `to` (excluded) and at `from` (included);
   the §2.1 cursor law re-asserted on `request_id desc`.
8. **Detail partition:** `req-parked` → `events` = spine rows, `approval_events` = the four
   episode rows ascending `seq` (the continuation rows land there via
   `resumed_from_approval_id`, not via their stage name); `req-full` → `approval_events` null;
   unknown id → 404.
9. **Auth posture (against the real routes):** no session → 401 on all five operations; session
   without `X-SUNIL-Client` → 403; a valid `SUNIL_SERVICE_TOKEN` bearer with no cookie → 401 on
   each C6 route (the ADR-035 structural-scope probe, complementing C5 test 8).
10. **Byte-fidelity (containment-by-shape):** the seeded objective/summary/detail values
    containing HTML/markdown/URL text come back **byte-identical** through list, detail and
    activity — the server neither strips nor encodes, pinning §4's "containment is a rendering
    duty" so a future "helpful" sanitiser fails the suite.

## 7. Out of scope, recorded

- `GET /api/v1/projects` (spec §13.4) — already in the module layout; returns C5
  `ProjectSummary`; counts ride §3's column via `listTasks`. Not part of C6.
- Q3 (grace-window exposure), Q4 (risk classification), Q5 (character policy), Q8 (mobile) —
  unchanged by C6; Q9 affects observed `stage_count` values only (§2.4).
- Push/streaming — the §1.5 10-second poll stands (ADR-027's V-10 argument); C6 adds no
  channel.

## Changelog

- **v1.0.0 — 2026-09-11.** Initial freeze of spec §13.1–13.3 verbatim (owner Gate 2 ruling
  Q1 = freeze). Q2 ruled: `tasks.project_key` added (§3). Pagination/order pinned to C4 §6.5's
  QA-pinned literal reading (F8) so one law covers C4 and C6. Companion ADR-036.
