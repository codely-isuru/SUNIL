"""Approval ids: ``apr-`` + ULID.

C4's OpenAPI says "ULID/UUID string id" and ``ARCHITECTURE_V2`` §6's worked
trace shows ``apr-01J…`` — a prefixed ULID. ULID rather than UUIDv4 because C4
§6.5's pagination orders by ``created_at desc, id desc`` with **lexicographic**
id comparison (the reading QA pinned in finding F8), and a ULID's first 48 bits
are the millisecond timestamp in Crockford base32 — so lexicographic id order
IS creation order. A UUIDv4 tiebreak would be random, which turns the keyset
cursor into a coin flip whenever two rows share a ``created_at``.

Two properties the pagination depends on, and which ``tests/unit/approvals``
assert rather than assume:

* **Fixed width.** Every id is ``apr-`` + 26 base32 characters, so a
  lexicographic (byte-wise) comparison and a collation-aware one agree. A
  variable-length scheme would not: under a typical ICU collation punctuation is
  weighted differently from bytes, which is how the fake's ``apr-10 < apr-2``
  case arises. Fixed width and one alphabet removes the question.
* **No lowercase.** Crockford base32 excludes ``I``, ``L``, ``O`` and ``U`` and
  is uppercase, so no case-folding collation can reorder two ids.

Written by hand rather than taking a ``python-ulid`` dependency: it is twenty
lines, and ``pyproject.toml``'s dependency list is deliberately minimal.
"""

from __future__ import annotations

import secrets
from datetime import datetime

#: Crockford base32, the ULID alphabet (RFC-less but universally agreed).
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TIME_CHARS = 10  # 48 bits of milliseconds
_RANDOM_CHARS = 16  # 80 bits of randomness
ID_PREFIX = "apr-"
ID_LENGTH = len(ID_PREFIX) + _TIME_CHARS + _RANDOM_CHARS


def _encode(value: int, length: int) -> str:
    out = [""] * length
    for i in range(length - 1, -1, -1):
        out[i] = _ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(out)


def ulid(now: datetime) -> str:
    """A ULID whose timestamp component is ``now`` (ms precision)."""
    millis = int(now.timestamp() * 1000)
    return _encode(millis, _TIME_CHARS) + _encode(
        secrets.randbits(5 * _RANDOM_CHARS), _RANDOM_CHARS
    )


def ulid_approval_id(now: datetime) -> str:
    """The id the approvals service mints: ``apr-`` + ULID."""
    return ID_PREFIX + ulid(now)
