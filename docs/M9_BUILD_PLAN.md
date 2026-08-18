# M9 — Voice: build plan (T27 … T38)

**Author:** Solution Architect, Minions Team 18 · **Date:** 2026-08-19
**Architecture:** [`docs/ARCHITECTURE_M9_VOICE.md`](ARCHITECTURE_M9_VOICE.md) — `M9§n` below.
**Decisions:** ADR-019 … ADR-025. **Requirements of record:** `ARCHITECTURE_M9_VOICE.md` §14 until the
BA merges it into `REQUIREMENTS_V1.md` §4.11.
**Git workflow (Delivery Manager's document, in force):** [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md) —
one branch per task, `task/T<n>-<slug>`, cut from current `main`, never committed to `main`.

---

## 0. The three rules M1 learned the hard way

1. **Exclusive file ownership, and it means the whole file.** M1's one cross-lane collision came from
   an ambiguous instruction, not from the rule failing. §1 below assigns every file to exactly one
   task. Two tasks share `sunil/main.py` (T27 and T32) and that sharing is resolved **in time, not in
   space**: T32 does not start until T27 has merged.
2. **A branch is green against what it was cut from, not against what exists.** This was M1's recurring
   defect — three confirmed instances. Every M9 task **merges current `main` into its branch and re-runs
   the full suite before requesting review.** A green branch that has not seen `main` since it was cut
   is not evidence.
3. **Verify SDK facts against the installed package.** Not the docs, not this plan, not memory. It
   caught three defects in M1 and two more while this architecture was written.

**Test-file collisions:** M1 lost a whole collection run to two `test_capture.py` files in directories
with no `__init__.py`. Every new test module below has a globally unique basename. Check before adding
one that is not on this list.

---

## 1. File ownership map — every file, exactly one owner

| File | Owner |
|---|---|
| `apps/api/sunil/settings.py` | **T27** |
| `apps/api/sunil/capture.py` | **T27** |
| `apps/api/sunil/db/models.py` | **T27** |
| `apps/api/sunil/db/capture.py` | **T27** |
| `apps/api/migrations/versions/0002_voice.py` | **T27** |
| `config/capture.yaml` | **T27** |
| `.env.example` | **T27** |
| `config/speech.yaml` | **T28** |
| `apps/api/sunil/core/registry/speech.py` | **T28** |
| `apps/api/sunil/core/registry/loader.py` | **T28** |
| `apps/api/sunil/speech/{__init__,base,openai_speech,registry}.py` | **T29** |
| `apps/api/sunil/speech/service.py` | **T30** |
| `apps/api/sunil/api/schemas.py` | **T31** |
| `apps/api/sunil/api/routes/chat.py` | **T31** |
| `apps/api/sunil/api/routes/voice.py` | **T32** |
| `apps/api/sunil/api/routes/__init__.py` | **T32** |
| `apps/api/sunil/main.py` | **T27**, then **T32** (strictly sequential — §0 rule 1) |
| `apps/web/src/lib/useVoiceCapture.ts`, `lib/earcon.ts`, `components/chat/MicButton.tsx` | **T33** |
| `apps/web/src/lib/voice.ts`, `components/chat/VoicePlayback.tsx`, `lib/useTurn.ts`, `lib/copy.ts`, `components/chat/{index.ts,types.ts}`, `app/(chat)/page.tsx` | **T34** |
| `apps/api/tests/security/test_import_boundaries.py`, `tests/security/test_voice_egress.py`, `tests/security/test_voice_capture.py` | **T35** |
| `apps/api/tests/exit/_speech_double.py`, `tests/exit/test_et13_*.py` … `test_et18_*.py` | **T36** |
| `apps/api/tests/integration/test_voice_latency_live.py`, `docs/worklog/2026-08-2x-m9-latency.md` | **T37** |
| `apps/api/sunil/speech/ack.py`, `apps/web/src/lib/spokenAck.ts` | **T38** (optional) |
| Unit tests under `tests/unit/**` | the task that owns the module under test; basenames listed per task |

**Documents nobody on this milestone edits:** `docs/STATUS.md`, `docs/GIT_WORKFLOW.md` (Delivery
Manager's), `docs/ARCHITECTURE_V1.md` §14.3 (no dependency changes — M9§13).

---

## 2. Dependency graph and the critical path

```
T27 ──┬─► T28 ──► T29 ──► T30 ──┬─► T31 ──► T32 ──► T34 ──► T36
      │                          │            ▲       ▲
      │                          └────────────┘       │
      └─────────────────────────────► T33 ────────────┘
                                                       └─► T37
T35 depends on T29 + T32 (it tests their boundaries)
T38 depends on T30 + T32, and is optional
```

**Critical path: T27 → T28 → T29 → T30 → T31 → T32 → T34 → T36.** T33 (the capture hook) has real
slack and can run beside the backend from day one, because it talks to `/voice/capabilities` and
`/voice/transcribe` — both frozen in M9§6 before either exists.

**The frozen contract for M9** is `ARCHITECTURE_M9_VOICE.md` §6 (the four endpoints and their exact
envelopes) plus §11 (the schema). Build against those, not against each other. A change to either is
an Architect ruling, not a lane decision.

---

## 3. Backend core lane (BE-1)

### T27 — Data model, settings, capture vocabulary, migration `0002`

**Deps:** none. **On the critical path — everything waits on this.**
**Owns:** `apps/api/sunil/{settings.py,capture.py,main.py}`, `apps/api/sunil/db/{models.py,capture.py}`,
`apps/api/migrations/versions/0002_voice.py`, `config/capture.yaml`, `.env.example`.

**Build:**
* `CaptureKind.SPEECH_CALL` — **one new member, table-keyed** (ADR-014 Amendment 1). No new
  `ContentSource` member: a transcript is `OWNER`, a synthesis input is `SUNIL_GENERATED`.
* `SpeechCall` model exactly per M9§11.1, inheriting `CaptureColumns`, with
  `enum_check_constraint("direction", …)` and `_capture_check_constraints("speech_calls")` like every
  peer table.
* `Message.input_modality`: `String(10)` NOT NULL default `'text'`, CHECK `IN ('text','voice')`.
* `db/capture.py`: `resolve_capture()` handles `SPEECH_CALL`; the writer nulls `transcript` under
  `none`/`metadata_only` on the **same writer path** the other kinds already use — no second mechanism.
* Migration `0002_voice`: create table, add column with a server default, back-fill `'text'`, add the
  CHECK. Downgrade drops both. Obeys §7.2 portability (no dialect-specific types).
* `main.py`: `EXPECTED_ALEMBIC_HEAD = "0002"`. **Nothing else in this file** — the lifespan wiring is
  T32's, and T32 starts after this merges.
* `settings.py`: the seven `SUNIL_VOICE_*` fields of M9§8.2 with their defaults, plus a model-level
  validator implementing the **egress interlock** (M9§8.1 item 2): if `openai_base_url` is loopback and
  `sunil_voice_allow_loopback_egress` is false, voice is *unavailable* — expose it as a computed
  `voice_available: bool`, do **not** raise. Raising would stop QA booting an app with a speech double,
  and ADR-017's boot-refusal already covers the case that must be fatal.
* `config/capture.yaml`: a `speech_call` block, `capture_policy: metadata_only`, `sensitivity:
  internal`, `retention_class: standard`, with the M9§7.2 reasoning as a comment.
* `.env.example`: the seven variables, and **the M9§7.3 warning sentence next to
  `SUNIL_VOICE_AUDIO_RETENTION`** in full.

**Tests** (`tests/unit/test_voice_settings.py`, `tests/unit/test_speech_call_model.py`,
`tests/unit/test_migration_0002.py`, additions to `tests/unit/test_db_capture.py`):
`speech_call` resolves to `metadata_only` from the real config · a `metadata_only` decision writes
`transcript IS NULL` and `transcript_chars` non-null · `training_eligible` stays derived · the
`direction` CHECK rejects a third value · `input_modality` rejects a third value and defaults to
`'text'` · `0002` upgrades and downgrades cleanly on SQLite · **canonical base URL → `voice_available`
true; loopback + interlock false → false; loopback + interlock true → true; a non-canonical
non-loopback URL still refuses to construct `Settings`** (ADR-017 unchanged).
**Satisfies:** FR-208, FR-209, NFR-052 (schema half). **Exit tests:** ET-14, ET-15, ET-18 (foundations).

### T30 — `SpeechService`: retry, deadline, persistence, cost, capture

**Deps:** T27, T29. **On the critical path.**
**Owns:** `apps/api/sunil/speech/service.py`.

**Build:** `SpeechService.transcribe(...)` and `.synthesize(...)`, each taking already-validated
inputs and a `sessionmaker`, and each:
* resolving the capability from the speech registry (T28) — never naming a vendor;
* running **one retry on transient only** (A-16's rule: no-status connection/timeout, 408, 429, any
  5xx are transient; **everything else, including any exception class this plan does not name, is
  permanent**);
* writing **one `speech_calls` row per attempt**, including the failed one, via `resolve_capture()`;
* computing cost from `config/speech.yaml` (STT per audio-second, TTS per input character) and
  stamping `pricing_version`;
* honouring `SUNIL_VOICE_AUDIO_RETENTION` — under `local_file`, writing `var/voice/<request_id>.<ext>`
  with mode `0600` and recording `audio_path`; under `discard`, **no filesystem call exists on the
  path at all**, not a no-op wrapper;
* returning a streaming async iterator for synthesis, never a buffered `bytes`.

**Tests** (`tests/unit/speech/test_speech_service.py`): two rows on one transient retry, one on
success, one on a permanent failure with `status="error"` and an `error_kind` · cost arithmetic against
a pinned price table · `metadata_only` nulls `transcript` while keeping `transcript_chars` ·
`local_file` writes exactly one file with the expected mode and records the path; `discard` writes none
(assert on a tmp-path tree that stays empty) · a synthesis longer than `max_speak_chars` is truncated at
a sentence boundary and sets `truncated=True`.
**Satisfies:** FR-207, FR-209, FR-210, NFR-052. **Exit tests:** ET-14, ET-15.

### T31 — The chat surface: `input_modality`, its provenance check, and the voice envelopes

**Deps:** T27, T30. **On the critical path.**
**Owns:** `apps/api/sunil/api/schemas.py`, `apps/api/sunil/api/routes/chat.py`.

**Build:**
* `ChatRequest.input_modality: Literal["text","voice"] = "text"` — additive and defaulted, so every
  existing client, fixture and test is untouched.
* **The provenance check** (M9§4.4): when `"voice"`, require a `speech_calls` row with
  `direction="stt"`, `status="ok"`, this `request_id`, and `user_id` equal to the session owner.
  Missing → `HTTPException(422)` raised **before** `handle_chat_turn()` runs, so no `messages` row, no
  `audit_events` row and no LLM call happen. It is a malformed request, not a turn outcome — the same
  category `UnknownConversationError` already maps to 422.
* `messages.input_modality` is written from the verified value, never from the claim.
* `message_received`'s `detail` gains `input_modality`, and when voice also `stt_ms`, `audio_ms`,
  `stt_model`, read from the `speech_calls` row. `final_response`'s `detail` gains
  `output_modality_requested`. **No transcript in `detail`** (T-32).
* All four voice envelopes from M9§6 defined here, so T32 imports them rather than redefining them —
  the frozen-contract pattern M1 used.

**Tests** (`tests/unit/api_routes/test_chat_input_modality.py`): default is `"text"` and behaviour is
byte-identical to today · `"voice"` with a matching row runs the turn and writes
`messages.input_modality="voice"` · `"voice"` with no row → 422 **and zero rows in `messages`,
`audit_events`, `llm_calls`, `tool_calls`** · `"voice"` with a row owned by another user → 422 · a
third modality value → 422 from Pydantic · `message_received.detail` carries the contracted keys.
**Satisfies:** FR-203, FR-204. **Exit tests:** ET-13, ET-16.

### T32 — The voice routes and the app wiring

**Deps:** T27, T28, T29, T30, T31 — **and T27 must be merged before this branch is cut** (§0 rule 1,
`main.py`). **On the critical path.**
**Owns:** `apps/api/sunil/api/routes/voice.py`, `apps/api/sunil/api/routes/__init__.py`,
`apps/api/sunil/main.py` (second owner, sequentially).

**Build:** the four endpoints of M9§6, with the guard order of M9§4.2 **exactly as listed** —
session → client header → enabled (404) → egress interlock (503) → content type (415) → length (413)
→ streamed read with a running byte cap. Plus:
* `GET /voice/speak/{message_id}`: **no client-header requirement** (an `<audio>` element cannot send
  one — M9§4.5) and therefore an ownership check that is not optional: assistant role, conversation
  owned by the session user, else **404**. `StreamingResponse(media_type="audio/mpeg")` forwarding
  `iter_bytes()` chunk by chunk.
* The bounded RAM cache on `app.state` — 8 entries / 16 MiB / 10 min TTL. **This is the named descope
  lever for this task:** dropping it costs a re-synthesis on replay and nothing else.
* `main.py`'s lifespan: build the speech registry, call `validate_speech_capabilities()`, hang
  `app.state.speech`, log the M9§8.1 item 3 egress line, and add `X-Audio-Duration-Ms` to
  `CORSMiddleware`'s `allow_headers` (M9§4.2's 🔎 finding — one list entry).

**Tests** (`tests/unit/api_routes/test_voice_routes.py`): each guard in order, each with its own status
code · a 3 MiB body with a truthful `Content-Length` → 413; a 3 MiB body with a **lying** 1 KB
`Content-Length` → also 413, and memory does not grow past the cap · `audio/aiff` → 415 · voice
disabled → 404 not 403 · speak for another user's message → 404 **and no upstream call** · a streamed
response yields more than one chunk · cache hit produces no second upstream call.
**Satisfies:** FR-200, FR-202, FR-206, FR-211, FR-214, NFR-013. **Exit tests:** ET-17, ET-18.
**Watch:** the app must still boot with `SUNIL_VOICE_ENABLED=false` and **no** OpenAI key — voice
unavailable is not a boot failure (T25's pattern).

---

## 4. Backend integrations lane (BE-2)

### T28 — `config/speech.yaml` and its registry

**Deps:** T27. **On the critical path.**
**Owns:** `config/speech.yaml`, `apps/api/sunil/core/registry/speech.py`,
`apps/api/sunil/core/registry/loader.py`.

**Build:** a sixth-and-seventh registry file following `model_catalogue.py`'s shape exactly:
`version`, `pricing_version`, `capabilities: {transcription, synthesis}` → `{provider, model,
timeout_s, language | voice | instructions, price…}`. Strings → typed values at load; an unknown value
refuses to boot (§10.2). **Cross-validate against the speech provider registry**, and validate the
configured `voice` against the SDK's `Voice` Literal — M9§4.5's ⚠️ note: the alias admits bare `str`,
so an unlisted voice type-checks and 400s at runtime instead.
**Prices ship as clearly-marked zeros with the `config/models.yaml` OpenAI comment repeated verbatim in
spirit** — they are not verifiable from any local source, and a guessed price is worse than a zero
(debt D-15). Pin `gpt-4o-mini-transcribe` and `gpt-4o-mini-tts`, both read from the installed SDK's
`AudioModel` / `SpeechModel` Literals.

**Tests** (`tests/unit/registry/test_speech_registry.py`, plus a case in the existing
`test_real_config.py`): loads the real file · unknown capability → named startup error · unknown
provider → named startup error · a voice outside the SDK Literal → named startup error · a model
outside the SDK Literal → named startup error.
**Satisfies:** FR-209 (pricing half), ADR-016.

### T29 — The `SpeechProvider` protocol and the OpenAI speech adapter

**Deps:** T27, T28. **On the critical path.**
**Owns:** `apps/api/sunil/speech/{__init__.py,base.py,openai_speech.py,registry.py}`.

**Build:**
* `base.py`: `SpeechProvider` Protocol (`name`, `async transcribe(...)`,
  `async synthesize(...) -> AsyncIterator[bytes]`), the request/result dataclasses, and
  `SpeechError`/`SpeechTransientError`/`SpeechPermanentError`. **No vendor import.**
* `openai_speech.py` — **the only module here permitted to `import openai`**:
  * `AsyncOpenAI(api_key=…, base_url=settings.openai_base_url, max_retries=0, timeout=…)`,
    `base_url` **explicit** (ADR-017 — a hard-coded canonical literal would outrank the test seam,
    which is precisely the defect that discipline caught in M1).
  * `transcriptions.create(file=(filename, data, content_type), model=…, response_format="json",
    language=…, temperature=0)`. **The filename is derived from the allow-listed content type**, never
    from the client. **`prompt=` is never passed** (T-38).
  * `speech.with_streaming_response.create(...)` used as an async context manager, forwarding
    `iter_bytes()`. **Not** `await create(...)`, whose `iter_bytes()` is synchronous over an already
    buffered body and would look like streaming while streaming nothing.
  * Error classification **by `status_code`** (A-16), never by class name.
* `registry.py`: `build_speech_registry(settings, speech_registry)` — a vendor with no key is simply
  not registered — and `validate_speech_capabilities(...)`, which raises
  `RegistryCrossValidationError` naming **every** problem, the capability, the vendor and the env var
  that would fix it (T25's message shape).

**Tests** (`tests/unit/speech/test_openai_speech_adapter.py`, `tests/unit/speech/test_speech_registry_build.py`),
all against a **loopback HTTP double** driven by `OPENAI_BASE_URL` (ADR-017's transport seam — a
protocol fake would only assert the fake): the adapter sends the model, format and language it was
configured with · a 429 → `SpeechTransientError`, a 400 → `SpeechPermanentError`, an unnamed 503 →
transient · `base_url` is honoured (assert the double was hit, not `api.openai.com`) · synthesis yields
multiple chunks · **`prompt` never appears in any outbound request body** · no key → not registered ·
a reachable capability with no key → named boot failure.
**Satisfies:** FR-202, FR-206, NFR-013. **Exit tests:** ET-18.
**Watch:** `sunil/speech/` and `sunil/providers/` are the only packages that may import a vendor SDK.
T35 tests it; CI (T21) runs that test on every merge.

---

## 5. Frontend lane (FE)

The frontend still has **no test runner** (M1 debt, deferred to M11). Both tasks below ship verified by
review plus T36's browser-level exit tests. That is weaker than a unit test and is recorded as weaker;
neither task may add a test library on its own authority.

### T33 — Push-to-talk capture, the mic control, and the earcon

**Deps:** T27 only (it needs the frozen `/voice/capabilities` envelope, not its implementation).
**Slack: this can run from day one.**
**Owns:** `apps/web/src/lib/useVoiceCapture.ts`, `apps/web/src/lib/earcon.ts`,
`apps/web/src/components/chat/MicButton.tsx`.

**Build:** the state machine `idle → requesting-permission → recording → stopping → uploading →
transcribed | error`, with `getUserMedia` constraints, `isTypeSupported` container selection in the
M9§4.1 order, `MediaRecorder` at 24 kbps with a 250 ms timeslice, `setPointerCapture`, slide-away-to-
cancel, the `MIN_MS` silent discard, the `MAX_MS` hard stop, and the keyboard equivalent
(`event.repeat` guarded). `earcon.ts` is a ~40 ms `AudioContext` oscillator blip — **no network, no
vendor, no dependency**, and it must work when everything else has failed. Named error states for
permission denied, no device, and unsupported recorder.
`MicButton` follows `Composer`'s existing conventions: a real `<button>`, ≥44 px hit target,
`aria-pressed`, an `aria-live` announcement on state change, and a static (non-pulsing) treatment under
`prefers-reduced-motion`.
**Satisfies:** FR-200, FR-201, FR-212 (client half). **Verified by:** review + ET-13.

### T34 — The voice API client, playback, and wiring

**Deps:** T31 (envelopes), T32 (endpoints), T33. **On the critical path.**
**Owns:** `apps/web/src/lib/voice.ts`, `apps/web/src/components/chat/VoicePlayback.tsx`,
`apps/web/src/lib/useTurn.ts`, `apps/web/src/lib/copy.ts`,
`apps/web/src/components/chat/{index.ts,types.ts}`, `apps/web/src/app/(chat)/page.tsx`.

**Build:**
* `voice.ts`: `getVoiceCapabilities()` (never throws, returns `{enabled:false}` on any failure — the
  `getProjects()` pattern), `transcribe(blob, requestId, durationMs)`, and `speakUrl(messageId)`.
* **The `request_id` is minted once per voice turn and used for all three calls.** Today `useTurn`
  mints it inside `sendTurn`; it gains an optional `requestId` argument so the capture flow can supply
  the one it already used for transcription. That is the *only* change to `useTurn`'s logic — the
  timer, phase, abort and token machinery is untouched, and this task must not refactor it.
* `VoicePlayback`: `<audio crossOrigin="use-credentials" src={speakUrl(id)} autoPlay>` with stop and
  replay controls, and a muted-playback state on error that **never** disturbs the message text
  (FR-207). Playback is attached to the assistant message, not to the turn.
* `TraceDisclosure` gains one line sourced from the response, rendered below the twelve stages and
  visually distinct from them — it is not a stage (ADR-023).
* All new copy lands in `copy.ts` (§11.2).
**Satisfies:** FR-202, FR-205, FR-206, FR-207, FR-210, FR-211, FR-213, FR-214. **Verified by:** review
+ ET-13, ET-17.

---

## 6. Security and QA lanes

### T35 — Import boundaries, egress, and the capture claim (SEC)

**Deps:** T29, T32.
**Owns:** `apps/api/tests/security/test_import_boundaries.py`,
`apps/api/tests/security/test_voice_egress.py`, `apps/api/tests/security/test_voice_capture.py`.

**Build:**
* Amend `test_only_providers_may_import_a_vendor_sdk` to
  `allowed_dirs=("providers/", "speech/")`, **and update the parametrised
  `test_dc10_rules_are_all_covered` list in the same change** — that test exists so a boundary cannot be
  quietly dropped, and it must move deliberately.
* **New:** only `sunil/api/routes/voice.py` may import `sunil.speech.*`. `core/`, `agents/` and
  `tools/` cannot reach speech at all. This is R§6's sentence turned into a test.
* **New:** no module under `sunil/speech/` passes `prompt=` to a transcription call (AST walk for the
  keyword, not a substring grep) — T-38.
* Egress: a non-canonical, non-loopback `OPENAI_BASE_URL` refuses to boot (ADR-017, unchanged);
  loopback + interlock unset → every voice endpoint 503 and **the double receives nothing**; loopback +
  interlock set → allowed.
* Capture: a complete voice turn under defaults leaves `speech_calls.transcript IS NULL`,
  `audio_path IS NULL`, and **an empty `var/voice/` tree**.
**Satisfies:** NFR-013, NFR-052, NFR-002. **Exit tests:** ET-15, ET-18.

### T36 — Exit tests ET-13 … ET-18 and the speech double (QA)

**Deps:** T32, T34.
**Owns:** `apps/api/tests/exit/_speech_double.py`, `apps/api/tests/exit/test_et13_voice_trace_equivalence.py`,
`test_et14_speech_calls_recorded.py`, `test_et15_no_audio_persisted.py`,
`test_et16_voice_provenance_required.py`, `test_et17_speak_ownership.py`,
`test_et18_voice_egress_interlock.py`.

**Build:** `_speech_double.py` is a loopback HTTP server scripting `/audio/transcriptions` and
`/audio/speech`, driven by `OPENAI_BASE_URL` exactly as `_mock_upstreams.py` already does for the other
two upstreams — the same seam, so the **real adapter code** is what runs. It must be able to script: a
normal transcript, an empty transcript, a 429-then-success, a permanent 400, and a chunked audio body.
Each exit test is written **red first**, per M9§14.3's statements verbatim.
ET-13 is the load-bearing one: it runs the same request twice, once typed and once spoken, and asserts
the two twelve-stage traces are identical in stage set and order, and that the spoken turn has exactly
twelve `audit_events` rows — the assertion that would catch anyone "helpfully" adding a stage.
**Satisfies:** the M9 exit criteria.

### T37 — Latency measurement, and replacing the estimates (QA/OPS)

**Deps:** T34. **Requires the owner's real key** — marked `@pytest.mark.live`, deselected in CI via
`-m "not live"` (`pyproject.toml`'s existing marker; there is no `tests/live/` directory in this repo —
live tests sit beside their peers and are selected by marker, which is the convention
`tests/security/test_live_credential_scope.py` already follows).
**Owns:** `apps/api/tests/integration/test_voice_latency_live.py`, `docs/worklog/2026-08-2x-m9-latency.md`.

**Build:** 10 real voice turns, timing each leg separately (capture flush, upload, STT, turn,
TTS-to-first-byte, TTS-to-last-byte, playback start). Report **median and maximum per leg**, never a
single number — §5.2's rule ("five timed runs measure a median and a max, not a 95th percentile").
Then **edit `ARCHITECTURE_M9_VOICE.md` §9.1's table in place**, replacing every ESTIMATE with an
observed value and its date, and close debt D-16. Also answer the one open question in that section:
whether `stream_format="audio"` actually yields early bytes, or whether leg 7 collapses into 7b.
**Satisfies:** NFR-062.

### T38 — OPTIONAL: the spoken acknowledgement (the descope lever)

**Deps:** T30, T32. **Drop this first if M9 comes under schedule pressure** — the earcon plus the
on-screen transcript already carry the message (M9§9.2d).
**Owns:** `apps/api/sunil/speech/ack.py`, `apps/web/src/lib/spokenAck.ts`.
**Build:** `GET /api/v1/voice/ack` serving a once-synthesised `"Okay."` from the same bounded RAM
cache, warmed lazily and asynchronously on the first `/voice/capabilities` call; if it is not warm when
needed the client simply skips it — no blocking, no failure mode. Gated on `SUNIL_VOICE_ACK="spoken"`.

---

## 7. Exit-test coverage map

| Exit test | Proved by |
|---|---|
| ET-13 — twelve stages, spoken == typed | T31, T32, T34, T36 |
| ET-14 — two `speech_calls` rows, costed | T27, T30, T36 |
| ET-15 — no audio persisted | T27, T30, T35, T36 |
| ET-16 — voice provenance required | T31, T36 |
| ET-17 — speak ownership enforced | T32, T36 |
| ET-18 — egress interlock holds | T27, T29, T32, T35, T36 |
| NFR-062 — latency, measured not modelled | T37 |

Every M9 FR in `ARCHITECTURE_M9_VOICE.md` §14.1 is claimed by at least one task above; FR-213/FR-214
(COULD) are T34 and T32 respectively and are the two safe descopes after T38.

---

## 8. Before build starts — the owner's decisions

These are not build decisions and no engineer should take them. Listed in
`ARCHITECTURE_M9_VOICE.md`'s report and repeated here so the lane leads can see the gate:

1. **Auto-send, or transcript-review-then-send?** The plan defaults to auto-send with the reasoning and
   the expiry condition in M9§5.3.
2. **`local_file` audio retention: implement it, or leave `discard` as the only mode?** M9§7.3 states
   exactly what turning it on means.
3. **Is the OpenAI voice choice his?** `config/speech.yaml` pins `alloy`; it is a one-line config
   change and he may have a preference.
4. **Does M9 wait for M2?** M9§9.3 is explicit that the conversational feel needs streaming. Shipping
   M9 first delivers a working voice interface with a ~7 s answer; shipping M2 first and then M9
   delivers ~3 s but later.
