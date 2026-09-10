"""``args_hash`` canonicalisation — C1 §6.4's normative rule.

    ``args_hash`` canonicalisation (normative for C1 and C4): ``sha256`` hex
    digest of the UTF-8 JSON serialisation of the **validated** params model
    with ``sort_keys=True``, separators ``(",", ":")``.

This is an INDEPENDENT QA implementation, deliberately kept out of
``sunil/`` so that the production implementation (in the Tool Manager, C1 §2.1
step 3) is written separately and verified against it. If the two ever disagree,
C1 contract test 4's ``args_hash`` assertion fails — which is the point.
"""

from __future__ import annotations

import json
from hashlib import sha256

from pydantic import BaseModel


def canonical_json(params: BaseModel | dict) -> str:
    """C1 §6.4 canonical form of validated params."""
    payload = params.model_dump() if isinstance(params, BaseModel) else params
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def args_hash(params: BaseModel | dict) -> str:
    """C1 §6.4 — sha256 hex digest of :func:`canonical_json`, UTF-8 encoded."""
    return sha256(canonical_json(params).encode("utf-8")).hexdigest()
