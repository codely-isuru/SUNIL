"""Declarative base and the portable column-type rules.

These rules are what let ONE schema and ONE Alembic history serve both the
deployed PostgreSQL 17 target and the SQLite database the unit suite runs
against (ARCHITECTURE_V2 §1, keeping ADR-001's "one portable schema"):

* primary keys are `String(36)`/ULID-or-UUID text, generated in Python;
* JSON columns are `JSON().with_variant(JSONB, "postgresql")`;
* timestamps are `DateTime(timezone=True)`, always written via `utc_now()`;
* enums are `String` + a Python `StrEnum` + a `CheckConstraint` — never a native
  `ENUM` type, which Alembic cannot alter portably;
* **no server-side defaults** — every default is set in Python, so two engines
  cannot disagree about what an omitted column means.

No `relationship()` declarations anywhere in `models.py`: lazy loading is a
footgun on async sessions (ADR-002's recorded consequence). Joins are explicit
`select()` statements written by the caller that needs them.
"""

from __future__ import annotations

import secrets
import time
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, CheckConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase

#: Crockford base32, the ULID alphabet (no I, L, O, U — unambiguous when read
#: aloud off a dashboard or pasted out of a log line).
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class Base(DeclarativeBase):
    """Declarative base for every SUNIL ORM model."""


# JSONB on PostgreSQL, TEXT-backed JSON on SQLite — one column definition for
# both engines.
PortableJSON = JSON().with_variant(postgresql.JSONB(), "postgresql")


def new_uuid() -> str:
    """A text UUID4. Text ids are greppable in logs and across `request_id`
    joins, and SQLite has no native UUID type."""
    return str(uuid.uuid4())


def new_ulid(prefix: str = "") -> str:
    """A lexicographically-sortable id, optionally prefixed (`apr-01J…` in the
    L-001 trace, `req-…` for a request).

    48-bit millisecond timestamp + 80 bits of randomness, Crockford base32 —
    the ULID layout, so ordering by id orders by creation time. Implemented here
    rather than pulled in as a dependency: it is 8 lines and one less supply
    chain on the audit path.
    """
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        value, remainder = divmod(value, 32)
        chars.append(_CROCKFORD[remainder])
    return prefix + "".join(reversed(chars))


def utc_now() -> datetime:
    """Always call this for a timestamp — never `datetime.utcnow()` (naive) and
    never a server-side `now()` (engine-dependent). SQLite drops tzinfo, which
    is harmless precisely because everything written is UTC."""
    return datetime.now(UTC)


def enum_check_constraint(
    column_name: str, enum_cls: type[StrEnum], *, name: str
) -> CheckConstraint:
    """A `CheckConstraint` restricting `column_name` to `enum_cls`'s values — the
    portable substitute for a native `ENUM`, and a real guard: a typo'd status
    fails the insert instead of sitting in the table looking like a new state."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column_name} IN ({values})", name=name)
