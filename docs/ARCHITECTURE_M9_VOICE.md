# SUNIL M9 — Voice: architecture

**Author:** Solution Architect, Minions Team 18 · **Status:** for owner review (Gate M9) · **Date:** 2026-08-19
**Parent architecture:** [`docs/ARCHITECTURE_V1.md`](ARCHITECTURE_V1.md) — `§n` below refers to *that*
document unless prefixed `R§` (roadmap) or `M9§` (this one).
**Plan of record:** [`docs/ROADMAP.md`](ROADMAP.md) — R§6 (voice is another interface), R§14 Epic 11,
R§16 Epic 5 (V2), R§23 Step 12.
**Requirements:** [`docs/REQUIREMENTS_V1.md`](REQUIREMENTS_V1.md) §4.11 — **one line, FR-200, COULD.**
M9§1 says why that is not enough to build from, and states the set it must become.
**Decisions:** ADR-019 … ADR-025 in [`docs/decisions/`](decisions/). **Threat model:**
[`docs/THREAT_MODEL.md`](THREAT_MODEL.md) §12 (added by this milestone).

---

## 0. How to read this, and the three rules that governed it

M1 is complete and live-verified: a real browser turn in **5.8 s** against real credentials, twelve
trace stages, one allowed tool call, one `llm_calls` row per provider attempt, `task=completed`.
M9 adds a **second interface** onto that system. It does not add a second system.

Three rules governed every decision below. They are the parent document's, unchanged:

1. **Deterministic code holds the privilege.** Audio is transport. It never produces a plan, never
   reaches an agent, never influences tool selection. Nothing in `sunil/speech/` can cause a tool to
   run.
2. **Nothing is claimed that the code will not have.** Where M9 cannot close a gap, the gap is named
   with the milestone that owns it (M9§12, M9§15). Several numbers in M9§9 are estimates and are
   labelled as estimates, with the task that replaces them by measurement.
3. **Every SDK fact below was read from — and where possible executed against — the installed
   package**, not documentation or memory. That discipline caught three real defects in M1, including
   one that would have pointed the whole exit suite at a live API with a real key. **It caught four
   more here**, all recorded where they bite: `python-multipart`'s absence stopping the app at *route
   registration* (M9§4.2, ADR-025 — confirmed by actually registering the route and catching the
   `RuntimeError`); the streamed-vs-buffered `iter_bytes()` trap and `AsyncResponseContextManager`
   having no `__await__` (M9§4.5); `AsyncTranscriptions.create` failing `iscoroutinefunction`
   (M9§4.3); and the `Voice` type alias disagreeing with its own docstring (M9§4.5).

**What the owner has already decided, and what this document therefore does not reopen:**

| Locked | Consequence here |
|---|---|
| Cloud STT and TTS via OpenAI (he holds the key, it is funded) | One vendor adapter, `sunil/speech/openai_speech.py`. R§16 Epic 5's local voice stays V2 |
| Push-to-talk — hold to speak, release to send | No wake word, no voice-activity detection, no always-open microphone. R§16 Epic 5 keeps wake-word in V2 |
| SUNIL speaks the answer **and** the text is still shown, with today's trace | FR-205 is a MUST, not a preference. Speech is additive to the screen, never a replacement for it |

---

## 1. The requirement gap — said plainly

`REQUIREMENTS_V1.md` §4.11 is one row:

> **FR-200 · COULD · M9** — Browser microphone input is transcribed by a cloud STT service, sent
> through the normal SUNIL conversation flow, and the response is spoken back via cloud TTS, streamed
> to the browser.

**That is a paragraph of intent, not a requirement set, and it cannot be built from or tested
against.** It does not say what happens to the recording; whether the owner sees the transcript
before a turn runs; what a spoken answer does when the answer is 6,000 characters long; what happens
when transcription returns an empty string; whether a failed TTS fails the turn; what the limits on a
recording are; or who decides those limits. Every one of those is a decision someone would otherwise
take silently during the build, and three of them are security decisions.

It is also mis-prioritised. A COULD is descopable; **"the text is still shown" and "the audio is not
persisted" are not descopable** — the first is the owner's explicit instruction and the second is the
entire capture-policy argument. A single COULD row cannot carry a MUST inside it.

**I am stating the replacement set here rather than briefing the BA, because I can state it precisely
and it is faster.** M9§14 is the normative set — fifteen FRs, three NFRs, six exit tests — written in
`REQUIREMENTS_V1.md`'s own table format so the BA or the Delivery Manager can lift it into §4.11
verbatim. M9§14 also names the two counter lines elsewhere in that document that must move with it, so
the merge does not leave the SRS internally inconsistent.

Until that merge happens, **M9§14 is the requirement of record for this milestone** and M9's exit
tests are graded against it.

---

## 2. Where STT and TTS live — arguing the boundary, because R§6 only gestures at it

R§6 says two things and joins them with a diagram:

> Voice is only another interface.
> The reasoning model does not need to be the same service used for STT or TTS.

The diagram puts *Speech-to-Text* above SUNIL and *Text-to-Speech* below it, with the Model Router in
between. Read literally, STT and TTS are **outside** the Model Router. This section argues that
reading is correct, because the alternative is tempting: both are "call a model at a vendor with a
key", the Model Router already does that, and a lazy design would add `LLMPurpose.STT` and be done in
an afternoon.

**Decision: STT and TTS adapters live in a new sibling package `sunil/speech/`. They are not
providers, they are not routed by the Model Router, and no agent, orchestrator or tool can reach
them.** ADR-019.

### 2.1 Four reasons, in decreasing order of force

**1. The Model Router's contract is text→text with structured output. Audio does not fit it, and
widening it breaks every existing caller.**

The interface is frozen at §4.2:

```python
class LLMProvider(Protocol):
    name: str
    def capabilities(self, model: str) -> ModelCapabilities: ...
    async def generate(self, model: str, request: LLMRequest) -> LLMResponse: ...
```

`LLMRequest` is `system` + `list[ChatTurn]` + `max_tokens` + `json_schema`. `LLMResponse` is
`text | data` + token counts. To carry audio, `LLMRequest.messages` would become a union that may hold
bytes, and every consumer would have to narrow it — the plan validator, the agent framework's
`ask_model`, the retry policy, and the redaction hook that scrubs `llm_calls.request_messages` before
insert. That is a breaking change to the one interface ADR-003 exists to keep stable, in exchange for
reusing about forty lines of retry code.

**2. The cost model is different, and forcing it into `llm_calls` would store numbers that are false.**

`llm_calls` has `input_tokens`, `output_tokens`, `cost_micro_usd` and `pricing_version`, all
`NOT NULL`, priced from `config/models.yaml`'s per-MTok table. Verified from the installed
`openai==3.1.0`:

* Transcription bills by **audio duration**. The response's `usage` is a discriminated union —
  `UsageTokens` or `UsageDuration(seconds: float, type: Literal["duration"])` — and *which* one you get
  depends on the model. `Transcription.usage` is also `Optional`, so it can be absent entirely.
* Synthesis returns **raw binary with no usage object at all**: `AsyncSpeech.create()` returns
  `_legacy_response.HttpxBinaryResponseContent`, which wraps an `httpx2.Response` and exposes
  `.content` / `.iter_bytes()` and nothing about billing. Cost must be derived from `len(input)`.

Writing an STT call into `llm_calls` therefore means inventing token counts or writing zeros. §13.1
says a turn's cost is "the sum over its attempts"; a zero row makes that sum wrong and silently
under-reports real spend. **A separate `speech_calls` table with `audio_ms` / `input_chars` columns
stores what actually happened** (M9§7).

**3. A vendor-neutral *routing* rule and a vendor-neutral *media* rule are different rules, and only
one of them belongs to the Model Router.**

§4.1's rule is "no agent, orchestrator or tool names a vendor; callers name a **capability**". M9 keeps
that rule and applies it to speech: `config/speech.yaml` maps the capabilities `transcription` and
`synthesis` onto `{provider, model, …}`, exactly as `config/models.yaml` does for reasoning. What M9
does **not** do is put the two capability spaces in one lookup, because they are selected on different
grounds — a reasoning capability is chosen by *the purpose of a turn stage*, a speech capability by
*the interface the request arrived on*. One is a property of the work, the other of the transport.
R§6's second sentence is exactly this distinction, and a shared registry would quietly couple them:
repointing `general_reasoning` at a local model in V2 would drag speech with it, or force an
`if capability.is_speech` branch into the router — the shape ADR-003 was written to prevent.

**4. It keeps the privilege boundary honest.**

TB3 (§9.3, threat model §4) is the boundary that matters: below it, external systems are reachable.
`AgentContext` grants four capabilities — `call_tool`, `ask_model`, `memory`, `trace` — and holds no
HTTP client and no secrets. If speech were a provider, `ask_model` would be one enum value away from
an agent being able to spend money on synthesis; worse, the transcription API takes a free-text
`prompt=` parameter that steers the model, so an agent with reach into that call would give
attacker-controlled tool output a path into the transcript. **`sunil/speech/` is reachable only from
`sunil/api/routes/voice.py`**, and M9§8.4 mechanises that as an import rule rather than leaving it as
an intention.

