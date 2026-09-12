"""OpenHands over HTTP — the ONE module that knows the vendor's shape.

    ============================ VENDOR MAPPING ============================
    The paths, request keys and lifecycle strings in the block of constants
    below are OpenHands' side of the seam, not SUNIL's. They were written
    without access to a running instance (the image is multi-gigabyte and
    needs an LLM key this environment does not hold), so they are
    **unverified** — :data:`VENDOR_MAPPING_STATUS` says exactly that, in
    code, and a test asserts it.

    What IS verified is the containment: every OpenHands-specific string in
    the system is in the constants block below, the tests pin each of them,
    and the rest of Stream F — :mod:`sunil.agents.developer.client`,
    :mod:`sunil.agents.developer.agent` and every test of the agent's
    behaviour — contains not one. Correcting the mapping at first live boot
    is therefore an edit to this block plus the test that pins it, and no
    change at all to the governed behaviour. That containment is ADR-030's
    "replaceable vendor behind a SUNIL-owned seam" made checkable rather
    than asserted.

    Two mapping choices are deliberate and should survive the correction:

    * an **unmapped lifecycle string raises** rather than defaulting. The
      tempting default is "not terminal", which is safe; the dangerous one is
      "finished", which makes the agent fetch a report for a run still
      writing to the branch. Refusing to guess costs one failed turn and a
      one-line map entry.
    * the **run's report is OUR contract, not the vendor's**. OpenHands has
      no native "what git writes do you want" output, so the agent asks for a
      fenced JSON block (``client.REPORT_CONTRACT``) and this module parses
      it. A report that does not arrive, or does not parse, is a FAILED run —
      which means zero git operations. Fail-closed is the default because the
      parse is the only thing standing between an autonomous loop and our
      remote.
    ========================================================================

**No credential is handled here.** The ``httpx.AsyncClient`` is injected,
already carrying whatever auth header the deployment needs — the same rule C2
applies to providers, so this module holds no token, no base URL literal and no
``Settings`` import. The git credential the sandbox uses is granted to the
OpenHands container at ITS boot (``infra/docker-compose.yml``); nothing on this
code path can carry one.

**The repository is resolved here, from the project registry**, exactly as the
native GitHub tool resolves ``owner/repo`` (``config/tools.yaml``: "owner/repo
come from config/projects.yaml via the wiring code, NEVER from the plan"). A
``TaskSpec`` names a ``project_key`` and nothing else, so no plan — however it
was produced — can point the engine at an arbitrary repository.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

import httpx

from sunil.agents.developer.client import (
    EngineError,
    EngineErrorKind,
    GitIntent,
    OpenHandsClient,
    RunResult,
    RunState,
    TaskSpec,
)

# ======================== VENDOR MAPPING (unverified) ====================== #
#: Machine-readable statement of the paragraph above. Flip to
#: ``"verified-<date>"`` in the same commit that corrects the block below
#: against a live instance.
VENDOR_MAPPING_STATUS = "unverified-until-first-live-boot"

SUBMIT_PATH = "/api/conversations"
CONVERSATION_PATH = "/api/conversations/{run_id}"

#: Request keys on the submit call.
SUBMIT_INSTRUCTIONS_KEY = "initial_user_msg"
SUBMIT_REPOSITORY_KEY = "repository"
SUBMIT_BRANCH_KEY = "selected_branch"

#: Response keys.
RUN_ID_KEY = "conversation_id"
STATE_KEY = "status"
FAILURE_KEY = "last_error"
#: Tried in order; the first string value wins. More than one because the
#: field's name is the single least certain thing in this module.
FINAL_MESSAGE_KEYS = ("final_message", "last_agent_message", "message")

#: The vendor's lifecycle, collapsed onto :class:`RunState`. Anything absent
#: raises — see the header note.
STATE_MAP: Mapping[str, RunState] = {
    "STARTING": RunState.QUEUED,
    "INITIALIZING": RunState.QUEUED,
    "RUNNING": RunState.RUNNING,
    "STOPPED": RunState.SUCCEEDED,
    "FINISHED": RunState.SUCCEEDED,
    "ERROR": RunState.FAILED,
    "ARCHIVED": RunState.FAILED,
}
# ========================================================================== #

#: A ceiling on how many git writes one run may request. Not a performance
#: knob: it bounds what a prompt-injected run can queue up for the owner to
#: approve. Eight is well past anything a legitimate fix-and-PR needs.
MAX_GIT_INTENTS = 8

#: The last fenced JSON block in the engine's final message. Last, not first:
#: an injected issue body quoted earlier in the transcript must not be able to
#: pre-empt the agent's own closing report.
_FENCE_RE = re.compile(r"```json\s*(?P<body>\{.*?\})\s*```", re.DOTALL)


class OpenHandsHttpClient:
    """:class:`OpenHandsClient` over HTTP. Structural conformance only — see the
    ``_check`` witness at the foot of this module."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        repositories: Mapping[str, str],
    ) -> None:
        self._http = http
        #: ``project_key -> "owner/name"``, built by wiring from
        #: ``config/projects.yaml``. Never read from a plan.
        self._repositories = dict(repositories)

    async def submit(self, spec: TaskSpec) -> str:
        repository = self._repositories.get(spec.project_key)
        if repository is None:
            # Never sent: the engine is not at fault and must not be told about
            # a project that does not exist.
            raise EngineError(
                EngineErrorKind.INVALID_PARAMS,
                f"no repository is configured for project_key {spec.project_key!r}",
            )

        body = await self._json(
            "POST",
            SUBMIT_PATH,
            json={
                SUBMIT_INSTRUCTIONS_KEY: spec.instructions,
                SUBMIT_REPOSITORY_KEY: repository,
                SUBMIT_BRANCH_KEY: spec.base_branch,
            },
            timeout=spec.timeout_s,
        )
        run_id = body.get(RUN_ID_KEY)
        if not isinstance(run_id, str) or not run_id:
            raise EngineError(
                EngineErrorKind.UPSTREAM_ERROR,
                f"submit response carried no {RUN_ID_KEY!r}",
            )
        return run_id

    async def status(self, run_id: str) -> RunState:
        body = await self._json("GET", CONVERSATION_PATH.format(run_id=run_id))
        return _state_of(body)

    async def result(self, run_id: str) -> RunResult:
        body = await self._json("GET", CONVERSATION_PATH.format(run_id=run_id))
        state = _state_of(body)

        if state is not RunState.SUCCEEDED:
            failure = body.get(FAILURE_KEY)
            return RunResult(
                run_id=run_id,
                state=RunState.FAILED,
                failure_kind=str(failure)[:200] if failure else "engine_reported_failure",
            )

        report = _parse_report(_final_message(body))
        if report is None:
            # Ran, said nothing usable. A failed run, so: no git operations.
            return RunResult(
                run_id=run_id, state=RunState.FAILED, failure_kind="unparsable_report"
            )

        branch, summary, intents = report
        return RunResult(
            run_id=run_id,
            state=RunState.SUCCEEDED,
            branch=branch,
            summary=summary,
            git_intents=intents,
        )

    # -- transport ---------------------------------------------------------- #
    async def _json(
        self, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Every HTTP outcome collapses to a JSON mapping or an `EngineError` —
        an httpx exception never escapes this class, the same posture C1 §2
        requires of a tool adapter."""
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise EngineError(EngineErrorKind.TIMEOUT, str(exc)) from exc
        except httpx.RequestError as exc:
            raise EngineError(EngineErrorKind.TRANSPORT_ERROR, str(exc)) from exc

        if response.status_code >= 400:
            # The body is not echoed: it is engine output, and an error log is
            # not the place to discover that (C1 §3, redaction posture).
            raise EngineError(
                EngineErrorKind.UPSTREAM_ERROR,
                f"engine answered HTTP {response.status_code} for {method} {path}",
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise EngineError(
                EngineErrorKind.UPSTREAM_ERROR, "engine answered with a non-JSON body"
            ) from exc
        if not isinstance(body, dict):
            raise EngineError(
                EngineErrorKind.UPSTREAM_ERROR, "engine answered with a non-object body"
            )
        return body


def _state_of(body: Mapping[str, Any]) -> RunState:
    raw = body.get(STATE_KEY)
    state = STATE_MAP.get(str(raw).upper()) if raw is not None else None
    if state is None:
        raise EngineError(
            EngineErrorKind.UPSTREAM_ERROR,
            f"unmapped engine state {raw!r} — add it to STATE_MAP rather than "
            "letting it default (see this module's VENDOR MAPPING note)",
        )
    return state


def _final_message(body: Mapping[str, Any]) -> str:
    for key in FINAL_MESSAGE_KEYS:
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _parse_report(
    text: str,
) -> tuple[str | None, str | None, tuple[GitIntent, ...]] | None:
    """``client.REPORT_CONTRACT`` parsed out of untrusted prose.

    Returns ``None`` for anything that is not exactly the agreed shape. Every
    value is coerced and bounded here and re-checked by the agent afterwards;
    neither layer trusts the other to have done it.
    """
    matches = _FENCE_RE.findall(text or "")
    if not matches:
        return None
    try:
        payload = json.loads(matches[-1])
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    raw_intents = payload.get("git_intents", [])
    if not isinstance(raw_intents, list):
        return None

    intents: list[GitIntent] = []
    for item in raw_intents[:MAX_GIT_INTENTS]:
        if not isinstance(item, dict):
            return None
        operation = item.get("operation")
        if not isinstance(operation, str):
            return None
        branch = item.get("branch")
        intents.append(
            GitIntent(
                operation=operation[:64],
                branch=branch[:120] if isinstance(branch, str) else None,
            )
        )

    branch = payload.get("branch")
    summary = payload.get("summary")
    return (
        branch[:120] if isinstance(branch, str) else None,
        summary[:2000] if isinstance(summary, str) else None,
        tuple(intents),
    )


#: Static conformance witness: this class satisfies the seam structurally. It
#: does not inherit the Protocol, for C1 §6.3's reason — an inherited Protocol
#: hands the subclass `...` bodies that return None, so a misspelled method
#: answers None instead of raising.
_check: OpenHandsClient = OpenHandsHttpClient(
    httpx.AsyncClient(base_url="http://127.0.0.1:1"), repositories={}
)
