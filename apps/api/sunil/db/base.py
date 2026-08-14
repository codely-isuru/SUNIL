"""Declarative base and the portable column-type helpers of
`ARCHITECTURE_V1.md` §7.2.

These rules are non-negotiable (§7.2's own word) because they are what let
one schema, one Alembic history, serve both SQLite (M1's default, ADR-001)
and PostgreSQL (the V1 target) without drift:

- Primary keys are `String(36)` text UUID4s, generated in Python.
- JSON columns are `sa.JSON().with_variant(JSONB, "postgresql")`.
- Timestamps are `DateTime(timezone=True)`, always written via `utc_now()`.
- Enums are `String` + a Python `StrEnum` + a `CheckConstraint` — never a
  native `ENUM` type.
- No server-side defaults — every default is set in Python.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, CheckConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every SUNIL ORM model."""


# JSONB on PostgreSQL, TEXT-backed JSON on SQLite — one column definition
# for both engines. Use this type object directly in `mapped_column(...)`.
PortableJSON = JSON().with_variant(postgresql.JSONB(), "postgresql")


def new_uuid() -> str:
    """A text UUID4. SQLite has no native UUID type, and text ids are
    greppable in logs and across `request_id` joins (§7.2)."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Always call this for a timestamp default, never
    `datetime.utcnow()` or a server-side `now()` — SQLite drops tzinfo, so
    writing UTC everywhere is what makes that harmless (§7.2), and a
    server-side default would differ between engines."""
    return datetime.now(UTC)


def enum_check_constraint(
    column_name: str, enum_cls: type[StrEnum], *, name: str
) -> CheckConstraint:
    """A `CheckConstraint` restricting `column_name` to `enum_cls`'s string
    values — the portable substitute for a native `ENUM` type (§7.2)."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column_name} IN ({values})", name=name)
