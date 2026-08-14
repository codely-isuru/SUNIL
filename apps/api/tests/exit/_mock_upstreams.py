"""A tiny local HTTP double for the two external services an M1 turn calls: Anthropic's
Messages API and GitHub's REST API.

WHY THIS EXISTS (see the T18 report's "ambiguity" section for the full writeup): the
frozen contract in docs/M1_BUILD_PLAN.md §6 specifies the browser<->SUNIL HTTP surface
only. It does not specify a test-time seam for substituting a fake LLM provider or fake
tool responses, and ARCHITECTURE_V1.md's own provider-construction snippet (§4.3) never
passes an explicit `base_url=` to `AsyncAnthropic(...)`. That means the SDK's own
`ANTHROPIC_BASE_URL` env-var fallback reaches whatever `sunil.providers.anthropic`
builds, with zero assumptions about sunil-internal class/function names. This is not a
guess: it was verified empirically against the real, installed `anthropic==0.122.0`
package on this machine before this file was written --

    $ python verify_mock_server.py
    content[0].text  = {"intent": "project_status_review"}
    usage.input_tokens  = 111
    usage.output_tokens = 22
    stop_reason  = end_turn
    _request_id  = req_scripted_abc
    OK -- round trip through ANTHROPIC_BASE_URL works end to end

    $ python verify_error_mapping.py
    500 -> anthropic.InternalServerError | is InternalServerError: True
    429 -> anthropic.RateLimitError | is RateLimitError: True

(both scratch scripts are reproduced in the T18 report; not committed here).

GitHub has no equivalent documented base-url override -- ARCHITECTURE_V1.md hard-codes
`https://api.github.com` in prose, not as a configurable value. QA requests a two-line
addition to T8 (`GITHUB_API_BASE_URL`, defaulting to the real host) mirroring the
Anthropic seam; until then, GitHub-routed script entries here are exercised only once
that variable exists. If it never lands, GitHub-dependent tests fail loudly (a real
network call reaches the real GitHub API with a placeholder token and gets a real 401,
which the real code must still turn into a graceful `tool_failed` outcome) rather than
silently mis-passing -- there is no path here that can produce a false green.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class ScriptedResponse:
    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)


class ScriptedHTTPServer:
    """A minimal threaded HTTP server serving pre-scripted JSON responses keyed by
    "METHOD /path", consumed in FIFO order per key (or held constant if only one is
    scripted). Every received request is recorded, in order, for later assertions --
    this is how ET-10/ET-12 inspect exactly what was sent "over the wire" to the model.

    Stdlib only, no extra dependency, torn down at the end of every test that uses it.
    """

    def __init__(self) -> None:
        self._script: dict[str, list[ScriptedResponse]] = {}
        self.received: list[dict[str, Any]] = []
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def script(self, method: str, path: str, response: ScriptedResponse) -> None:
        """Queue `response` for the next matching request to METHOD path. Call more
        than once for the same key to script a sequence (e.g. fail once, then succeed).
        """
        self._script.setdefault(f"{method.upper()} {path}", []).append(response)

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2)

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:  # silence stderr noise
                pass

            def _handle(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                server.received.append(
                    {
                        "method": method,
                        "path": self.path,
                        "headers": dict(self.headers.items()),
                        "body": raw.decode("utf-8", "replace"),
                    }
                )
                key = f"{method} {self.path.split('?', 1)[0]}"
                queue = server._script.get(key)
                if not queue:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(
                        json.dumps(
                            {"error": f"no scripted response for {key}"}
                        ).encode()
                    )
                    return
                resp = queue.pop(0) if len(queue) > 1 else queue[0]
                body = json.dumps(resp.body).encode()
                self.send_response(resp.status)
                self.send_header("Content-Type", "application/json")
                for k, v in resp.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                self._handle("GET")

            def do_POST(self) -> None:
                self._handle("POST")

        return Handler


# ----------------------------------------------------------------------------------
# Response builders — Anthropic Messages API shape (verified, see module docstring)
# ----------------------------------------------------------------------------------


def anthropic_success(
    *,
    text: str,
    input_tokens: int = 120,
    output_tokens: int = 60,
    stop_reason: str = "end_turn",
    provider_request_id: str | None = None,
) -> ScriptedResponse:
    return ScriptedResponse(
        status=200,
        body={
            "id": "msg_" + uuid.uuid4().hex[:20],
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5",
            "content": [{"type": "text", "text": text}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        },
        headers={"request-id": provider_request_id or ("req_" + uuid.uuid4().hex[:16])},
    )


def anthropic_transient_error(
    *, status: int = 500, kind: str = "api_error"
) -> ScriptedResponse:
    """500/503/529/429 -- all specified (ARCHITECTURE_V1.md §4.3) to map to
    ProviderTransientError. Verified for 500 -> InternalServerError and 429 ->
    RateLimitError against the real SDK (module docstring)."""
    return ScriptedResponse(
        status=status,
        body={
            "type": "error",
            "error": {"type": kind, "message": "simulated by QA fixture"},
        },
    )


def anthropic_permanent_error(
    *, status: int = 400, kind: str = "invalid_request_error"
) -> ScriptedResponse:
    return ScriptedResponse(
        status=status,
        body={
            "type": "error",
            "error": {"type": kind, "message": "simulated by QA fixture"},
        },
    )


# ----------------------------------------------------------------------------------
# Response builders — GitHub REST API shape
# ----------------------------------------------------------------------------------


def github_commits(messages: list[str]) -> ScriptedResponse:
    return ScriptedResponse(
        status=200,
        body=[
            {
                "sha": uuid.uuid4().hex,
                "commit": {
                    "message": m,
                    "author": {"date": "2026-08-10T09:00:00Z"},
                },
                "author": {"login": "some-dev"},
            }
            for m in messages
        ],
    )


def github_pulls(titles: list[str], *, draft: bool = False) -> ScriptedResponse:
    return ScriptedResponse(
        status=200,
        body=[
            {
                "number": i + 1,
                "title": t,
                "user": {"login": "some-dev"},
                "created_at": "2026-08-09T10:00:00Z",
                "updated_at": "2026-08-11T10:00:00Z",
                "draft": draft,
            }
            for i, t in enumerate(titles)
        ],
    )


def github_issues(items: list[tuple[str, str]]) -> ScriptedResponse:
    """`items` is a list of (title, body) pairs. GitHub's real `/issues` endpoint also
    returns pull requests (a documented M1 gotcha -- ARCHITECTURE_V1.md §9.3) -- this
    fixture returns issues only, deliberately, since the PR-double-count filter is the
    adapter's job, not this fixture's."""
    return ScriptedResponse(
        status=200,
        body=[
            {
                "number": 100 + i,
                "title": title,
                "body": body,
                "user": {"login": "some-reporter"},
                "created_at": "2026-08-08T10:00:00Z",
                "comments": 0,
            }
            for i, (title, body) in enumerate(items)
        ],
    )
