"""Structural conformance of every QA fake to its frozen Protocol.

Why this file exists — backend fakes-review finding **F2**. Each fake used to
declare its Protocol as a BASE CLASS (``class FakeApprovalsService(
ApprovalsService)``). Explicitly inheriting a ``typing.Protocol`` does not make
its methods abstract: the ``...`` bodies are inherited as ordinary callables that
**return ``None``**. So a fake that misspells, renames or simply forgets a
contract method still *has* that method — it silently answers ``None`` — and a
contract test can pass against it vacuously. The backend engineer proved it with
a subclass whose ``consume()`` returned ``None`` instead of a ``ConsumeResult``.

The fix is structural typing only: no fake inherits its Protocol, so a missing
method is an ``AttributeError`` at the call site and a wrong shape is a type
error at build time. Two guards replace the base class:

* **static** — a module-level ``_check: <Protocol> = <Fake>(…)`` assignment in
  each fake module, which a type checker reads as "this fake must satisfy this
  Protocol" (and which also proves the fake constructs at import time);
* **runtime** — this file: the Protocol is absent from the MRO, every Protocol
  member is present on the fake AND defined by the fake itself, async-ness
  matches, and the ``_check`` witnesses exist.
"""

from __future__ import annotations

from inspect import iscoroutinefunction

import pytest

import tests.fakes.fake_approvals as fake_approvals_module
import tests.fakes.fake_hooks as fake_hooks_module
import tests.fakes.fake_memory_provider as fake_memory_module
import tests.fakes.fake_provider as fake_provider_module
import tests.fakes.fake_tool_adapter as fake_tool_adapter_module
from sunil.core.approvals.base import ApprovalsService
from sunil.core.memory.provider import MemoryProvider
from sunil.core.tool_framework.base import AuditHook, PermissionHook, ToolAdapter
from sunil.providers.base import LLMProvider
from tests.fakes.fake_approvals import FakeApprovalsService
from tests.fakes.fake_hooks import FakePermissionHook, RecordingAuditHook
from tests.fakes.fake_memory_provider import FakeMemoryProvider
from tests.fakes.fake_provider import FakeProvider
from tests.fakes.fake_tool_adapter import FakeToolAdapter

pytestmark = pytest.mark.contract

#: Every (fake, Protocol, module, `_check` witness name) the QA fakes deliver.
PAIRS = [
    (FakeToolAdapter, ToolAdapter, fake_tool_adapter_module, "_check"),
    (FakePermissionHook, PermissionHook, fake_hooks_module, "_check_permission"),
    (RecordingAuditHook, AuditHook, fake_hooks_module, "_check_audit"),
    (FakeApprovalsService, ApprovalsService, fake_approvals_module, "_check"),
    (FakeMemoryProvider, MemoryProvider, fake_memory_module, "_check"),
    (FakeProvider, LLMProvider, fake_provider_module, "_check"),
]
IDS = [f"{fake.__name__}->{protocol.__name__}" for fake, protocol, _, _ in PAIRS]


def protocol_members(protocol: type) -> set[str]:
    """The Protocol's own declared surface: annotated attributes plus public
    methods. Deliberately not ``typing.get_protocol_members`` (3.13-only, and
    ``pyproject`` keeps the contract's ``>=3.12`` floor) and not the private
    ``__protocol_attrs__``."""
    members = set(getattr(protocol, "__annotations__", {}))
    members |= {
        name
        for name, value in vars(protocol).items()
        if callable(value) and (not name.startswith("_") or name == "__call__")
    }
    return members


@pytest.mark.parametrize("fake,protocol,module,witness", PAIRS, ids=IDS)
def test_fake_does_not_inherit_its_protocol(fake, protocol, module, witness) -> None:
    """F2 — the Protocol must be absent from the fake's MRO, so no contract
    method can be answered by an inherited ``...`` stub returning ``None``."""
    assert protocol not in fake.__mro__
    assert fake.__mro__ == (fake, object)


@pytest.mark.parametrize("fake,protocol,module,witness", PAIRS, ids=IDS)
def test_fake_defines_every_protocol_member_itself(
    fake, protocol, module, witness
) -> None:
    """Structural typing is only safe if it is checked: every member the
    Protocol declares is present on the fake, and every callable one is defined
    by the fake's own class body — not borrowed from anywhere."""
    members = protocol_members(protocol)
    assert members, f"{protocol.__name__} declares no members — check the extractor"

    instance = fake()
    for member in members:
        assert hasattr(instance, member), f"{fake.__name__} is missing {member}"
        declared = getattr(protocol, member, None)
        if callable(declared):
            own = vars(fake).get(member)
            assert own is not None, f"{fake.__name__}.{member} is not defined here"
            assert own is not declared, f"{fake.__name__}.{member} is the stub"
            assert iscoroutinefunction(own) == iscoroutinefunction(declared), (
                f"{fake.__name__}.{member} async-ness differs from the contract"
            )


@pytest.mark.parametrize("fake,protocol,module,witness", PAIRS, ids=IDS)
def test_each_fake_module_carries_a_static_conformance_witness(
    fake, protocol, module, witness
) -> None:
    """The ``_check: <Protocol> = <Fake>(…)`` assignment is what a type checker
    reads instead of the deleted base class. Pinned here so it cannot be
    dropped as "unused" — deleting it would remove the only build-time proof
    that the fake still satisfies the seam."""
    assert isinstance(getattr(module, witness), fake)
    assert module.__annotations__[witness] == protocol.__name__


async def test_protocol_inheritance_would_have_returned_none() -> None:
    """The hazard F2 names, pinned as executable fact rather than prose: a class
    that inherits a Protocol and omits a method still HAS that method, and it
    returns ``None``. This is why the assertion above is 'not in the MRO' rather
    than 'has the attribute'."""

    class Forgetful(ApprovalsService):  # deliberately incomplete
        async def park(self, req):  # type: ignore[override]
            return None

    assert hasattr(Forgetful(), "consume")
    # Not a ConsumeResult, not an AttributeError: silently None. A C1 pipeline
    # test asserting `ok is False` on that would pass for the wrong reason.
    assert await Forgetful().consume("apr-1", binding=None) is None
