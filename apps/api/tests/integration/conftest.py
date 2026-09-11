"""Loads the spine's shared fixtures for the integration suite only — see
``tests/spine_harness.py`` for why they are not in a top-level conftest."""

pytest_plugins = ["tests.spine_harness"]
