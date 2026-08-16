"""Conversation gateway (T11a) — FR-021, FR-140.

`get_or_create_conversation()` / `persist_message()` are the only
writers of `conversations` and `messages`; stage 1 (`message_received`)
and stage 12 (`final_response`) both go through `persist_message()`.
"""

from __future__ import annotations
