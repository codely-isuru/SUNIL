"""C1 §3 — the untrusted-results posture applied to MCP result payloads.

Two mechanisms, both normative, both applied by the chokepoint
(:mod:`sunil.core.tool_framework.manager` step 7) to results from MCP adapters:

* a **256 KiB per-result cap**; beyond it the payload is replaced by a marker
  carrying ``data["truncated"] = true``;
* a **key strip**: any dict key equal to ``instructions``, ``system`` or
  ``prompt`` — case-insensitively, at every nesting depth including inside lists
  — is removed, and the removal is **logged with the key path** (never
  silently).

**This strip is cosmetic defence-in-depth only** (C1 §3, Security review
2026-09-10 item 4). A denylist of key names is bypassable by construction — the
same text under another key, or in any VALUE, passes straight through — and must
never be argued as a control. The load-bearing controls are elsewhere and hold
with this module deleted entirely:

* results are presented to the model inside a delimited, role-tagged block
  labelled as external tool output, never concatenated into the system prompt;
* the only path to another tool call is a new validated plan step (ROADMAP §25),
  so free-form text in a result cannot trigger a privileged action (§33.3).

The cap is different in kind: it is a real resource bound (context budget and
log volume), not a content judgement.
"""

from __future__ import annotations

import json
import logging
from typing import Any

#: C1 §3's three key names, matched case-insensitively.
STRIPPED_KEYS = frozenset({"instructions", "system", "prompt"})

#: C1 §3's cap: 256 KiB per result, measured on the compact JSON serialisation
#: of the payload (the form in which it will be placed in the context block).
MAX_RESULT_BYTES = 256 * 1024

#: How much of an oversize payload survives as a diagnostic. Small enough that
#: the truncated marker is comfortably inside the cap; large enough that the
#: agent can say what it received instead of only that something was dropped.
_PREVIEW_CHARS = 4096


def _serialised_size(data: Any) -> int:
    return len(json.dumps(data, separators=(",", ":"), default=str).encode("utf-8"))


def strip_instruction_keys(data: Any, _path: str = "") -> tuple[Any, list[str]]:
    """Return ``(cleaned, removed_key_paths)``.

    Recursive over dicts AND lists (C1 §3: "at every nesting depth ... lists
    included"), case-insensitive on the key name only — a matching VALUE is left
    alone, and a near-miss key such as ``instructions_url`` is not a match,
    because over-stripping corrupts honest tool output for no gain on a control
    the contract already calls cosmetic.

    Never mutates its input: the raw result may still be needed for the audit
    trail, and a sanitiser that edited in place would make the two views of one
    call disagree.
    """
    removed: list[str] = []
    if isinstance(data, dict):
        cleaned: dict[Any, Any] = {}
        for key, value in data.items():
            child_path = f"{_path}.{key}" if _path else str(key)
            if isinstance(key, str) and key.lower() in STRIPPED_KEYS:
                removed.append(child_path)
                continue
            sub, sub_removed = strip_instruction_keys(value, child_path)
            cleaned[key] = sub
            removed.extend(sub_removed)
        return cleaned, removed
    if isinstance(data, list):
        items: list[Any] = []
        for index, value in enumerate(data):
            sub, sub_removed = strip_instruction_keys(value, f"{_path}[{index}]")
            items.append(sub)
            removed.extend(sub_removed)
        return items, removed
    return data, removed


def cap_result(data: dict) -> dict:
    """C1 §3's size cap. Returns ``data`` unchanged at or below the cap; a
    ``{"truncated": True, ...}`` marker above it.

    The boundary is inclusive (a result of exactly ``MAX_RESULT_BYTES`` passes):
    an off-by-one here silently truncates legitimate results, and "beyond" in
    §3's wording means beyond.
    """
    size = _serialised_size(data)
    if size <= MAX_RESULT_BYTES:
        return data
    serialised = json.dumps(data, separators=(",", ":"), default=str)
    return {
        "truncated": True,
        "original_size_bytes": size,
        "preview": serialised[:_PREVIEW_CHARS],
    }


def sanitise_untrusted_data(
    data: dict,
    *,
    context: str,
    logger: logging.Logger,
) -> dict:
    """Strip, then cap — in that order.

    Order is deliberate: a huge ``instructions`` value must be REMOVED, not kept
    as the reason a legitimate result was truncated. ``context`` is the
    ``tool.operation`` the result came from, so the log line names the
    boundary; only key PATHS are logged, never the stripped content, which is
    attacker-authored text that has no business in an operator's log.
    """
    cleaned, removed = strip_instruction_keys(data)
    if removed:
        logger.warning(
            "C1 §3: removed %d instruction-shaped key(s) from %s result: %s "
            "(cosmetic defence-in-depth; not a control)",
            len(removed),
            context,
            ", ".join(sorted(removed)),
        )
    capped = cap_result(cleaned)
    if capped is not cleaned:
        logger.warning(
            "C1 §3: %s result exceeded the %d-byte cap (%d bytes) and was truncated",
            context,
            MAX_RESULT_BYTES,
            capped["original_size_bytes"],
        )
    return capped