### 2.2 What is reused — the pattern, not the code

The speech package is a *sibling* of `providers/` and repeats its shape deliberately, so an engineer
who has read one can read the other:

| Pattern from `providers/` | Applied in `speech/` |
|---|---|
| A `Protocol` plus vendor-neutral request/response dataclasses (§4.2) | `SpeechProvider`, `TranscriptionRequest/Result`, `SynthesisRequest/Result` |
| Errors normalised at the boundary into SUNIL's own hierarchy | `SpeechTransientError` / `SpeechPermanentError` |
| **Classification by `status_code`, never by exception class name** (A-16) | Identical rule, identical `{408, 429} ∪ 5xx` transient set |
| `max_retries=0` on the SDK client; SUNIL owns retry so every attempt is individually persisted | Identical |
| `base_url` passed **explicitly** from `Settings`, never left to the SDK's own env reading (ADR-017) | Identical, and extended — M9§8 |
| A registry built once in the lifespan; a vendor with no key is simply not registered (T25) | Identical |
| One `llm_calls` row per provider **attempt** (A-2) | One `speech_calls` row per attempt |
| Capability → `{provider, model, …}` in a YAML registry cross-validated at startup | `config/speech.yaml` |

**No code is shared between the two packages.** A shared retry helper would create an import edge from
`speech/` into `core/routing/`, which is the coupling M9§2.1 exists to avoid; the duplicated logic is
roughly thirty lines and duplication is the cheaper half of that trade.

---

## 3. Component decomposition

```text
apps/api/sunil/
├── speech/                     NEW — the vendor-adapter package for media
│   ├── base.py                 SpeechProvider Protocol + dataclasses + error hierarchy
│   ├── openai_speech.py        the ONLY module here permitted to `import openai`
│   ├── registry.py             build_speech_registry(), validate_speech_capabilities()
│   └── service.py              SpeechService: retry, deadline, speech_calls rows, cost, capture
├── core/registry/speech.py     NEW — loads and cross-validates config/speech.yaml
├── api/routes/voice.py         NEW — the four voice endpoints
├── api/routes/chat.py          CHANGED — accepts input_modality, verifies its provenance
├── api/schemas.py              CHANGED — ChatRequest.input_modality + the voice envelopes
├── db/models.py                CHANGED — SpeechCall table, Message.input_modality
├── db/capture.py               CHANGED — resolves the new CaptureKind
├── capture.py                  CHANGED — CaptureKind.SPEECH_CALL
├── settings.py                 CHANGED — seven voice settings (M9§8.2)
└── main.py                     CHANGED — alembic head 0002; speech registry in the lifespan

config/speech.yaml              NEW — capability → {provider, model, timeout, pricing}
config/capture.yaml             CHANGED — the speech_call defaults

apps/web/src/
├── lib/useVoiceCapture.ts      NEW — the push-to-talk state machine
├── lib/voice.ts                NEW — the voice half of the API client
├── lib/earcon.ts               NEW — the zero-dependency capture-confirmation tone
├── components/chat/MicButton.tsx      NEW
├── components/chat/VoicePlayback.tsx  NEW
├── lib/useTurn.ts              CHANGED — carries inputModality; unchanged otherwise
└── app/(chat)/page.tsx         CHANGED — wiring

apps/api/migrations/versions/0002_voice.py   NEW
```

**Nothing under `core/orchestrator/`, `core/agent_framework/`, `core/routing/`, `agents/` or `tools/`
changes.** That is the test of R§6's "voice is only another interface", and M9§8.4 asserts it as an
import rule rather than leaving it as a claim.

---

## 4. The audio path, end to end, at real addresses and ports

My standing rule (memory L-001) is that no architecture is issued until one real mutating request has
been walked across every trust boundary at real addresses and ports, with every mechanism it needs
named in the config inventory. This section is that walk. **It found three things that would
otherwise have been discovered mid-build**, flagged 🔎 below.

**Addresses, from `.env.example` / §14.4:** browser `http://localhost:3000` (`WEB_ORIGIN`), API
`http://localhost:8000` (`NEXT_PUBLIC_API_BASE_URL`), OpenAI `https://api.openai.com/v1`
(`OPENAI_BASE_URL`), GitHub `https://api.github.com`.

### 4.1 Capture — browser, `http://localhost:3000`

```
pointerdown on MicButton
  └─ navigator.mediaDevices.getUserMedia({ audio: {
         channelCount: 1, echoCancellation: true,
         noiseSuppression: true, autoGainControl: true } })
  └─ new MediaRecorder(stream, { mimeType: <first supported>, audioBitsPerSecond: 24000 })
  └─ recorder.start(250)            // 250 ms timeslice: chunks accumulate, flush is fast
  └─ earcon("start")                // ~40 ms sine blip, Web Audio, no network
pointerup / pointercancel / lostpointercapture
  └─ recorder.stop()  →  ondataavailable* → onstop → new Blob(chunks, { type: mimeType })
```

* **Secure context.** `getUserMedia` requires one. 🔎 **`http://localhost:3000` qualifies** (browsers
  treat loopback as potentially-trustworthy), so dev works with no TLS. **The moment SUNIL is served
  from anything other than `localhost` over plain HTTP — a LAN IP, a hostname — the microphone silently
  returns nothing.** That is a deployment constraint on M9 and it is recorded as debt **D-14**; it is
  the same line `SessionMiddleware`'s `https_only=False` comment already anticipates.
* **Container/codec selection**, in order, by `MediaRecorder.isTypeSupported()`:
  `audio/webm;codecs=opus` → `audio/webm` → `audio/mp4` → `audio/ogg;codecs=opus` → the recorder's
  default. Chromium and Firefox give WebM/Opus; Safari gives MP4/AAC. **Both containers are on
  OpenAI's accepted list** — verified from the installed SDK's own `TranscriptionCreateParamsBase`
  docstring: *"flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, or webm"*. No transcoding is needed, and no
  audio library is added (M9§13).
* **Sizes.** Opus mono at 24 kbps ≈ **3 KB/s**. A 5-second utterance ≈ **15 KB**; the 60-second
  ceiling ≈ **180 KB**. Upload time over loopback is not a measurable component of the latency budget.
* **Client limits** (all served from the API, never hard-coded — M9§6.1): `MIN_MS = 300` (shorter is
  discarded silently, with no request: it was a mis-tap, not speech), `MAX_MS = 60_000` (hard stop,
  recorder stopped by a timer, the clip is still sent), `MAX_BYTES = 2 MiB`.
* **Slide-to-cancel.** `setPointerCapture` keeps the recording alive if the pointer leaves the button;
  releasing *outside* the button's bounds discards the clip instead of sending it.
* **Keyboard.** The mic control is a real `<button>`, so holding `Space`/`Enter` while it is focused
  fires `keydown`/`keyup` and drives the same state machine. `keydown` autorepeat is ignored via
  `event.repeat`.

### 4.2 Ingress — `POST http://localhost:8000/api/v1/voice/transcribe`

```
fetch("http://localhost:8000/api/v1/voice/transcribe", {
  method: "POST",
  credentials: "include",
  headers: { "Content-Type": "audio/webm",
             "X-SUNIL-Client": "web",
             "X-Request-Id": <uuid4 minted here, for the WHOLE voice turn>,
             "X-Audio-Duration-Ms": "4820" },
  body: blob,          // the raw Blob — NOT FormData
})
```

* 🔎 **CORS: no change is required, and I checked rather than assumed.** `Content-Type: audio/webm` is
  *not* a CORS-safelisted value, and `X-SUNIL-Client` / `X-Request-Id` / `X-Audio-Duration-Ms` are not
  safelisted headers, so the browser sends an `OPTIONS` preflight. `main.py`'s `CORSMiddleware` already
  allows `POST`/`OPTIONS` and the headers `Content-Type`, `X-SUNIL-Client`, `X-Request-Id` — **only
  `X-Audio-Duration-Ms` has to be added to `allow_headers`.** One list entry, named here so it is not
  found by a failing preflight in a browser console.
* **The body is the raw blob, not `multipart/form-data`.** 🔎 **`python-multipart` is not installed**
  (verified: absent from `apps/api/.venv/Lib/site-packages`, absent from `pyproject.toml`), and
  FastAPI's `ensure_multipart_is_installed()` runs during *route registration*
  (`fastapi/dependencies/utils.py:523`, from `analyze_param`) — so a single `File(...)` parameter would
  raise `RuntimeError` at import time and **the application would not start**. Taking the raw body
  avoids a new dependency entirely; see ADR-025.
* **Middleware order is unchanged**: CORS → `RequestContextMiddleware` (validates `X-Request-Id` is a
  UUID4 or 422; sets `request.state.request_id` and the turn clock) → `SessionMiddleware`.
