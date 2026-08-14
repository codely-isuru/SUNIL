"""SUNIL M1 backend test suite.

Package layout and ownership (docs/M1_BUILD_PLAN.md §5, T18):
    tests/unit/            backend engineers, one module each, for their own code
    tests/integration/     QA (T18) — exclusively
    tests/exit/            QA (T18) — exclusively; ET-1..ET-12 live here
    tests/security/        Security (T19) — exclusively

This file, tests/conftest.py and tests/_helpers.py are QA-owned (T18's "Owns" line
in the build plan names apps/api/tests/conftest.py explicitly).
"""
