"""Workflow lifecycle service (T11a) — FR-063.

M1 has exactly one `Workflow` per `Task` (§21) and exactly one trigger
(`chat_message`); the `schedule` column stays null until M10.
"""

from __future__ import annotations
