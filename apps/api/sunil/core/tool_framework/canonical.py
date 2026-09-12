"""``args_hash`` — C1 §6.4's canonicalisation rule, in production code.

    ``args_hash`` canonicalisation (normative for C1 and C4): ``sha256`` hex
    digest of the UTF-8 JSON serialisation of the **validated** params model
    with ``sort_keys=True``, separators ``(",", ":")``.

One hasher, one composer (C1 §2.1 step 3, backend review F3): the Tool Manager
computes the hash at park time AND recomputes it from freshly re-validated
params at consume time with this same function, so the binding a continuation
is checked against is the binding the approval was minted with. Nothing else in
the system may hash params — ``json.dumps(..., sort_keys=True)`` hand-rolled at
a second call site is how the two sides drift.

QA keeps an INDEPENDENT implementation in ``tests/fakes/canonical.py`` and
asserts this one's output through C1 contract test 4. That is deliberate: the
two must be written separately so the contract test can catch a disagreement.
"""

from __future__ import annotations

import json
from hashlib import sha256

from pydantic import BaseModel


def canonical_json(params: BaseModel | dict) -> str:
    """C1 §6.4's canonical form. ``sort_keys=True`` is recursive in
    ``json.dumps``, so nested dicts canonicalise too — two calls whose nested
    params were built in a different key order hash identically, which is what
    makes the park-time hash bind on resume."""
    payload = params.model_dump() if isinstance(params, BaseModel) else params
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def args_hash(params: BaseModel | dict) -> str:
    """C1 §6.4 — sha256 hex digest of :func:`canonical_json`, UTF-8 encoded."""
    return sha256(canonical_json(params).encode("utf-8")).hexdigest()
