"""The Model Router (ADR-003, `ARCHITECTURE_V1.md` §4).

Renamed from the roadmap's `core/models/` — this package is the Model
*Router*, and `sunil.db.models` already owns the name `models` for the
ORM tables (A-1, §2.1). Callers name a **capability**; nothing here or
above it names a vendor or a model ID (§33 rule 1).
"""
