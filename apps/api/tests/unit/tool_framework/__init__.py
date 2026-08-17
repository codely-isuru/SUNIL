"""Package marker — mirrors `tests/unit/registry/`'s reason: without this,
pytest imports this directory's `conftest.py` under the bare module name
`conftest`, which collides with any other directory's `conftest.py`
(e.g. `tests/security/conftest.py`) that also lacks `__init__.py` — the
first one loaded wins in `sys.modules` and the other silently gets the
wrong fixtures for any bare `from conftest import ...` elsewhere."""
