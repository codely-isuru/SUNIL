"""Shared fixtures for `sunil.core.registry` unit tests.

`valid_config_files()` returns the minimal, individually-valid, mutually
cross-consistent set of six YAML documents every test starts from; each
test mutates a copy to introduce exactly the one defect it is checking
for, so a failing assertion always points at one deliberate change.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

AGENTS_YAML: dict[str, Any] = {
    "version": 1,
    "agents": {
        "project_manager": {
            "role": "Manage software projects and identify risks.",
            "instructions": ["Review recent project activity."],
            "objectives": ["Report current project status."],
            "memory_scope": ["short_term"],
            "preferred_capability": "general_reasoning",
            "escalation_capability": "complex_reasoning",
            "tools": {"github": ["list_recent_activity"]},
        }
    },
}

PERMISSIONS_YAML: dict[str, Any] = {
    "version": 1,
    "agents": {"project_manager": {"github": {"list_recent_activity": "allow"}}},
}

PROJECTS_YAML: dict[str, Any] = {
    "version": 1,
    "projects": {
        "easy_clean_workforce": {
            "display_name": "EasyClean Workforce",
            "github": {"owner": "codely-isuru", "repo": "easy_clean_workforce"},
        }
    },
}

MODELS_YAML: dict[str, Any] = {
    "version": 1,
    "pricing_version": "2026-08-14",
    "models": {
        "claude-sonnet-5": {
            "provider": "anthropic",
            "context_window": 1_000_000,
            "max_output": 128_000,
            "input_usd_per_mtok": "2",
            "output_usd_per_mtok": "10",
            "supports_structured_output": True,
        },
        "claude-opus-5": {
            "provider": "anthropic",
            "context_window": 1_000_000,
            "max_output": 128_000,
            "input_usd_per_mtok": "5",
            "output_usd_per_mtok": "25",
            "supports_structured_output": True,
        },
    },
    "capabilities": {
        "general_reasoning": {
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "max_tokens": 1024,
            "timeout_s": 20,
        },
        "complex_reasoning": {
            "provider": "anthropic",
            "model": "claude-opus-5",
            "max_tokens": 2048,
            "timeout_s": 25,
        },
    },
}

TOOLS_YAML: dict[str, Any] = {
    "version": 1,
    "tools": {
        "github": {
            "display_name": "GitHub",
            "operations": {
                "list_recent_activity": {
                    "read_only": True,
                    "description": "Recent commits, open PRs and open issues.",
                    "timeout_s": 15,
                    "params": {"project_key": {"type": "string", "required": True}},
                }
            },
        }
    },
}

CAPTURE_YAML: dict[str, Any] = {
    "version": 1,
    "defaults": {
        "message": {
            "capture_policy": "redacted_full",
            "sensitivity": "internal",
            "retention_class": "standard",
        },
        "plan": {
            "capture_policy": "redacted_full",
            "sensitivity": "internal",
            "retention_class": "standard",
        },
        "llm_call": {
            "capture_policy": "redacted_full",
            "sensitivity": "internal",
            "retention_class": "standard",
        },
        "tool_call": {
            "capture_policy": "redacted_full",
            "sensitivity": "internal",
            "retention_class": "standard",
        },
        "memory": {
            "capture_policy": "redacted_full",
            "sensitivity": "internal",
            "retention_class": "transient",
        },
    },
    "project_overrides": {},
}


def valid_config_files() -> dict[str, dict[str, Any]]:
    """A fresh, independent copy of the six documents every test starts
    from — mutate the returned dict, never the module-level constants."""
    return {
        "agents.yaml": copy.deepcopy(AGENTS_YAML),
        "permissions.yaml": copy.deepcopy(PERMISSIONS_YAML),
        "projects.yaml": copy.deepcopy(PROJECTS_YAML),
        "models.yaml": copy.deepcopy(MODELS_YAML),
        "tools.yaml": copy.deepcopy(TOOLS_YAML),
        "capture.yaml": copy.deepcopy(CAPTURE_YAML),
    }


def write_config_dir(directory: Path, files: dict[str, dict[str, Any]]) -> Path:
    """Write `files` (name -> parsed document) as YAML under `directory`,
    which must already exist, and return it."""
    for filename, document in files.items():
        (directory / filename).write_text(yaml.safe_dump(document), encoding="utf-8")
    return directory


@pytest.fixture
def valid_config_dir(tmp_path: Path) -> Path:
    """A temp directory holding a complete, valid, mutually consistent set
    of the six registry files."""
    return write_config_dir(tmp_path, valid_config_files())
