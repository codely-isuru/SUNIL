"""Short-term memory (T11a) — FR-140, FR-144.

M1 writes exactly one memory type, `short_term` (ADR-013 defers
long-term/vector memory to M7). `read_recent_messages()` is what actually
supplies "available context" (FR-140) — it reads `messages` directly, the
conversation's own durable record; `record_short_term_memory_retrieval()`
is the auditable note (FR-144) that retrieval happened for this request,
not a second copy of the message content.
"""

from __future__ import annotations
