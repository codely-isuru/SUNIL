"""Makes `tests.unit.registry` a package so its `test_capture.py` does not
collide, at import time, with T2's `tests/unit/test_capture.py` (both
directories are flat otherwise, and pytest imports same-named modules by
bare filename when there is no `__init__.py` to disambiguate them)."""
