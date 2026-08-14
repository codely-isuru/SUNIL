#!/usr/bin/env python
"""Seed the single owner user row (ADR-000 Q3, ADR-007).

Reads `OWNER_USERNAME` / `OWNER_PASSWORD` from `Settings` and creates (or,
if it already exists, updates the password of) the one `users` row this
system will ever have in M1. **No signup endpoint exists** — this script
is the only way an owner account is created or its password is reset.

Usage (from the repo root, with apps/api's venv active):
    python scripts\\seed-owner.py

Or via `scripts\\dev-api.ps1`, which runs this after `alembic upgrade head`.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import sys
from pathlib import Path

# Allow running this script directly (`python scripts/seed-owner.py`)
# without the editable install already being the active interpreter's
# working directory.
_API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from sqlalchemy import select  # noqa: E402

from sunil.db.models import User  # noqa: E402
from sunil.db.session import get_engine, get_sessionmaker  # noqa: E402
from sunil.settings import get_settings  # noqa: E402

# ADR-007's exact encoding: `scrypt$n$r$p$salt_b64$hash_b64`.
# T5's login route (`sunil/api/routes/auth.py`) must verify against this
# same format — these parameters are the whole contract between the two.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def hash_password(password: str) -> str:
    """`scrypt$n$r$p$salt_b64$hash_b64` (ADR-007) — a fresh random 16-byte
    salt every call, so hashing the same password twice never produces the
    same encoded string."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(digest).decode("ascii")
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt_b64}${hash_b64}"


async def seed_owner() -> None:
    settings = get_settings()
    username = settings.owner_username
    password = settings.owner_password.get_secret_value()

    engine = get_engine(settings)
    sessionmaker = get_sessionmaker(engine)

    try:
        async with sessionmaker() as session:
            existing = await session.scalar(select(User).where(User.username == username))
            if existing is not None:
                existing.password_hash = hash_password(password)
                print(f"Updated password for existing owner '{username}'.")
            else:
                session.add(
                    User(
                        name=username,
                        username=username,
                        password_hash=hash_password(password),
                    )
                )
                print(f"Created owner user '{username}'.")
            await session.commit()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_owner())
