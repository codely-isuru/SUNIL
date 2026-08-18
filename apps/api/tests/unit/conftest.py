"""Shared fixtures for the whole `tests/unit/` tree.

T26: a real `.env` now exists at the repo root on the owner's own machine
(created for a live run) — `sunil.settings.Settings` reads it by path
(`model_config["env_file"]`), not through `os.environ`, so
`monkeypatch.delenv("SOME_KEY")` does not make `SOME_KEY` genuinely absent
when the real `.env` also defines it; it only clears the process copy. Every
test that asserts a variable is *absent* was silently reading the developer's
real credentials the moment that file appeared — confirmed by reproducing it
locally (a throwaway `.env` with a fake-but-present `OPENAI_API_KEY` turned a
real, passing "refuses to boot without it" test into "boots fine", for
exactly this reason).

Most call sites already protect themselves explicitly
(`Settings(_env_file=None, ...)` — `tests/unit/test_settings.py`'s own module
docstring, `tests/security/test_secret_exposure.py`, QA's
`tests/exit/_client.py::build_settings()`). The one shape that *cannot*
protect itself the same way is a bare `create_app()`
(`tests/unit/test_main_app.py`): `create_app(settings: Settings | None =
None)` takes a whole `Settings` instance or none, so there is no
`_env_file=` kwarg to reach for at that call site at all.

This fixture closes the class structurally for the whole unit suite, the
same way this repo's root `tests/conftest.py::_isolate_stdlib_logger_registry`
closed the stdlib-logger-registry collision class rather than renaming the
two files that exhibited it: `monkeypatch.setitem(Settings.model_config,
"env_file", None)` makes `env_file` `None` for every `Settings()` /
`create_app()` call for the duration of each unit test, exactly as if
`_env_file=None` had been passed explicitly everywhere, without requiring
every current and future call site to remember to pass it. Confirmed to
take effect per-construction, not just at class-definition time
(`pydantic_settings.BaseSettings` reads `model_config["env_file"]` fresh
every time `Settings()` runs) — this is not a guess about how the library
behaves.

Scoped to `tests/unit/` only (a new conftest.py here, not an edit to the
root one): `tests/exit/` and `tests/security/` already build every
`Settings` through their own explicit, `_env_file=None`-disabled seams and
have no bare `create_app()`/`Settings()` call sites depending on this, and
the root `tests/conftest.py` states its own contract explicitly ("free of
any `sunil.*` import, so this file itself always collects cleanly
regardless of how much of the backend exists yet") — importing
`sunil.settings` there would break a stated invariant for no benefit, when
a directory-scoped conftest already gets the same protection to exactly
the files that need it.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_dotenv_in_unit_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    from sunil.settings import Settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