* **Guards, in order, before a single byte is read into memory:**
  1. `require_owner_session` → 401.
  2. `require_client_header` → 403 (ADR-008's CSRF control; this is a mutating request).
  3. `SUNIL_VOICE_ENABLED` false → **404** (not 403 — a disabled feature should not confirm its own
     existence).
  4. Egress interlock (M9§8.1) fails → 503 with a named reason, and nothing is read.
  5. `Content-Type` not in the allow-list → **415**. Allow-list: `audio/webm`, `audio/ogg`,
     `audio/mp4`, `audio/mpeg`, `audio/wav`. Parameters (`;codecs=opus`) are stripped before matching.
  6. `Content-Length` absent or > `SUNIL_VOICE_MAX_UPLOAD_BYTES` → **413**.
  7. The body is read by iterating `request.stream()` with a running total, aborting at the limit —
     **not** `await request.body()`, because `Content-Length` is client-supplied and a lying header
     would otherwise buffer an unbounded body in memory.

### 4.3 STT — `https://api.openai.com/v1/audio/transcriptions`

```python
# sunil/speech/openai_speech.py — the only module in this package importing a vendor SDK
client = AsyncOpenAI(
    api_key=settings.openai_api_key.get_secret_value(),
    base_url=settings.openai_base_url,     # explicit — ADR-017, never the SDK's env reading
    max_retries=0,                         # SUNIL owns retry, so each attempt is persisted
    timeout=capability.timeout_s,
)
result = await client.audio.transcriptions.create(
    file=(f"speech{ext}", audio_bytes, content_type),   # filename derived from the ALLOW-LIST, never the client
    model=capability.model,                             # config/speech.yaml
    response_format="json",
    language=capability.language,                       # "en" by default; improves accuracy AND latency
    temperature=0,
    # prompt= is NEVER set. See below.
)
transcript = result.text
```

Verified against the installed `openai==3.1.0`:

* `AsyncTranscriptions.create(*, file: FileTypes, model, …)` and
  `FileTypes` accepts `Tuple[Optional[str], FileContent, Optional[str]]` where
  `FileContent = IO[bytes] | bytes | PathLike` — so a `(filename, bytes, content_type)` tuple is the
  supported shape and **no temporary file is written**.
* The SDK builds the `multipart/form-data` request itself
  (`extract_files(...)` → `self._post(..., files=files)` → httpx2). **SUNIL never encodes or parses
  multipart**, which is why M9§4.2's raw-body ingress costs nothing.
* `AudioModel` is `Literal["whisper-1", "gpt-transcribe", "gpt-4o-transcribe",
  "gpt-4o-mini-transcribe", "gpt-4o-mini-transcribe-2025-12-15", "gpt-4o-transcribe-diarize"]`.
  `config/speech.yaml` pins **`gpt-4o-mini-transcribe`** — the fastest of the accurate ones, which is
  the axis that matters here (M9§9).
* For `gpt-4o-transcribe` / `gpt-4o-mini-transcribe` the SDK docstring states **the only supported
  `response_format` is `json`** — so `verbose_json`, and with it word-level timestamps, is not
  available on the chosen model. M9 does not need them.
* **`prompt=` is never set, and that is a security decision, not an omission.** It is free text that
  steers the model's output. Passing anything derived from a message, a tool result or a previous
  transcript there would create a path for external content to shape a transcript that the orchestrator
  then treats as the owner's own words. Threat **T-38**.
* ⚠️ **`AsyncTranscriptions.create` is not detectable as a coroutine function.** Verified by
  introspection against the installed package: `inspect.iscoroutinefunction(client.audio.transcriptions
  .create)` is **`False`**, because the method is wrapped by the SDK's `@required_args` decorator —
  though calling it does return a coroutine, so `await` works normally. Any test double, `autospec`
  mock, or wrapper that decides whether to await by introspection will get this wrong. `AsyncSpeech
  .create` has no such decorator and *is* detectable. Named here so it is not diagnosed at 2 a.m.

**Retry.** One retry on transient (`408`, `429`, any 5xx, or a connection/timeout error with no status
— A-16's rule verbatim), no retry on permanent. Each attempt writes its own `speech_calls` row. The
STT leg has its own timeout from `config/speech.yaml` (default 20 s) and **does not** consume the
`SUNIL_TURN_DEADLINE_S` budget, because it is not part of the turn — the turn has not started yet.

**Response to the browser:**

```json
{ "request_id": "…", "transcript": "check the workforce repo",
  "audio_ms": 4820, "stt_ms": 940, "auto_send": true }
```

An empty or whitespace-only transcript returns `transcript: ""` with HTTP 200 and the client shows
*"I didn't catch that"* and returns to idle — **no turn is started** (FR-212).

### 4.4 The turn — `POST http://localhost:8000/api/v1/chat`, unchanged

The browser sends the transcript to the **existing** chat endpoint with the **same** `X-Request-Id`:

```
POST /api/v1/chat
X-Request-Id: <the same uuid4>
{ "message": "check the workforce repo", "conversation_id": …, "input_modality": "voice" }
```

* 🔎 **The transcription leg writes no `audit_events` row, and it must not.** `audit_events` has
  `UniqueConstraint("request_id", "seq")` and `LiveTraceContext` numbers a turn's stages 1…12 from its
  own in-memory counter. If the transcribe leg emitted stage rows under the same `request_id`, the
  chat turn's `seq` values would collide on insert and ET-6 ("exactly twelve, in order, from
  `audit_events` alone") would become ambiguous or fail outright. **Sharing the `request_id` is
  therefore only safe because the speech legs record themselves in `speech_calls`, never in
  `audit_events`.** That is not a convenience; it is the reason ADR-023 works.
* **`input_modality="voice"` is verified, never trusted.** The route checks that a `speech_calls` row
  exists with `direction="stt"`, `request_id` equal to this request's, `user_id` equal to the session
  owner, and `status="ok"`. No row → **422**, no turn runs. Without that check the modality flag is a
  free-text provenance claim, and provenance claims end up in a training corpus (ADR-014's whole
  argument). Exit test **ET-16**.
* Everything else is byte-for-byte the M1 path: gateway → orchestrator → validated plan → Project
  Manager agent → read-only GitHub tool → analysis → response, twelve stages, ~5.8 s.

### 4.5 Egress — `GET http://localhost:8000/api/v1/voice/speak/{message_id}`

🔎 **This is the third finding, and it changed the design.** The obvious shape — `POST /voice/speak`
with the text in the body, then feed the response to an `<audio>` element — does not work, because an
`<audio>` element can only issue a **GET**, cannot carry a request body, and cannot send a custom
header. So `X-SUNIL-Client` (ADR-008's CSRF control) is unavailable on the one request that must
stream. The alternatives were:

| Option | Verdict |
|---|---|
| `POST` + `await res.blob()` + `URL.createObjectURL` | Works, keeps the client header — but **waits for the entire body**, discarding the streaming win that is M9's main latency lever |
| `POST` + `res.body.getReader()` + `MediaSource.appendBuffer` | Streams, but needs a `MediaSource` codec-string dance and `ManagedMediaSource` on Safari. Real complexity in a lane with **no frontend test runner** (M1 debt, deferred to M11) |
| **`GET` + `<audio crossorigin="use-credentials" src=…>`** | **Chosen.** The browser streams progressive MP3 natively, playback starts before the download finishes, and the client code is one attribute |

**The GET is safe, and the reason is `SameSite=Lax`, which is already configured**
(`build_session_middleware(...)`, `same_site="lax"`). `localhost:3000` → `localhost:8000` is
*same-site* (a site is scheme + registrable domain; ports are irrelevant), so SUNIL's own page sends
the cookie. A genuinely cross-site page embedding
`<audio src="http://localhost:8000/api/v1/voice/speak/…">` is *cross-site*, Lax withholds the cookie,
and the endpoint answers 401 having synthesised nothing and spent nothing. Layered on top:

1. **The endpoint takes a `message_id`, never text.** It is not a text-to-speech oracle the browser can
   drive with arbitrary input. The server loads `messages.content` itself.
2. **Ownership is checked**: the message must be `role="assistant"` and sit in a conversation owned by
   the session user, or **404** (not 403 — a 403 confirms the id exists). Exit test **ET-17**.
3. **`message_id` is a UUID4** and is not guessable.
4. **A bounded in-process cache** (`app.state`, 8 entries / 16 MiB / 10 min TTL, RAM only) makes replay
   free and caps repeat spend. It holds audio in memory, never on disk — consistent with M9§7's "no
   persistence path".

```python
# streamed straight through, chunk by chunk
async with client.audio.speech.with_streaming_response.create(
        input=text, model=capability.model, voice=capability.voice,
        response_format="mp3", stream_format="audio",
        instructions=capability.instructions,      # ignored by tts-1/tts-1-hd; we use gpt-4o-mini-tts
) as upstream:
    async for chunk in upstream.iter_bytes():
        yield chunk
```

Verified against the installed `openai==3.1.0`:

* `client.audio.speech.with_streaming_response.create(...)` returns an
  `AsyncResponseContextManager[AsyncStreamedBinaryAPIResponse]`, and
  `AsyncAPIResponse.iter_bytes()` is an **async** generator (`openai/_response.py:472`). The plain
  `await create(...)` path returns `HttpxBinaryResponseContent` whose `iter_bytes()` is **synchronous**
  and iterates an already-buffered body — using it would look like streaming and stream nothing.
* ⚠️ **`AsyncResponseContextManager` has `__aenter__` and no `__await__`.** Verified by introspection.
  So `await client.audio.speech.with_streaming_response.create(...)` is a `TypeError`, not a slow path —
  it must be `async with`. This is the mistake an engineer makes by pattern-matching the non-streaming
  call above it, and it fails immediately rather than subtly, which is the good case.
* `SpeechModel` is `Literal["tts-1", "tts-1-hd", "gpt-4o-mini-tts", "gpt-4o-mini-tts-2025-12-15"]`;
  `config/speech.yaml` pins **`gpt-4o-mini-tts`**.
* `response_format` ∈ `mp3 | opus | aac | flac | wav | pcm`; `stream_format` ∈ `sse | audio`, and the
  SDK notes `sse` is unsupported on `tts-1`/`tts-1-hd`.
* ⚠️ **One SDK inconsistency worth knowing:** the `Voice` type alias is
  `Union[str, Literal["alloy","ash","ballad","coral","echo","sage","shimmer","verse","marin","cedar"], VoiceID]`,
  but the *docstring* on the same parameter also lists `fable`, `onyx` and `nova`. Because the alias
  admits bare `str`, an unlisted voice type-checks and may still 400 at runtime. `config/speech.yaml`
  therefore pins a voice **from the Literal** (`alloy`), and the registry validates the configured
  value against that Literal at startup rather than at first synthesis.
* ⚠️ **`input` is capped at 4096 characters** by the API. `SUNIL_VOICE_MAX_SPEAK_CHARS` (default
  **2000**) truncates at a sentence boundary below that hard limit; the full answer stays on screen and
  the response carries `X-Speech-Truncated: true` so the UI can say so (FR-210). Without this a long
  answer is a 400 from the vendor at the worst possible moment.

**Invariant: a TTS failure never fails a turn.** The answer already exists, is persisted, and is on
screen. A failed synthesis surfaces as a muted-playback state on that message, and the `speech_calls`
row records `status="error"` with its `error_kind` (FR-207).

### 4.6 Playback and the trace

`<audio>` plays progressively; a stop control halts it (FR-213); replay re-requests the same URL and
is served from the cache (FR-214). The `TraceDisclosure` for the message gains one line sourced from
`speech_calls` — *"Spoken · gpt-4o-mini-tts · 0.6 s"* — rendered **below** the twelve stages and
visually distinct from them, because it is not a stage (ADR-023).

### 4.7 The whole path on one line

```
mic ─(WebM/Opus ≈15 KB)→ localhost:3000 ─(POST raw body, cookie+client header)→ localhost:8000
     ─(multipart, SDK-built, Bearer key)→ api.openai.com/v1/audio/transcriptions
     ─(transcript)→ localhost:8000 ─(JSON)→ localhost:3000
     ─(POST /api/v1/chat, same X-Request-Id)→ localhost:8000 ─ …the unchanged M1 turn… → answer
     ─(GET /voice/speak/{id}, Lax cookie)→ localhost:8000
     ─(JSON, Bearer key)→ api.openai.com/v1/audio/speech ─(MP3 chunks)→ localhost:8000
     ─(audio/mpeg, chunked)→ <audio> on localhost:3000
```

Every mechanism this path needs — `allow_headers`, the client header, the session cookie's
`SameSite`, the `X-Request-Id` validator, the base URL and its guard, the alembic head — is named in
M9§8.2's config inventory or already in §14.4.

---

## 5. Why a voice turn reuses `POST /api/v1/chat` rather than forking the orchestrator

**Decision: three requests, one `request_id`, and the middle request is today's chat endpoint,
unmodified except for one optional, server-verified field.** ADR-020.

```
POST /api/v1/voice/transcribe      audio  → transcript      (new)
POST /api/v1/chat                  text   → answer          (EXISTING — the only change is one field)
GET  /api/v1/voice/speak/{id}      id     → audio/mpeg      (new)
```

### 5.1 The rejected alternative, and why it is genuinely tempting

`POST /api/v1/voice/turn` — audio in, audio out, one request, everything server-side. It saves two
round trips (~60 ms on loopback, i.e. nothing), and it *looks* like the cleanest interface. It was
rejected for four reasons:

1. **It hides the transcript until the turn is over.** The transcript is the single artefact the owner
   must be able to see and correct, because an STT error is otherwise indistinguishable from SUNIL
   misunderstanding him. Showing it at ~1 s instead of ~7 s is the difference between "it misheard me"
   and "it's broken".
2. **It forks the turn contract.** `ChatResponse` is the frozen §6 envelope — `outcome`, `message`,
   `task`, `failure`, `trace[]`, `usage` — and four M1 components read it: `useTurn`, `ErrorCard`'s
   four variants, `TraceDisclosure`, and QA's exit assertions. A second endpoint returning a
   different-shaped turn means two response contracts, two failure vocabularies and two sets of tests
   for one pipeline.
3. **It triples the endpoint's deadline.** `SUNIL_TURN_DEADLINE_S` (40 s) is calibrated to the reasoning
   turn and sits below the client's 45 s abandon. A combined endpoint would have to cover STT + turn +
   TTS under one clock, and the first thing to be squeezed on a slow day would be the retry budget of
   the part that matters.
4. **It couples cancel to the wrong thing.** ADR-010 makes cancel client-side in M1. With three
   requests, cancelling playback and cancelling the turn are naturally separate actions on separate
   requests. With one request they are one abort, and stopping the audio would abandon a turn that has
   already completed and been paid for.

### 5.2 The one change to the chat surface

```python
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    input_modality: Literal["text", "voice"] = "text"      # NEW, defaults to today's behaviour
```

Additive, defaulted, and **verified server-side** (M9§4.4) rather than believed. Every existing client,
test and fixture keeps working untouched — which is the property that makes this a one-field change
rather than a contract change.

### 5.3 Auto-send, and the condition under which it stops being safe

When `auto_send` is true (default), the transcript is rendered as the user's message and the turn
starts immediately — no confirmation step. Requiring a click would break the interaction the owner
asked for: hold, speak, release, hear the answer.

**This is safe today for a stated, expiring reason.** M1's only reachable tool operation is
read-only, single-repository, and an unrecognised project produces a graceful `unknown_project`
(ET-11). A misheard instruction can therefore cause a wrong *read* and a wrong *answer* — never a wrong
*action*. **That property expires when M5/M6 add write-capable operations**, at which point a misheard
command is an executed command. It is recorded as **DC-17** with M5 as the owning milestone, and
`SUNIL_VOICE_AUTO_SEND` exists precisely so the default can be flipped in one config edit when that
day comes. The permission engine's `ASK_USER` path (DC-2) is the real answer; auto-send is not a
control and this document does not present it as one.

---

## 6. API surface added

### 6.1 `GET /api/v1/voice/capabilities`

Session required. The client's only source of its own limits.

```json
{ "enabled": true, "max_ms": 60000, "min_ms": 300, "max_upload_bytes": 2097152,
  "accepted_mime_types": ["audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav"],
  "auto_send": true, "max_speak_chars": 2000, "ack": "earcon" }
```

This exists for the same reason `GET /api/v1/projects` exists (A-14): **a product whose entire claim is
that it does not fabricate must not fabricate its own capability list.** A hard-coded client limit
that disagrees with the server produces a 413 the user cannot explain. When `enabled` is false the
client renders no microphone control at all — not a disabled one.

### 6.2 `POST /api/v1/voice/transcribe`

Body: raw audio bytes. Headers: `Content-Type` (allow-listed), `X-Request-Id` (UUID4),
`X-SUNIL-Client`, `X-Audio-Duration-Ms` (advisory).
Responses: `200 {request_id, transcript, audio_ms, stt_ms, auto_send}` · `401` · `403` · `404`
(voice disabled) · `413` · `415` · `422` (bad request id) · `502` (`{"detail": "stt_failed",
"error_kind": …}`) · `503` (egress interlock).

### 6.3 `GET /api/v1/voice/speak/{message_id}`

Session required (Lax cookie; no custom header is possible — M9§4.5). `200 audio/mpeg` chunked, with
`X-Speech-Truncated` and `Cache-Control: private, max-age=600` · `404` (unknown, not owned, or voice
disabled) · `502` · `503`.

### 6.4 `GET /api/v1/voice/ack` — OPTIONAL (T38, the descope lever)

Returns a short spoken acknowledgement (`"Okay."`) synthesised once and held in the same bounded RAM
cache. `404` when `SUNIL_VOICE_ACK != "spoken"`. M9§9.4 explains why this is worth a whole endpoint and
why it is nevertheless the first thing to drop.

### 6.5 Copy ownership is unchanged

§11.2's rule holds: the API sends enums and numbers; every human-readable string — *"I didn't catch
that"*, *"Microphone blocked"*, *"Playback unavailable"* — lives in `apps/web/src/lib/copy.ts` and is
the Designer's to change without a backend deploy.

---

## 7. Audio is content, and the capture policy applies to it

ADR-014 governs what may become training data. It was written for text. **Audio is worse than text in
three specific ways, and the policy has to answer for that** — ADR-021.

1. **A person speaking aloud says things they would never type.** Reading a password to yourself while
   you look for it, a client's full name, a third party audible in the room. Typing is edited; speech
   is not.
2. **Redaction cannot work on audio.** §8.3's mechanism walks strings, dicts and lists and replaces
   registered secret values and pattern matches. There is no mechanism in SUNIL — and no cheap one
   anywhere — that removes a spoken API key from a waveform. **`redacted_full` is therefore not
   achievable for audio bytes, and a policy value that cannot be honoured must not be offered for
   them.**
3. **A voice recording is biometric.** A stored corpus of the owner's speech is a voiceprint. That is a
   different category of data from a stored corpus of his typing, and it deserves a different default.

### 7.1 The decision

| Artefact | What happens | Configurable |
|---|---|---|
| **The captured audio bytes** | **Discarded at the end of the request.** One request-scoped `bytes` object, handed to the STT client, dropped when the response returns. **There is no column and no default file path that can hold it** | `SUNIL_VOICE_AUDIO_RETENTION` = **`discard`** (default) \| `local_file` |
| **The transcript** | Becomes `messages.content` for the user's turn — exactly as a typed message would — governed by the existing `message` capture kind (`redacted_full / internal / standard`) | via `config/capture.yaml` as today |
| **The transcript's second copy in `speech_calls`** | **Not written by default.** The `speech_call` kind defaults to **`metadata_only`**: duration, bytes, model, latency, cost, error kind — no content | `config/capture.yaml` → `speech_call` |
| **The synthesised reply audio** | Streamed to the browser; held in a bounded RAM cache for ≤10 min; **never written to disk or to the database** | not configurable |

**The default is: the recording is discarded, and only its transcript survives — once, in the place a
typed message would have lived.**

### 7.2 Why `metadata_only` for `speech_call`, not `none` and not `redacted_full`

`none` would null the *metadata* columns too and destroy the cost and latency record — the thing
FR-209 exists for. `redacted_full` would store the transcript **twice** (once in `messages.content`,
once in `speech_calls.transcript`) under two independent policies, so tightening one would silently
leave the other in place. `metadata_only` keeps the shape and drops the duplicate. Setting
`speech_call: redacted_full` is genuinely implemented — it writes `speech_calls.transcript` — and is
useful for debugging a bad transcription, which is why it is a real config value and not decoration.

### 7.3 `local_file`, and exactly what turning it on means

`SUNIL_VOICE_AUDIO_RETENTION=local_file` writes the clip to `var/voice/<request_id>.<ext>` (mode
`0600`; `var/` is already gitignored) and records the path in `speech_calls.audio_path`, which is
`NULL` under the default. It is implemented so the setting is a real choice rather than theatre, and
because reproducing a bad transcription is otherwise impossible. **Turning it on means accepting that
anything spoken is on disk verbatim, unredactable and unredacted, including anything said by accident.**
That sentence is in `.env.example` next to the setting. Nothing purges it — the same gap
`retention_class` already has (debt D-11, M11) — and it is not exempted from that gap.

### 7.4 The vocabulary addition, following Amendment 1 exactly

`CaptureKind` is **table-keyed** — one member per capture-column-bearing table (ADR-014 Amendment 1),
because the four capture columns live *on the row*. M9 adds one table, so it adds exactly one member:

```python
class CaptureKind(StrEnum):
    MESSAGE = "message"; PLAN = "plan"; LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"; MEMORY = "memory"
    SPEECH_CALL = "speech_call"      # NEW — one member, one table
```

`ContentSource` gains no member. A transcript is the owner speaking, so `source=OWNER`; a synthesis
input is SUNIL's own prior output, so `source=SUNIL_GENERATED`. `audit_events` still has no member and
never will.

### 7.5 What M9 does *not* claim here

* `full_local_only` remains **recorded, not enforced** (ADR-014, debt D-13). M9 changes nothing about
  that and does not imply otherwise.
* `retention_class` on `speech_calls` is written and **nothing purges it** (D-11).
* "Discarded" means *no code path writes it*. It does **not** mean the bytes are scrubbed from process
  memory, from the OS socket buffers, or from whatever the vendor does with them after receipt. The
  last of those is the one that matters and it is a contractual question, not an architectural one —
  threat **T-40**, accepted, with the mitigation being that the owner chose this vendor knowingly.

---

## 8. The egress guard extends here

ADR-017 exists because an env-settable API base URL is an exfiltration channel: redirect it and every
prompt leaves, and the GitHub one carries `Authorization: Bearer <PAT>` to whatever host is named. The
guard — *a non-canonical base URL must be loopback, or the application refuses to boot* — is enforced
by one validator in `settings.py`.

**An STT endpoint receives the owner's live microphone audio.** Prompts are text the owner composed;
audio is a recording of a room he is sitting in. That is a materially different disclosure, and the
loopback exception is what makes the difference matter: ADR-017 reasoned that a hostile local process
"could already read `.env`", so loopback added no meaningful exposure. **That reasoning does not carry
over.** A process that can read `.env` gains prompts it could have read from `var/sunil.db` anyway; a
process that receives audio gains something that exists nowhere else on the machine.

### 8.1 The control — ADR-022

1. **The existing validator covers speech unchanged.** The speech adapter is constructed from
   `settings.openai_base_url`, which already has `_check_openai_base_url` on it. A non-canonical,
   non-loopback value still refuses to boot. **No new base-URL setting is introduced, so no new hole
   is introduced** — one canonical host, one validator, one place to review.
2. **NEW — the interlock: a loopback base URL disables voice unless separately opted into.**

   ```
   openai_base_url is canonical            → voice available
   openai_base_url is loopback
        and SUNIL_VOICE_ALLOW_LOOPBACK_EGRESS is false (default) → voice endpoints return 503
        and SUNIL_VOICE_ALLOW_LOOPBACK_EGRESS is true            → voice available (QA's harness)
   anything else                           → the app does not boot (ADR-017, unchanged)
   ```

   The reasoning is one sentence: **"a local test double may receive my prompts" and "a local process
   may receive my microphone" are different consents, and one flag should not grant both.** The
   interlock is checked at startup (logged) *and* per request (so flipping it needs a restart, which is
   ADR-016's model). Exit test **ET-18**.
3. **A single startup line naming where audio goes**, following ADR-017's "both are logged at startup,
   which is how a wrong one becomes visible immediately":
   `voice.egress base_url=https://api.openai.com/v1 canonical=true stt=gpt-4o-mini-transcribe tts=gpt-4o-mini-tts retention=discard`
4. **`SUNIL_VOICE_ENABLED` ships `false`** and is flipped to `true` when the last M9 task lands and is
   verified — the same pattern `SUNIL_PROGRESS_EVENTS` used (§8.4). **It is a delivery switch, not a
   security control**, and it is not presented as one: the controls are items 1–3 and 5.
5. **The audio has exactly one way out of the process**, and it is mechanised — M9§8.4.

### 8.2 Config inventory additions (`.env.example` / §14.4)

| Variable | Example | Used by | Secret |
|---|---|---|---|
| `SUNIL_VOICE_ENABLED` | `false` | voice routes — delivery switch, ships `false` (M9§8.1 item 4) | no |
| `SUNIL_VOICE_ALLOW_LOOPBACK_EGRESS` | `false` | voice routes — **the interlock**; must be `true` for a loopback speech double | no |
| `SUNIL_VOICE_AUDIO_RETENTION` | `discard` | `speech/service.py` — `discard` \| `local_file`. See the warning in M9§7.3 | no |
| `SUNIL_VOICE_AUTO_SEND` | `true` | `/voice/capabilities` — flip to `false` when write-capable tools land (DC-17) | no |
| `SUNIL_VOICE_MAX_UPLOAD_BYTES` | `2097152` | `/voice/transcribe` — 413 above this | no |
| `SUNIL_VOICE_MAX_SPEAK_CHARS` | `2000` | `/voice/speak` — truncate at a sentence boundary below the API's 4096 hard cap | no |
| `SUNIL_VOICE_ACK` | `earcon` | `/voice/capabilities` — `earcon` \| `spoken` \| `none` (T38) | no |

No new secret, no new base URL, no new outbound destination. `OPENAI_API_KEY` and `OPENAI_BASE_URL` are
reused — one key per vendor, exactly as R§6's "the reasoning model does not need to be the same
service" is honoured by *adding a second speech provider with its own credentials later*, following
ADR-003 §4.6's recipe, not by splitting one vendor's key in two.

### 8.3 The cross-validation rule

`config/speech.yaml`'s `provider` values are cross-validated at startup against the **speech** registry,
and a speech capability that resolves to a vendor with no registered key is a loud, named startup
failure — mirroring `validate_capability_providers()` (T25) exactly. Voice being *enabled* while its
capability points at an unregistered vendor is a boot failure, not a 500 on the owner's first press.

### 8.4 The import rules that mechanise "voice is only another interface"

`tests/security/test_import_boundaries.py` (DC-10) gains one amended rule and one new one:

| Rule | Change |
|---|---|
| *"only `sunil/providers/` imports a vendor SDK"* | **Amended** to *"only `sunil/providers/` and `sunil/speech/` import a vendor SDK"*. Both are vendor-adapter packages; nothing else in the tree may be. The parametrised `test_dc10_rules_are_all_covered` list moves with it |
| *"only `sunil/api/routes/voice.py` imports `sunil.speech.*`"* | **New.** `core/`, `agents/` and `tools/` cannot reach speech at all. This is the mechanised form of R§6's sentence, and it is the fourth argument of M9§2.1 turned into a test |

---

## 9. Latency — the honest number

The brief is right that this is the design problem that actually matters. A 5.8 s wait is comfortable
when reading and long when talking to something. This section derives the number, separates what is
measured from what is estimated, and says plainly which fixes belong to M9 and which need M2.

### 9.1 The budget, leg by leg

| # | Leg | Time | Source |
|---|---|---|---|
| 1 | Release → blob assembled (stop, final `dataavailable`, `onstop`) | **50–150 ms** | ESTIMATE — MediaRecorder flush with a 250 ms timeslice |
| 2 | Upload, 5 s clip ≈ 15 KB, loopback | **10–30 ms** | Arithmetic. Not a factor |
| 3 | Guards, body read, `speech_calls` insert | **<20 ms** | Same shape as existing route work |
| 4 | **STT round trip** — `gpt-4o-mini-transcribe`, 5 s of audio, non-streaming | **0.6–1.5 s** | **ESTIMATE — unverifiable here. T37 measures it** |
| 5 | Client renders transcript, POSTs `/api/v1/chat` | **<30 ms** | |
| 6 | **The turn** | **5.8 s** | **MEASURED**, one real run. Median and p95 unknown — §5.2's honesty applies unchanged |
| 7 | **TTS to first audio byte**, streamed | **0.3–0.8 s** | **ESTIMATE — T37 measures it** |
| 7b | *(TTS to last byte, non-streamed, ~500 chars)* | *1.0–2.5 s* | ESTIMATE — the fallback if streaming does not deliver |
| 8 | Browser decode + playback start | **50–150 ms** | ESTIMATE |

**Release → first word of the answer ≈ 6.9–8.5 s; call it ~7.5 s typical.**
Against 5.8 s of text today, **voice adds ~1.1–2.7 s**, and the felt cost is worse than the arithmetic,
because in a text turn the user is *reading* and in a voice turn the user is *waiting in silence*.

### 9.2 What M9 can do about it

**(a) Kill the silence at the front — the largest perceived win, and nearly free.**
An earcon on release (leg 1, ~50 ms) confirms capture, and the transcript appears on screen at ~1 s.
**Time to first feedback goes from ~7.5 s to ~0.05 s**, and time to first *meaningful* feedback (the
transcript — proof SUNIL heard the right words) to ~1 s. The earcon is a 40 ms Web Audio oscillator
blip: no network, no vendor, no dependency, no cache, and it works when everything else has failed.

**(b) Stream the synthesis.** `with_streaming_response.create(...)` + `stream_format="audio"` + a
`StreamingResponse` forwarding chunks + native `<audio>` progressive playback takes leg 7 from
~1.0–2.5 s to ~0.3–0.8 s. **Verified achievable from the installed SDK**, and it needs nothing from M2,
because it streams *finished text* — it does not need the reasoning model to stream.

**(c) Start synthesis the instant the POST resolves.** Not cleverness, just not waiting for React to
paint first.

**(d) A spoken acknowledgement — OPTIONAL, T38.** *"Okay."* played at ~1 s alongside the transcript.
It is honest at that moment because SUNIL genuinely has heard and understood the words, and it is
shown on screen simultaneously. Synthesised once and cached in RAM, so it costs one round trip in the
process's lifetime, not one per turn. It is the first thing to descope: the earcon plus the on-screen
transcript already carry the message.

**(e) What I am NOT recommending: speaking progress.** *"Working out a plan…"* spoken over a 6 s wait
costs a TTS round trip per phase, talks over the user, and — the real objection — a spoken phase label
is a claim about progress that the four-phase model deliberately does not make. §5.3 of the chat spec
rejected a percentage bar for exactly this reason: *"M1 cannot know true % complete, and a fake
percentage would be dishonest."* The same argument applies with more force when it is said out loud.
The existing `WorkIndicator` stays visible and silent, and it is enough.

**Net effect of (a)–(c): first sound ~0.05 s, transcript ~1 s, first spoken word of the answer ~7 s.**
The wait does not get shorter. It stops being silent, which is the part that was actually broken.

### 9.3 What genuinely needs M2, stated so nobody promises it

**Synthesising the answer before the whole answer exists.** That requires token streaming from the
reasoning model (`stream=True` on chat completions), which is **BL-001 / M2 / NFR-061** — the SRS
already puts "streamed responses begin within 3 seconds" there, and `REQUIREMENTS_V1.md` already lists
BL-009 (voice) as depending on BL-001 (streaming). With it, incoming text is chunked at sentence
boundaries and each sentence is synthesised while the next is still being generated, so speech starts
at roughly the first sentence: **release → first spoken word ≈ 2.5–3.5 s** instead of ~7 s. That is the
change that makes it feel like a conversation, and **M9 cannot deliver it.**

**The seam M9 leaves so M2 is additive, not a rewrite:**

* `SpeechProvider.synthesize()` takes a `str` today; M2 adds `synthesize_stream(chunks: AsyncIterator[str])`
  beside it. The protocol grows a method; nothing existing changes signature.
* **The client side is already built by M9.** `<audio>` progressive playback over a chunked
  `audio/mpeg` response does not care whether the server is forwarding one upstream synthesis or
  concatenating six. M2's work is entirely server-side.
* The `speech_calls` row already carries `attempt` and per-call cost, so N sentence-level syntheses
  are N rows and the cost arithmetic stays true with no schema change.

Also V2, not M9, per R§16 Epic 5: **barge-in** (speaking over SUNIL to interrupt), offline STT/TTS, and
wake-word. M9 gives a stop button, not voice interruption.

### 9.4 Honesty about these numbers

Legs 1, 4, 7, 7b and 8 are **estimates**. This environment has no network access and no key in the
shell, so I could not measure them, and I will not present modelled numbers as measured ones — the same
discipline `config/models.yaml` already applies to OpenAI's pricing, where zeros are written rather
than guesses. **T37 measures all five legs across 10 runs and replaces this table with observed medians
and maxima**, reporting per leg, exactly as §5.2 requires latency to be reported ("median and max of N
observed turns … not arithmetic theatre"). If streamed TTS does not deliver early bytes in practice,
leg 7 becomes leg 7b and the total moves by ~1–1.7 s; that contingency is why both rows are in the
table.

---

## 10. What the twelve trace stages become when the input was spoken

**They stay exactly twelve, in exactly the same order, with exactly the same names.** ADR-023.

A voice turn is a chat turn. The audio is transport. `audit_events` holds the turn's *reasoning*
spine; `llm_calls` and `tool_calls` are sibling records that the stages point at, and **`speech_calls`
is a third sibling of exactly the same kind**. Neither `llm_calls` nor `tool_calls` is a stage; neither
is speech.

### 10.1 What a voice turn's trace looks like

```
speech_calls   direction=stt   request_id=R   status=ok   latency_ms=940       ← before the turn
audit_events   seq 1..12       request_id=R                                    ← the turn, unchanged
speech_calls   direction=tts   request_id=R   status=ok   latency_ms=610       ← after the turn
```

One `request_id` joins all three. `GET /api/v1/trace/{request_id}` (T13) reassembles them in timestamp
order, and NFR-020's actual claim — reconstructable from stored records alone — holds for a voice turn
exactly as it does for a typed one.

### 10.2 The two `detail` contract additions (§3.4's table)

| Stage | New contracted `detail` keys |
|---|---|
| `message_received` | `input_modality` (`"text"` \| `"voice"`); **when voice**: `stt_ms`, `audio_ms`, `stt_model` |
| `final_response` | `output_modality_requested` (`"text"` \| `"voice"`) — what the client asked for, not what happened |

`final_response` carries no `tts_ms`, because **stage 12 fires before synthesis is requested** and this
document does not put a number in a field that cannot be known yet. The TTS timing lives on the
`speech_calls` row, which is written when it is actually known. `detail` still carries no untrusted
content, and **the transcript is not put in `detail`** — it is the message, and it lives in
`messages.content` (T-32's rule, unchanged).

### 10.3 Why not add stages, and why not a separate `request_id`

| Rejected | Why |
|---|---|
| **Add `speech_transcribed` / `speech_synthesised` as stages 0 and 13** | `TraceStage` is the frozen §6 contract; ET-6 asserts `set(emitted) == set(TraceStage)`. Adding members makes them mandatory for **every** turn, so every typed turn would fail ET-6 — or ET-6 weakens to "at least the twelve", which is exactly the assertion that stops catching a missing stage. It would also force a frontend phase-map change for a milestone that has no frontend test runner |
| **Emit the existing stages twice, once per leg** | Breaks §3.4's "each stage is emitted at most once per turn", which `LiveTraceContext` enforces with `DuplicateStageEmission`. It is also false: nothing was planned or permitted during transcription |
| **Give each leg its own `request_id`** | Then nothing joins a voice turn together, and the owner debugging "why did it mishear me" has three unrelated ids. The trace's whole value is that one id reconstructs one interaction |
| **Share the `request_id` *and* write audit rows from the speech legs** | Collides on `UniqueConstraint(request_id, seq)` — M9§4.4's 🔎 finding. It would have been discovered as an `IntegrityError` under load, intermittently |

**Consequence, stated so it is not a surprise:** ET-6 is unchanged and untouched by M9, and a new exit
test **ET-13** asserts the *equivalence* — a spoken request produces the same twelve stages, in the same
order, as the equivalent typed request, with exactly twelve `audit_events` rows.

---

## 11. Data model — migration `0002_voice`

The first migration since `0001_initial`. `EXPECTED_ALEMBIC_HEAD` in `main.py` moves to `"0002"` in the
same change, or the app refuses to boot (§7.4's fail-closed check, working as designed).

### 11.1 `speech_calls` (new)

Carries the four ADR-014 capture columns, like every other capture-path table.

| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` PK | uuid4 |
| `request_id` | `String(36)` NOT NULL, indexed | the turn's id — the join to `audit_events` / `llm_calls` |
| `user_id` | FK `users.id` NOT NULL, indexed | the provenance check in M9§4.4 keys on this |
| `conversation_id` | FK `conversations.id` NULL | null for the STT leg (no conversation yet) |
| `message_id` | FK `messages.id` NULL | set on the TTS leg — what was spoken |
| `direction` | `String(10)` NOT NULL | `stt` \| `tts`, CHECK-constrained like every other enum column |
| `capability` | `String(50)` NOT NULL | `transcription` \| `synthesis` |
| `provider` / `model` | `String(50)` / `String(100)` NOT NULL | |
| `attempt` | `Integer` NOT NULL | **one row per attempt** (A-2's rule, applied here) |
| `status` | `String(20)` NOT NULL | `ok` \| `error` |
| `audio_ms` | `Integer` NULL | STT: `usage.duration.seconds` when present, else the advisory client header, else NULL |
| `audio_bytes` | `Integer` NULL | STT: bytes received. TTS: bytes streamed out |
| `input_chars` | `Integer` NULL | TTS: `len(input)` — the billing unit |
| `transcript_chars` | `Integer` NULL | STT: `len(text)` — kept under `metadata_only`, where the text is not |
| `transcript` | `Text` NULL | **content column.** NULL under the `metadata_only` default |
| `audio_path` | `String(500)` NULL | NULL unless `SUNIL_VOICE_AUDIO_RETENTION=local_file` |
| `truncated` | `Boolean` NOT NULL default false | TTS: the answer exceeded `max_speak_chars` |
| `cost_micro_usd` | `BigInteger` NOT NULL | from `config/speech.yaml` |
| `pricing_version` | `String(20)` NOT NULL | stamped per call, same rule as `llm_calls` |
| `latency_ms` | `Integer` NOT NULL | |
| `error_kind` | `String(50)` NULL | |
| `provider_request_id` | `String(100)` NULL | |
| `created_at` | tz timestamp NOT NULL | |
| `capture_policy`, `sensitivity`, `retention_class`, `training_eligible` | ADR-014's four | resolved by `resolve_capture(kind=SPEECH_CALL, …)` |

### 11.2 `messages.input_modality` (new column)

`String(10)` NOT NULL, default `'text'`, CHECK `IN ('text','voice')`. Back-filled to `'text'` for every
existing row, which is true. It is the durable fact that distinguishes a transcript from typed text —
and it matters beyond display: **a transcript has different error characteristics from typed text**
(homophones, dropped words, punctuation invented by the model), and a V3 corpus that cannot tell them
apart will learn from both as if they were the same artefact. That is ADR-014's argument applied to a
new axis, and it is why this is a column rather than a `detail` key.

### 11.3 Portability

`0002` obeys §7.2's non-negotiables: no SQLite-only or Postgres-only types, `String(n)` everywhere,
`BigInteger` for money, tz-aware timestamps, enums as CHECK constraints. Debt **D-2** (verify the
migration once against real PostgreSQL before Gate 3) now covers two migrations instead of one; Docker
is running, so this is cheaper than it was.

---

## 12. Security — additions to the threat model

Written into `docs/THREAT_MODEL.md` §12 by this milestone, which also adds **TB8** (API ↔ speech
vendor, drawn separately from TB2 for the reason ADR-022 gives) and **A8** (captured audio and its
transcript) to the asset list. Summarised here so this document stands alone.

| ID | Threat | Control | Status |
|---|---|---|---|
| T-35 | **Microphone audio egress to an unintended host** — the ADR-017 loopback exception now covers live audio, not just prompts | Canonical-or-loopback validator (unchanged) **plus** the M9§8.1 interlock: loopback disables voice unless separately opted in | **Mitigated** |
| T-36 | **Denial of wallet via the speak endpoint** — repeated synthesis of the same or arbitrary text | The endpoint takes a `message_id`, not text; ownership is checked; a bounded RAM cache serves replays; `SameSite=Lax` withholds the cookie cross-site | **Mitigated** |
| T-37 | **False provenance** — a client claims `input_modality="voice"` for typed text, contaminating a future corpus | Server-side check for a matching `speech_calls(stt, ok)` row owned by the same user; 422 otherwise (ET-16) | **Mitigated** |
| T-38 | **Injection into the transcript via the STT `prompt=` parameter** | The parameter is never set, by any code path. Asserted by a security test that greps the speech package | **Mitigated** |
| T-39 | **Unbounded upload** — a lying `Content-Length`, or a 500 MB body | Allow-listed `Content-Type` (415), `Content-Length` cap (413), **and** a running byte count while iterating `request.stream()` that aborts past the limit | **Mitigated** |
| T-40 | **The vendor retains the audio** — SUNIL's discard policy governs SUNIL's disk, not OpenAI's | None available architecturally. The owner chose a cloud STT vendor knowingly; R§16 Epic 5's local voice is the answer and it is V2 | **Accepted, by explicit roadmap design.** Deferred → V2 |
| T-41 | **Spoken secrets** — the owner reads a password aloud while a recording is running | Audio is discarded by default (M9§7.1) and **is never redactable** (M9§7). The transcript passes through §8.3's redaction like any other text, which catches `sk-…`-shaped tokens but not a spoken passphrase | **Partial, and stated as partial.** The residual is real; the mitigation is the default retention policy, not detection |
| T-42 | **Microphone available over an insecure origin** — `getUserMedia` needs a secure context, and any plain-HTTP origin other than `localhost` silently yields nothing | None needed today (single machine, loopback). Hosting means TLS, and the session cookie's `https_only=False` moves at the same time | **Not reachable today; recorded so hosting does not rediscover it.** Debt D-14 |

**Deferred controls added to the register:**

| # | Deferred control | Owning milestone |
|---|---|---|
| DC-17 | **Auto-send is safe only while every reachable operation is read-only.** When write-capable tools land, a misheard command becomes an executed command; the answer is the `ASK_USER` approval path (DC-2), not a voice-specific control | **M5** |
| DC-18 | Purge of `var/voice/` under `local_file` retention — nothing purges, same gap as `retention_class` (D-11) | M11 |
| DC-19 | Rate limiting on the voice endpoints. M1/M9 have one user and no limiter anywhere in the system; the speak endpoint's cache caps the common case but not a determined loop | M11 |

---

## 13. Dependencies — §14.3

**M9 adds no dependency, backend or frontend.** That is worth stating loudly, because the naive
version of this milestone adds three.

| Tempting | Not needed, because |
|---|---|
| `python-multipart` | 🔎 Not installed, and FastAPI's `ensure_multipart_is_installed()` runs at **route registration** (`fastapi/dependencies/utils.py:523`, from `analyze_param`), so one `File(...)` parameter stops the app booting. **Confirmed by execution, not by reading:** registering `@app.post("/x") async def x(f: UploadFile = File(...))` in this venv raises `RuntimeError: Form data requires "python-multipart" to be installed` at decoration time. The raw-body ingress (ADR-025) avoids it entirely |
| `pydub` / `ffmpeg` / `soundfile` | No transcoding: WebM/Opus and MP4/AAC are both on the vendor's accepted list, verified from the installed SDK's own docstring |
| `sse-starlette` | Already rejected at §14.3; TTS uses `StreamingResponse`, ~15 lines |
| A frontend audio library (`wavesurfer`, `recorder.js`) | `MediaRecorder`, `getUserMedia`, `AudioContext` and `<audio>` are platform APIs. The frontend still has **no test runner** (M1 debt, deferred to M11) and this is not the milestone to add one — M9's frontend is verified by review plus the browser-level exit tests, and that limitation is stated rather than papered over |

`openai==3.1.0` is already on the approved list — **the owner authorised the OpenAI dependency on
2026-08-17** (T23, `docs/SECRETS_SETUP.md` §0) — and it carries both `audio.transcriptions` and
`audio.speech`. **§14.3 needs no edit for M9.**

---

## 14. The requirement set FR-200 must become

Normative for M9. Written in `REQUIREMENTS_V1.md`'s format so §4.11 can be replaced with it verbatim.

### 14.1 Functional (replaces §4.11)

| ID | Pri | M | Statement | Ref |
|---|---|---|---|---|
| FR-200 | MUST | M9 | Push-to-talk capture: while the microphone control is held the browser records; on release, recording stops and the clip is submitted. There is no wake word and no always-open microphone. | R§14 Epic 11 |
| FR-201 | MUST | M9 | A recording shorter than the configured minimum is discarded in the browser with no request sent. | M9§4.1 |
| FR-202 | MUST | M9 | The clip is transcribed by a cloud STT service and the transcript is returned to the browser and displayed to the owner. | R§14 Epic 11 |
| FR-203 | MUST | M9 | A transcribed request runs through the unmodified `POST /api/v1/chat` path — same orchestrator, plan validation, permission engine and twelve trace stages as a typed request. | R§6, ADR-020 |
| FR-204 | MUST | M9 | The server accepts `input_modality="voice"` only when it itself produced a successful transcription for that `request_id` and that owner; otherwise the request is rejected and no turn runs. | ADR-020 |
| FR-205 | MUST | M9 | The assistant's answer is displayed as text in every case, whether or not it is spoken, with the trace available as today. | owner instruction |
| FR-206 | MUST | M9 | The assistant's answer is spoken back via cloud TTS, streamed to the browser and played progressively. | R§14 Epic 11 |
| FR-207 | MUST | M9 | A synthesis failure never fails the turn: the text answer stands, and the failure is surfaced as a playback-unavailable state on that message. | M9§4.5 |
| FR-208 | MUST | M9 | Under the default configuration the captured audio is not persisted: no database column and no file holds it after the request ends. | ADR-021 |
| FR-209 | MUST | M9 | Every STT and TTS attempt records provider, model, attempt number, duration or size, latency, cost and error kind, linked to the turn's `request_id`. | ADR-019, §13.1 |
| FR-210 | SHOULD | M9 | An answer longer than the configured spoken-length limit is spoken up to a sentence boundary within that limit; the full answer remains on screen and the truncation is indicated. | M9§4.5 |
| FR-211 | SHOULD | M9 | The client obtains its capture limits, accepted formats and send behaviour from the server, never from a hard-coded list. | A-14's precedent |
| FR-212 | SHOULD | M9 | An empty or unintelligible transcription does not start a turn; the owner is told nothing was caught. | M9§4.3 |
| FR-213 | COULD | M9 | Playback can be stopped by the owner at any point. | R§16 Epic 5 is where interruption proper lives |
| FR-214 | COULD | M9 | A previously spoken answer can be replayed without re-synthesis. | M9§4.5 |

### 14.2 Non-functional

| ID | Pri | M | Statement | Verification method |
|---|---|---|---|---|
| NFR-013 | MUST | M9 | Microphone audio leaves the machine only to the canonical speech host; a loopback destination requires a separate, explicit opt-in, and any other destination prevents the application from starting. | Startup test with a non-canonical host (refuses to boot); request test with a loopback host and the opt-in unset (503, nothing sent) — ET-18 |
| NFR-052 | MUST | M9 | Captured audio has no persistence path under the default configuration: no schema column and no file receives it. | Schema review plus a filesystem and database diff across a complete voice turn — ET-15 |
| NFR-062 | SHOULD | M9 | Release → first audible feedback ≤ 1.5 s. Release → first spoken word of the answer ≤ 9 s at the median. | 10 timed runs, reporting **median and maximum per leg** (capture, STT, turn, TTS-to-first-byte, playback start) — never a single figure — T37 |

### 14.3 Exit tests

| ID | Test |
|---|---|
| ET-13 | A spoken request and the equivalent typed request produce the same twelve trace stages in the same order, and the spoken turn has exactly twelve `audit_events` rows. |
| ET-14 | A completed voice turn has exactly two `speech_calls` rows (one `stt`, one `tts`) sharing the turn's `request_id`, each with non-null provider, model, latency and cost. |
| ET-15 | Across a complete voice turn under the default configuration, no audio bytes are written to the database or the filesystem. |
| ET-16 | `POST /api/v1/chat` with `input_modality="voice"` and no server-side transcription for that `request_id` is rejected 422 and runs no turn (no `audit_events`, no `llm_calls`, no `tool_calls`). |
| ET-17 | `GET /api/v1/voice/speak/{message_id}` for a message in another user's conversation returns 404 and produces no `speech_calls` row and no upstream call. |
| ET-18 | With `OPENAI_BASE_URL` loopback and `SUNIL_VOICE_ALLOW_LOOPBACK_EGRESS` unset, every voice endpoint returns 503 and no audio leaves the process. |

### 14.4 The two counter lines that must move with this

`REQUIREMENTS_V1.md` states totals in two places. Replacing §4.11 changes both:

* *"**Total functional requirements (all milestones): 61.**"* → **75** (FR-200 becomes FR-200…FR-214).
* The backlog row **BL-009** ("Voice V1 … depends on BL-001/M2") stays true and should now read that the
  **conversational** experience depends on M2 streaming, while M9 delivers the interface — M9§9.3.
* The M1 count (39) is unchanged: no M9 requirement is an M1 requirement.
* **§5.1's heading claims a 1:1 mapping onto R§26's twelve security rules, and NFR-013 is a
  thirteenth.** It is a genuine security NFR and it is *not* one of the twelve; the heading must say so
  ("the twelve rules, mapped 1:1, plus NFR-013 which R§26 does not cover") rather than the new row
  quietly making the existing sentence false. Flagged because it is exactly the kind of counter
  inconsistency a partial merge leaves behind.

---

## 15. What M9 does not have, said before anyone claims it does

| Not in M9 | Where it is |
|---|---|
| Speech starting before the answer is complete | **M2** — needs token streaming (NFR-061, BL-001). M9§9.3 |
| Barge-in / interruption by speaking | **V2** — R§16 Epic 5 |
| Wake word, always-listening, voice activity detection | **V2** — R§16 Epic 5, kept there by the owner |
| Offline/local STT and TTS | **V2** — R§16 Epic 5 |
| Any control over what the vendor does with received audio | Nowhere in V1. T-40, accepted |
| Redaction of spoken secrets | Impossible on audio; partial on the transcript. T-41 |
| Purge of retained clips under `local_file` | **M11** — DC-18 |
| Rate limiting on voice endpoints | **M11** — DC-19 |
| A frontend regression test for the push-to-talk state machine | **M11** — the no-test-runner debt, unchanged. M9's frontend is verified by review and by browser-level exit tests, which is weaker and is stated as weaker |
| Speaker identification, multi-speaker, diarization | Not a V1 requirement. The SDK supports it (`gpt-4o-transcribe-diarize`); nothing in SUNIL asks for it |

---

## 16. Debt added by this milestone

| # | Debt | Owner |
|---|---|---|
| D-14 | **Voice requires a secure context.** `http://localhost` qualifies; any other plain-HTTP origin silently yields no microphone. Hosting SUNIL means TLS, and `https_only=False` on the session cookie moves at the same time | M11 / whoever hosts it |
| D-15 | `config/speech.yaml`'s prices ship as **clearly-marked zeros**, exactly as `config/models.yaml`'s OpenAI entry does, because they are not verifiable from any local source. Voice cost reads as 0 until they are filled in, and the file says so | first person with the pricing page |
| D-16 | Five of the eight latency legs in M9§9.1 are estimates until T37 measures them | T37 |
| D-17 | `0002` is the second migration never verified against real PostgreSQL (extends D-2) | before Gate 3 |
