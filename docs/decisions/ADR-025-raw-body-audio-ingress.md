# ADR-025 — Audio is uploaded as a raw request body, not multipart; and the spoken answer is a GET

**Status:** Proposed (Architect, M9) · **Date:** 2026-08-19 · **Decider:** Solution Architect
**Context refs:** `ARCHITECTURE_V1.md` §9.5, §14.3; ADR-008 (browser↔API topology and the CSRF
control); `ARCHITECTURE_M9_VOICE.md` §4.2, §4.5, §13; `THREAT_MODEL.md` T-01, T-36, T-39.

## Context

Two transport questions, both of which look trivial and both of which have a wrong answer that works
until it doesn't.

**Ingress.** The obvious way to upload a recording is `multipart/form-data` with FastAPI's
`UploadFile`. **`python-multipart` is not installed** — verified: absent from
`apps/api/.venv/Lib/site-packages`, absent from `pyproject.toml`'s pinned list. And FastAPI's
`ensure_multipart_is_installed()` is called from `analyze_param` during **route registration**
(`fastapi/dependencies/utils.py:523`), not at request time — so a single `File(...)` parameter raises
`RuntimeError` at import and **the application does not start**.

**This was confirmed by execution, not by reading the source.** Registering
`@app.post("/x") async def x(f: UploadFile = File(...))` in this virtualenv raises
`RuntimeError: Form data requires "python-multipart" to be installed` at decoration time. The
distinction matters: had the check run per request, multipart would merely have been *unavailable* and
the choice below would be a preference. Because it runs at registration, choosing multipart without
adding the dependency is a boot failure, and adding the dependency is an act outside
`ARCHITECTURE_V1.md` §14.3's approved list — which is the owner's, not an engineer's.

**Egress.** The obvious way to play the answer is `POST /voice/speak` with the text, then feed the
response to an `<audio>` element. An `<audio>` element can only issue a **GET**, cannot carry a request
body, and cannot send a custom header — so `X-SUNIL-Client`, ADR-008's CSRF control, is unavailable on
the one request that must stream.

## Decision

### 1. Ingress: the raw blob as the request body

```
POST /api/v1/voice/transcribe
Content-Type: audio/webm        ← allow-listed; parameters (";codecs=opus") stripped before matching
X-Request-Id: <uuid4>
X-SUNIL-Client: web
X-Audio-Duration-Ms: 4820       ← advisory only
<body = the Blob, unwrapped>
```

* **No `python-multipart`, and therefore no dependency added to §14.3.** M9 adds none at all.
* The OpenAI SDK builds its own `multipart/form-data` on the outbound leg
  (`extract_files(...)` → `self._post(..., files=files)` → httpx2), so SUNIL never encodes or parses
  multipart anywhere. `FileTypes` accepts `(filename, bytes, content_type)`, verified from the
  installed package, so no temporary file is written either.
* **The body is read by iterating `request.stream()` with a running byte total, aborting past the
  limit — not `await request.body()`.** `Content-Length` is client-supplied; a lying header would
  otherwise buffer an unbounded body in memory (T-39).
* **The filename handed to the vendor is derived from the allow-listed content type**, never from the
  client, so nothing client-controlled reaches the outbound multipart part.
* **CORS: one entry to add.** `Content-Type: audio/webm` is not CORS-safelisted, so a preflight
  fires. `main.py` already allows `POST`/`OPTIONS` and the headers `Content-Type`, `X-SUNIL-Client`,
  `X-Request-Id` — **only `X-Audio-Duration-Ms` must be added to `allow_headers`.** Checked against the
  live middleware config rather than assumed.

### 2. Egress: `GET /api/v1/voice/speak/{message_id}`, and why dropping the client header is safe

```html
<audio crossorigin="use-credentials" src="http://localhost:8000/api/v1/voice/speak/{id}" autoplay>
```

**`SameSite=Lax` is the control**, and it is already configured (`build_session_middleware(...)`,
`same_site="lax"`). `localhost:3000` → `localhost:8000` is *same-site* — a site is scheme plus
registrable domain; ports are irrelevant — so SUNIL's own page sends the cookie. A genuinely cross-site
page embedding the same element is *cross-site*, Lax withholds the cookie, and the endpoint returns 401
having synthesised nothing and spent nothing. Layered on top:

1. **The endpoint takes a `message_id`, never text.** It is not a text-to-speech oracle the browser can
   drive with arbitrary input; the server loads `messages.content` itself. This also means the thing
   spoken is provably the thing shown.
2. **Ownership is checked**: assistant role, in a conversation owned by the session user, or **404** —
   not 403, because a 403 confirms the id exists (ET-17).
3. `message_id` is a UUID4 and is not guessable.
4. **A bounded in-process cache** (8 entries / 16 MiB / 10 min TTL, `app.state`, RAM only) makes replay
   free and caps repeat spend (T-36). RAM is not persistence, so this is consistent with ADR-021.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Add `python-multipart` and use `UploadFile`** | A dependency outside §14.3 for a single endpoint that needs one field. Every argument for it is convenience; the argument against is that the approved-dependency list is the mechanism that has kept this build honest, and "one small library" is how such lists stop working. The raw body costs about six lines. |
| **Base64 the audio into a JSON body** | 33% larger, buffered as a string, and it puts binary data through a JSON parser and a Pydantic validator for no benefit. It would also route audio through the same request-logging paths as text. |
| **`POST` the speak request and `await res.blob()`** | Keeps the client header — a genuine benefit — and **waits for the entire body**, discarding streamed synthesis, which is M9's only real latency win without M2 (ADR-024). |
| **`POST` + `res.body.getReader()` + `MediaSource.appendBuffer`** | Streams *and* keeps the client header, and needs a `MediaSource` codec-string dance plus `ManagedMediaSource` on Safari. Real complexity in a lane with **no frontend test runner** (M1 debt, deferred to M11), to re-obtain a control that `SameSite=Lax` already provides. |
| **A short-lived signed URL token in the path instead of the cookie** | Invents a second authentication scheme for one endpoint, with its own signing key, expiry and revocation questions — and the token then sits in browser history and in any log that records request paths. The session cookie is the scheme this system already has. |
| **Relax `require_client_header` to exempt GETs generally** | Widens a control across the whole API to serve one endpoint. The exemption is stated for this route, in this ADR, with its compensating controls named. |
| **Stream the audio over the existing SSE progress channel** | SSE is text-framed; binary would need base64 and re-framing, and ADR-009 defines that channel as *cosmetic by construction* — a turn completes identically if it never opens. Audio is not cosmetic. |

## Consequences

* **M9 adds no dependency, backend or frontend.** §14.3 needs no edit.
* `POST /api/v1/voice/transcribe` keeps the full ADR-008 guard set (session, client header, origin);
  `GET /api/v1/voice/speak/{id}` keeps session + `SameSite` + ownership and is the **only** endpoint in
  SUNIL that spends money without the client header. That exception is recorded here and in
  `THREAT_MODEL.md` T-36, not left to be inferred from the code.
* The 413/415 guards run **before** any byte is read, and the streamed read enforces the cap
  independently of `Content-Length`.
* Because the browser sends a preflight for every transcribe call, there is one extra round trip on the
  ingress leg. On loopback it is not measurable; over a network it would be, and `Access-Control-Max-Age`
  is already set to 600 s, so it is paid once per ten minutes.
