"""Task lifecycle service (T11a) — FR-063, FR-065.

`create_task()` and `transition_task_status()` are the only writers of
`tasks` and `task_status_events`; `turn.py` (T11b) calls these rather
than constructing `Task` rows itself, so the lifecycle rule (exactly
`pending -> in_progress -> completed|failed`, no `cancelled` — ADR-010)
lives in one place.
"""

from __future__ import annotations
