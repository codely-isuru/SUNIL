"""Package marker — mirrors `tests/unit/registry/`'s reason: without this,
pytest imports this directory's `conftest.py` under the bare module name
`conftest`, which collides with any other directory's `conftest.py`
(e.g. `tests/unit/tool_framework/conftest.py`) that also lacks
`__init__.py` — the first one loaded wins in `sys.modules`, and every
`from conftest import ...` in this package's own test files then silently
resolves to the OTHER directory's fixtures instead of this one's,
whichever loaded first. Found running the full combined tree (T3+T6+T8+T9
+T19 together for the first time); not caused by any one of those tasks
individually."""
