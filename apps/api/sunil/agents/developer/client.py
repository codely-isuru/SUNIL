"""The developer-engine seam — **ours**, not OpenHands'.

ADR-030's governing principle is that every integrated component is "a
replaceable vendor behind a SUNIL-owned seam". This module is that seam. It is
deliberately three calls wide:

    submit(spec) -> run_id      status(run_id) -> RunState      result(run_id) -> RunResult

and nothing about OpenHands appears in it: no URL, no header, no field name, no
status string. The vendor mapping lives in exactly one module,
:mod:`sunil.agents.developer.openhands_http`, so swapping the engine (or
correcting its shape after a live boot) touches one file and no test of the
agent's behaviour.

Three properties are load-bearing rather than incidental:

* **No credential crosses this seam.** ``TaskSpec`` carries a ``project_key``,
  never a repository URL and never a token. The engine's sandbox is given its
  own scoped git credential at ITS boot (``infra/docker-compose.yml``,
  ``docs/tasks/S2-F-openhands.md``); SUNIL's agent holds none and cannot pass
  one. That is what keeps "the agent never holds git credentials" structural
  instead of a convention.
* **The engine's reply is untrusted input** (C1 §3). ``RunResult`` is a parsed,
  typed projection of whatever the engine said — and every field of it is
  re-checked by the agent before it can influence a privileged call. A
  ``GitIntent.operation`` is a *request*, never an instruction.
* **The failure vocabulary is C1 §4's**, not a fourth private one
  (:class:`EngineErrorKind` below). One closed set means the audit row, the
  trace detail and the agent result all say the same word for the same event.

Deferred to the first live boot: nothing in this module. It is a pure interface
plus value types and is exercised end-to-end by the agent tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class RunState(StrEnum):
    """The four states a delegated run can be in, as far as SUNIL cares.

    Deliberately smaller than any vendor's lifecycle: an engine that
    distinguishes "starting" from "initialising" from "cloning" is telling us
    the same thing — not finished. The mapping from the vendor's richer set
    lives in the adapter, which is where a vendor's vocabulary belongs.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (RunState.SUCCEEDED, RunState.FAILED)


class EngineErrorKind(StrEnum):
    """C1 §4's execution subset, reused verbatim.

    ``transport_error`` — the engine could not be reached at all.
    ``timeout``         — it was reached but did not answer in budget.
    ``upstream_error``  — it answered, and the answer was a failure or a shape
                          the adapter does not recognise.
    ``invalid_params``  — the CALLER's request was not valid; today the only
                          case is a ``project_key`` with no repository behind
                          it. Distinct from ``upstream_error`` because the
                          engine never saw it and is not at fault.
    """

    TRANSPORT_ERROR = "transport_error"
    TIMEOUT = "timeout"
    UPSTREAM_ERROR = "upstream_error"
    INVALID_PARAMS = "invalid_params"


class EngineError(Exception):
    """Raised by a client when a CALL failed — never when a RUN failed.

    A run that ran and failed is a :class:`RunResult` with
    ``state=RunState.FAILED``: it is data about the world, and the agent reports
    it. An ``EngineError`` is the seam itself not working.
    """

    def __init__(self, kind: EngineErrorKind, message: str) -> None:
        super().__init__(f"{kind.value}: {message}")
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class TaskSpec:
    """What SUNIL delegates. Composed by the agent, never by a model.

    ``project_key`` — a key in ``config/projects.yaml``. The repository identity
    is resolved from it by the *client*, which is constructed by wiring with the
    project registry, exactly as the native GitHub tool resolves ``owner/repo``
    (``config/tools.yaml``: "owner/repo come from config/projects.yaml via the
    wiring code, NEVER from the plan"). A plan therefore cannot name a
    repository, and a prompt-injected plan cannot point the engine at someone
    else's.

    ``base_branch`` / ``branch_prefix`` — the branch policy, carried into the
    prompt AND re-enforced by the agent on the way back out (a prompt is a
    request; the check on the return path is the control).
    """

    project_key: str
    instructions: str
    base_branch: str
    branch_prefix: str
    timeout_s: float


@dataclass(frozen=True)
class GitIntent:
    """A git write the engine says it wants. UNTRUSTED.

    ``operation`` is matched against the agent's closed set and then executed as
    a C1 tool call with params the AGENT builds — the string never reaches an
    adapter, a permission lookup or an approval summary unmapped.
    """

    operation: str
    branch: str | None = None


@dataclass(frozen=True)
class RunResult:
    """The engine's report on a finished run. Every field is untrusted."""

    run_id: str
    state: RunState
    branch: str | None = None
    summary: str | None = None
    git_intents: tuple[GitIntent, ...] = field(default_factory=tuple)
    #: The engine's OWN word for why it failed, preserved unmapped for the audit
    #: trail. It is never translated into a C1 error kind by guesswork: the agent
    #: reports `upstream_error` (the run executed and failed) and carries this
    #: string alongside it.
    failure_kind: str | None = None


#: The reporting contract the agent appends to every delegated instruction.
#: It lives here, next to :class:`RunResult`, because it and the dataclass are
#: two halves of one agreement: change the fields and this text must change with
#: them. A run that ignores it produces an unparsable report, which is a failed
#: run — the agent then does nothing, which is the correct fail-closed outcome.
REPORT_CONTRACT = (
    "When you have finished, end your final message with a fenced JSON block "
    "(```json ... ```) containing exactly these keys: "
    '{"branch": "<the branch you worked on>", '
    '"summary": "<one sentence>", '
    '"git_intents": [{"operation": "push_branch"|"merge_main"}]}. '
    "Do not perform the merge yourself and do not ask for any other operation: "
    "SUNIL performs every git write itself, under its own permission matrix, "
    "and an operation not in that list is refused."
)


class OpenHandsClient(Protocol):
    """The seam. Three calls, no vendor vocabulary.

    Implemented by :class:`sunil.agents.developer.openhands_http.OpenHandsHttpClient`
    for the real engine and by the tests' scripted double. Deliberately NOT
    ``@runtime_checkable``: a runtime-checkable Protocol makes ``isinstance``
    prove shape, not provenance (the M1 tripwire lesson, restated in C1 §2).
    """

    async def submit(self, spec: TaskSpec) -> str:
        """Start a run; return the engine's id for it. Raises `EngineError`."""
        ...

    async def status(self, run_id: str) -> RunState:
        """Where the run has got to. Raises `EngineError`."""
        ...

    async def result(self, run_id: str) -> RunResult:
        """The report for a run the caller has seen reach a terminal state."""
        ...
