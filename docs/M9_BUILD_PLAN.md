# M9 — Voice: build plan (T27 … T39)

> **⚠️ M9 IS NO LONGER THE NEXT BUILD.** The owner reversed the order on 2026-08-19: **M2 (streaming)
> ships first** — see [`docs/M2_BUILD_PLAN.md`](M2_BUILD_PLAN.md). This plan is amended and correct,
> and it is executed *after* M2 lands. Task numbers T27…T39 are M9's and do not collide with M2's,
> which uses T40…T51.

**Author:** Solution Architect, Minions Team 18 · **Date:** 2026-08-19 · **Amended:** 2026-08-19 (M9-A2 … M9-A5)
**Architecture:** [`docs/ARCHITECTURE_M9_VOICE.md`](ARCHITECTURE_M9_VOICE.md) — `M9§n` below, and read
its **amendment log** first.
**Decisions:** ADR-019 … ADR-026, including ADR-019 Am. 1, ADR-021 Am. 1, ADR-022 Am. 1, ADR-024 Am. 1. **Requirements of record:** `ARCHITECTURE_M9_VOICE.md` §14 until the
BA merges it into `REQUIREMENTS_V1.md` §4.11.
**Git workflow (Delivery Manager's document, in force):** [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md) —
one branch per task, `task/T<n>-<slug>`, cut from current `main`, never committed to `main`.

---

## 0a. What the owner's 2026-08-19 decisions changed in this plan

| Amendment | Effect here |
|---|---|
| **M9-A2** — `local_file` withdrawn, `SUNIL_VOICE_AUDIO_RETENTION` deleted | **T27** loses a setting, a column (`audio_path`) and a warning paragraph. **T30** loses a filesystem branch entirely — it does not gain a no-op one. **T35** gains an easier assertion: `var/` must be byte-identical across a voice turn, with no configuration under which that could differ |
| **M9-A3** — synthesis moves to ElevenLabs | **T29 splits into T29a (OpenAI STT) and T29b (ElevenLabs TTS)** — two adapters, one protocol, and they can be built in parallel. **T28** carries two vendors and the `billing_unit`/`unit_price` scheme. **T27** adds `ELEVENLABS_API_KEY` + `ELEVENLABS_BASE_URL` and the `billing_unit`/`billed_units` columns. Still **zero new dependencies** — `httpx` is already pinned |
| **M9-A4** — the interlock is narrowed to the STT leg and renamed | **T27** renames the setting; **T32** applies it to `/voice/transcribe` only; **T35**'s egress test asserts the **asymmetry** deliberately, not by omission |
| **M9-A5** — M2 ships first, so pipelining is in M9 scope | **T30** gains `synthesize_stream()` and a sentence-boundary chunker; **T32**'s speak endpoint forwards N syntheses rather than one; **T38 is replaced** by the plan-fact utterance (ADR-024 Am. 1). The client side is unchanged — that half of the seam held |

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
| `apps/api/sunil/speech/{__init__,base,openai_speech,registry}.py` | **T29a** |
| `apps/api/sunil/speech/elevenlabs_speech.py` | **T29b** |
| `apps/api/sunil/speech/{service.py,chunker.py}` | **T30** |
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
| `apps/api/sunil/speech/plan_utterance.py`, `apps/web/src/lib/planUtterance.ts` | **T39** (optional — replaces T38) |
| Unit tests under `tests/unit/**` | the task that owns the module under test; basenames listed per task |

**Documents nobody on this milestone edits:** `docs/STATUS.md`, `docs/GIT_WORKFLOW.md` (Delivery
Manager's), `docs/ARCHITECTURE_V1.md` §14.3 (no dependency changes — M9§13).

---

## 2. Dependency graph and the critical path

```
                     ┌─► T29a ─┐
T27 ──► T28 ─────────┤         ├─► T30 ──► T31 ──► T32 ──► T34 ──► T36 ──► T37
      │              └─► T29b ─┘                     ▲
      └────────────────────► T33 ────────────────────┘

T29b needs only T29a's `base.py`, not the whole task — the two adapters build in parallel.
T35 depends on T29a + T29b + T32 (it tests their boundaries).
T39 depends on T30 + T32, and is optional.
```

**Critical path: T27 → T28 → T29a → T30 → T31 → T32 → T34 → T36.** The vendor split (M9-A3) did **not**
lengthen it: T29b runs beside T29a, and both finish before T30 needs them. T33 (the capture hook) has real
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
  peer table. **Includes `billing_unit` (`audio_second|character`, CHECK-constrained) and
  `billed_units` `Numeric(12,3)`** (M9-A3) — two units across three vendor/leg combinations, so cost is
  `billed_units × unit_price` with no vendor branch in code. **No `audio_path` column** (M9-A2).
* `Message.input_modality`: `String(10)` NOT NULL default `'text'`, CHECK `IN ('text','voice')`.
* `db/capture.py`: `resolve_capture()` handles `SPEECH_CALL`; the writer nulls `transcript` under
  `none`/`metadata_only` on the **same writer path** the other kinds already use — no second mechanism.
* Migration `0002_voice`: create table, add column with a server default, back-fill `'text'`, add the
  CHECK. Downgrade drops both. Obeys §7.2 portability (no dialect-specific types).
* `main.py`: `EXPECTED_ALEMBIC_HEAD = "0002"`. **Nothing else in this file** — the lifespan wiring is
  T32's, and T32 starts after this merges.
* `settings.py`: the six `SUNIL_VOICE_*` fields of M9§8.2 with their defaults, **plus
  `elevenlabs_api_key: SecretStr | None` and `elevenlabs_base_url`** — the latter added to
  `_CANONICAL_BASE_URLS` as `https://api.elevenlabs.io` (**no `/v1` suffix**, unlike OpenAI's) and
  covered by the existing `_validate_base_url`, which now guards four upstreams with one function.
  Register the new key with `redaction.register()` **and** add an `sk_[A-Za-z0-9]{20,}` entry to §8.3's
  pattern list — ElevenLabs' documented prefix is one character from OpenAI's.
  Then a model-level validator implementing the **STT interlock** (M9§8.1 item 2, M9-A4): if
  `openai_base_url` is loopback and `sunil_voice_allow_loopback_stt` is false, **transcription** is
  unavailable — expose it as a computed `stt_available: bool`, do **not** raise. Raising would stop QA
  booting an app with a transcription double, and ADR-017's boot-refusal already covers the case that
  must be fatal. **There is no equivalent flag for synthesis, and that is deliberate** (M9-A4) — do not
  add one "for symmetry".
* **`SUNIL_VOICE_AUDIO_RETENTION` does not exist** (M9-A2). If you find yourself adding it, re-read
  ADR-021 Amendment 1.
* `config/capture.yaml`: a `speech_call` block, `capture_policy: metadata_only`, `sensitivity:
  internal`, `retention_class: standard`, with the M9§7.2 reasoning as a comment.
* `.env.example`: the six `SUNIL_VOICE_*` variables plus `ELEVENLABS_API_KEY` and
  `ELEVENLABS_BASE_URL`, placeholders only. **No retention variable and no warning paragraph** —
  M9-A2 removed the mode, so there is nothing to warn about.

**Tests** (`tests/unit/test_voice_settings.py`, `tests/unit/test_speech_call_model.py`,
`tests/unit/test_migration_0002.py`, additions to `tests/unit/test_db_capture.py`):
`speech_call` resolves to `metadata_only` from the real config · a `metadata_only` decision writes
`transcript IS NULL` and `transcript_chars` non-null · `training_eligible` stays derived · the
`direction` CHECK rejects a third value · `billing_unit` CHECK rejects a third value ·
`input_modality` rejects a third value and defaults to `'text'` · `0002` upgrades and downgrades
cleanly on SQLite · **canonical `openai_base_url` → `stt_available` true; loopback + interlock false →
false; loopback + interlock true → true; a non-canonical non-loopback URL still refuses to construct
`Settings`** (ADR-017 unchanged) · **a loopback `elevenlabs_base_url` does NOT affect `stt_available`
and needs no flag** — assert it explicitly, so a later "tidy-up" that adds symmetry fails a test
(M9-A4) · `ELEVENLABS_API_KEY`'s value never appears in a log line (ET-10's mechanism, new secret).
**Satisfies:** FR-208, FR-209, NFR-052 (schema half). **Exit tests:** ET-14, ET-15, ET-18 (foundations).

### T30 — `SpeechService`: retry, deadline, persistence, cost, capture

**Deps:** T27, T29a, T29b. **On the critical path.**
**Owns:** `apps/api/sunil/speech/service.py`, `apps/api/sunil/speech/chunker.py`.

**Build:** `SpeechService.transcribe(...)`, `.synthesize(...)` and — new under M9-A5 —
`.synthesize_stream(...)`, each taking already-validated inputs and a `sessionmaker`, and each:
* resolving the capability from the speech registry (T28) — never naming a vendor;
* running **one retry on transient only** (A-16's rule: no-status connection/timeout, 408, 429, any
  5xx are transient; **everything else, including any exception class this plan does not name, is
  permanent**);
* writing **one `speech_calls` row per attempt**, including the failed one, via `resolve_capture()`;
* computing cost as **`billed_units × unit_price`** from `config/speech.yaml`, stamping
  `pricing_version` and writing `billing_unit`/`billed_units`. **There is no `if direction == "stt"`
  branch** — the unit is named data, not inferred from the leg (M9-A3, ADR-019 Am. 1). A code review
  that finds such a branch should reject the task;
* **no filesystem call exists anywhere on this path** (M9-A2). Not a guarded one, not a no-op wrapper —
  `SpeechService` does not import `pathlib` or `open`;
* returning a streaming async iterator for synthesis, never a buffered `bytes`.

**`chunker.py` (new, M9-A5)** — `sentence_chunks(tokens: AsyncIterator[str]) -> AsyncIterator[str]`:
emits on `.`, `!` or `?` followed by whitespace or end-of-stream, with a **minimum chunk of 24
characters** so `"e.g."` or `"v2.5"` does not trigger a four-character synthesis, and a **maximum of
`SUNIL_VOICE_MAX_SPEAK_CHARS`** so a model that never punctuates still flushes. It is a pure async
generator over strings with no vendor, no HTTP and no database — which is what makes it the one piece
of M9 that is trivially unit-testable in isolation, and it should have the densest tests in the
milestone.

**Tests** (`tests/unit/speech/test_speech_service.py`, `tests/unit/speech/test_sentence_chunker.py`):
two rows on one transient retry, one on success, one on a permanent failure with `status="error"` and
an `error_kind` · cost arithmetic for **both** billing units against a pinned price table · a synthesis
row records `billing_unit="character"` and a transcription row `audio_second` · `metadata_only` nulls
`transcript` while keeping `transcript_chars` · **`discard` is unconditional: run a full transcribe
against a `tmp_path` tree and assert it is byte-identical afterwards, and assert `service.py`'s source
imports neither `open` nor `pathlib`** · a synthesis longer than `max_speak_chars` truncates at a
sentence boundary and sets `truncated=True` · the chunker emits on `. ! ?`, does **not** emit inside
`"e.g."`, `"v2.5"` or `"Dr. Smith"`, flushes an unpunctuated 3,000-character stream, and emits the tail
when the stream ends mid-sentence.
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

**Deps:** T27, T28, T29a, T29b, T30, T31 — **and T27 must be merged before this branch is cut** (§0 rule 1,
`main.py`). **On the critical path.**
**Owns:** `apps/api/sunil/api/routes/voice.py`, `apps/api/sunil/api/routes/__init__.py`,
`apps/api/sunil/main.py` (second owner, sequentially).

**Build:** the four endpoints of M9§6, with the guard order of M9§4.2 **exactly as listed** —
session → client header → enabled (404) → **STT interlock (503, `/voice/transcribe` only — M9-A4)** →
content type (415) → length (413) → streamed read with a running byte cap. **`/voice/speak` has no
interlock check**; adding one there is a defect, not a hardening (ADR-022 Amendment 1). Plus:
* `GET /voice/speak/{message_id}`: **no client-header requirement** (an `<audio>` element cannot send
  one — M9§4.5) and therefore an ownership check that is not optional: assistant role, conversation
  owned by the session user, else **404**. `StreamingResponse(media_type="audio/mpeg")` forwarding
  chunks. **Under M9-A5 the upstream is N syntheses concatenated, not one** — the response is a single
  chunked `audio/mpeg` body either way, which is the half of the original seam that held: the client is
  unchanged. Each sentence-level synthesis writes its own `speech_calls` row, so N syntheses are N rows
  and the cost arithmetic stays true with no schema change.
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

**Build:** a seventh registry file following `model_catalogue.py`'s shape exactly: `version`,
`pricing_version`, `capabilities: {transcription, synthesis}` → `{provider, model, timeout_s,
billing_unit, unit_price, …}`. Strings → typed values at load; an unknown value refuses to boot
(§10.2). **Cross-validate against the speech provider registry.**

**Two vendors (M9-A3):**

```yaml
capabilities:
  transcription:
    provider: openai
    model: gpt-4o-mini-transcribe      # from the installed SDK's AudioModel Literal
    language: en
    timeout_s: 20
    billing_unit: audio_second
    unit_price: "0"                    # PLACEHOLDER — see below
  synthesis:
    provider: elevenlabs
    model: eleven_flash_v2_5           # ~75ms, 40k char cap, 0.5 credits/char (vendor's figures)
    voice_id: REPLACE_ME               # the owner's choice — never a value read from a blog post
    voice_settings: {stability: 0.5, similarity_boost: 0.75}
    output_format: mp3_44100_128
    timeout_s: 20
    billing_unit: character
    unit_price: "0"                    # PLACEHOLDER
  # synthesis_openai: kept commented, carrying the exact shape `synthesis` had before ADR-026,
  # so reverting the vendor is a config edit and never a code change (T24's pattern).
```

**`billing_unit` + `unit_price` are the mechanism that keeps vendor arithmetic out of code** (ADR-019
Amendment 1): `SpeechService` computes `billed_units × unit_price` and never asks which leg it is on.

**Prices ship as clearly-marked zeros** with `config/models.yaml`'s OpenAI comment repeated in spirit —
not verifiable from any local source, and a guessed price is worse than a zero (debt D-15).
**`voice_id` ships as `REPLACE_ME`** and the owner supplies it (§9): pinning a "premade" voice id read
from a third-party page is exactly the class of unverified constant this project writes zeros for.
**Do not validate `voice_id` by calling the vendor at startup** — that would make booting SUNIL depend
on a vendor being reachable, against ADR-016's restart model. Validate it is present and non-empty; a
422 at first synthesis maps to `error_kind="unknown_voice"` (T29b).

**Tests** (`tests/unit/registry/test_speech_registry.py`, plus a case in the existing
`test_real_config.py`): loads the real file · unknown capability → named startup error · unknown
provider → named startup error · a model outside its vendor's known set → named startup error · an
unknown `billing_unit` → named startup error · **an empty `voice_id` → named startup error, and the
message says which config key and which owner action fixes it** · the commented `synthesis_openai`
block is not loaded and does not affect cross-validation.
**Satisfies:** FR-209 (pricing half), ADR-016, ADR-026.

### T29a — The `SpeechProvider` protocol and the OpenAI transcription adapter

**Deps:** T27, T28. **On the critical path.** Splits from the original T29 under M9-A3.
**Owns:** `apps/api/sunil/speech/{__init__.py,base.py,openai_speech.py,registry.py}`.

**Build:**
* `base.py`: `SpeechProvider` Protocol (`name`, `async transcribe(...)`,
  `async synthesize(...) -> AsyncIterator[bytes]`, `async synthesize_stream(...) -> AsyncIterator[bytes]`),
  the request/result dataclasses, and `SpeechError`/`SpeechTransientError`/`SpeechPermanentError`.
  **No vendor import.** A provider that cannot do a leg raises `SpeechCapabilityUnsupported` — OpenAI's
  adapter implements all three; a future transcription-only vendor would not.
* `openai_speech.py` — one of the two modules permitted a vendor import:
  * `AsyncOpenAI(api_key=…, base_url=settings.openai_base_url, max_retries=0, timeout=…)`,
    `base_url` **explicit** (ADR-017 — a hard-coded canonical literal would outrank the test seam,
    which is precisely the defect that discipline caught in M1).
  * `transcriptions.create(file=(filename, data, content_type), model=…, response_format="json",
    language=…, temperature=0)`. **The filename is derived from the allow-listed content type**, never
    from the client. **`prompt=` is never passed** (T-38).
  * Reads `usage` defensively: `Transcription.usage` is `Optional` and is a **discriminated union** of
    `UsageTokens` and `UsageDuration`. Set `billing_unit="audio_second"` and `billed_units` from
    `usage.duration.seconds` when present, else from the advisory `X-Audio-Duration-Ms` header, else
    write `billed_units=0` and an `error_kind` note — never invent a duration.
  * Keeps its **synthesis** path implemented and tested (`speech.with_streaming_response.create(...)`
    as an async context manager, forwarding `iter_bytes()`; **not** `await create(...)`, whose
    `iter_bytes()` is synchronous over an already-buffered body and would look like streaming while
    streaming nothing; and `AsyncResponseContextManager` has no `__await__`). **It is not wired to a
    capability**, exactly as `general_reasoning_anthropic` is not — so reverting ADR-026 is a config
    edit, never a code change.
  * Error classification **by `status_code`** (A-16), never by class name.
* `registry.py`: `build_speech_registry(settings, speech_registry)` — a vendor with no key is simply
  not registered — and `validate_speech_capabilities(...)`, which raises
  `RegistryCrossValidationError` naming **every** problem, the capability, the vendor and the env var
  that would fix it (T25's message shape).

**Tests** (`tests/unit/speech/test_openai_speech_adapter.py`,
`tests/unit/speech/test_speech_registry_build.py`), all against a **loopback HTTP double** driven by
`OPENAI_BASE_URL` (ADR-017's transport seam — a protocol fake would only assert the fake): the adapter
sends the model, format and language it was configured with · a 429 → `SpeechTransientError`, a 400 →
`SpeechPermanentError`, an unnamed 503 → transient · `base_url` is honoured (assert the double was hit,
not `api.openai.com`) · **`prompt` never appears in any outbound request body** · a `UsageDuration`
response sets `billed_units`; a response with `usage=None` falls back to the header; neither invents a
number · no key → not registered · a reachable capability with no key → named boot failure.
**Satisfies:** FR-202, NFR-013. **Exit tests:** ET-18.
**Watch:** `sunil/speech/` and `sunil/providers/` are the only packages that may import a vendor SDK.
T35 tests it; CI (T21) runs that test on every merge.

### T29b — The ElevenLabs synthesis adapter

**Deps:** T27, T28, and **T29a's `base.py` merged** (it consumes the protocol, it does not define it).
**Parallel with T30 once `base.py` exists.** New under M9-A3.
**Owns:** `apps/api/sunil/speech/elevenlabs_speech.py`.

**Build:** `httpx.AsyncClient` — **no SDK, no new dependency** (`httpx` 0.28.1 is already pinned and
already used in exactly this shape by `tools/github/adapter.py`).

* `POST {elevenlabs_base_url}/v1/text-to-speech/{voice_id}/stream`, `base_url` **explicit** from
  `Settings` (ADR-017), `follow_redirects=False` like the GitHub client — a redirect would bounce the
  key onward.
* Header **`xi-api-key`**, *not* `Authorization: Bearer`. An adapter written by analogy with T29a's
  will 401 on every call; this line is why the plan says it twice.
* Query `output_format=mp3_44100_128` and **`enable_logging=false`** — Zero Retention Mode, requested
  unconditionally and **claimed nowhere** (T-43; it is Enterprise-only).
* **Do not send `optimize_streaming_latency`** — deprecated in the vendor's own documentation.
* Body `{"text", "model_id", "voice_settings", "language_code"}`; `model_id` and voice settings come
  from `config/speech.yaml`, never from a literal.
* Stream with `client.stream("POST", …)` and `aiter_bytes()`. **On a `>=400` status you must
  `await response.aread()` before inspecting the body** — an unread streaming response has no content.
* `billing_unit="character"`, `billed_units=len(text)`.
* `provider_request_id` from `request-id`/`x-request-id` **if present, else `NULL`** — no such header
  is documented (debt D-18). Do not invent one.
* Error classification **by `status_code`** (A-16). A 401 is permanent (bad key); a 422 naming an
  unknown voice maps to `error_kind="unknown_voice"` so a mis-configured `voice_id` is legible.

**Tests** (`tests/unit/speech/test_elevenlabs_adapter.py`), against a **loopback HTTP double** driven
by `ELEVENLABS_BASE_URL`: the outbound request carries `xi-api-key` and **never** an `Authorization`
header · `enable_logging=false` is present on every call · `optimize_streaming_latency` is **absent** ·
the double receives the configured `model_id` and `voice_id` · a chunked body yields more than one
chunk to the caller · a 429 → transient, a 400 → permanent, an unnamed 502 → transient · a 422 →
`error_kind="unknown_voice"` · `billed_units == len(text)` · a redirect is **not** followed · the key's
value never appears in a log line.
**Satisfies:** FR-206, FR-207, NFR-013. **Exit tests:** ET-14.
**Watch:** every fact above came from the vendor's published reference, **not from a live call** (debt
D-18). The first task run with a real key must confirm the auth header, the streaming behaviour and the
response headers, and report any difference as a defect against this plan rather than fixing it
silently.

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

**Deps:** T29a, T29b, T32.
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
* **New:** no module under `sunil/speech/` sends an `Authorization` header to ElevenLabs, and none
  sends `optimize_streaming_latency` — both are AST/keyword walks over `elevenlabs_speech.py`, and both
  encode a fact that was verified once and would otherwise be re-guessed by the next person.
* Egress, **including the asymmetry M9-A4 introduced, asserted rather than left implicit**:
  * a non-canonical, non-loopback `OPENAI_BASE_URL` or `ELEVENLABS_BASE_URL` refuses to boot
    (ADR-017, unchanged, now four upstreams);
  * loopback `OPENAI_BASE_URL` + `SUNIL_VOICE_ALLOW_LOOPBACK_STT` unset → `/voice/transcribe` 503 and
    **the double receives nothing**; set → allowed;
  * **loopback `ELEVENLABS_BASE_URL` with no flag at all → synthesis is allowed.** This test exists so
    that a future "tidy-up" adding a second flag for symmetry fails, and has to come and read ADR-022
    Amendment 1 to find out why the asymmetry is deliberate.
* Capture: a complete voice turn leaves `speech_calls.transcript IS NULL` and **`var/` byte-identical**.
  There is no `audio_path` column and no `var/voice/` tree to check (M9-A2) — assert instead that
  `sunil/speech/service.py` imports neither `open` nor `pathlib`, which is the property that makes
  "discarded" structural rather than behavioural.
**Satisfies:** NFR-013, NFR-052, NFR-002. **Exit tests:** ET-15, ET-18.

### T36 — Exit tests ET-13 … ET-18 and the speech double (QA)

**Deps:** T32, T34.
**Owns:** `apps/api/tests/exit/_speech_double.py`, `apps/api/tests/exit/test_et13_voice_trace_equivalence.py`,
`test_et14_speech_calls_recorded.py`, `test_et15_no_audio_persisted.py`,
`test_et16_voice_provenance_required.py`, `test_et17_speak_ownership.py`,
`test_et18_voice_egress_interlock.py`.

**Build:** `_speech_double.py` is a loopback HTTP server scripting **both vendors** — OpenAI's
`/audio/transcriptions` (driven by `OPENAI_BASE_URL`) and ElevenLabs'
`/v1/text-to-speech/{voice_id}/stream` (driven by `ELEVENLABS_BASE_URL`) — exactly as
`_mock_upstreams.py` already does for the other upstreams, so the **real adapter code** is what runs.
It must be able to script: a normal transcript, an empty transcript, a 429-then-success, a permanent
400, a 422 naming an unknown voice, and a chunked audio body delivered in several parts. It must also
**assert what it received**, so the security tests can check the `xi-api-key` header, the absence of
`Authorization`, and `enable_logging=false`.
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

### T39 — OPTIONAL: the plan-fact utterance (replaces T38 as the descope lever)

**Deps:** T30, T32. **Drop this first if M9 comes under schedule pressure** — the earcon plus the
on-screen transcript already carry the interaction (M9§9.2a).
**Owns:** `apps/api/sunil/speech/plan_utterance.py`, `apps/web/src/lib/planUtterance.ts`.

**Replaces T38's `"Okay."` acknowledgement**, because M9-A5 changed which gap needs filling. With
sentence pipelining, the first spoken word of the answer arrives at ~5.3 s and the transcript at ~1 s;
the gap that remains is **2.5 s → 5.3 s**, and the honest thing to put in it is the fact SUNIL learns at
`plan_created`.

**Build:** when a validated plan resolves a project, synthesise and play
*"Checking {project_display_name}."* — the **same fact** `WorkIndicator` already renders on screen from
`plan_created.detail.project_display_name` (§3.4). Gated on `SUNIL_VOICE_ACK="spoken"`.

**Three rules, and they are what separate this from the thing ADR-024 rejected:**
1. It states a **fact from a validated plan**, never a claim about progress. *"Working out a plan…"*
   stays rejected; *"Checking the workforce repo."* is permitted. If you cannot name the source row for
   what is being said, do not say it.
2. **Never spoken when the plan was rejected** or when `project_display_name` is absent — silence is
   correct, and a generic fallback would reintroduce exactly the progress claim rule 1 forbids.
3. **Cancelled if the answer's first sentence is ready before it finishes**, so SUNIL never talks over
   itself.

**Tests** (`tests/unit/speech/test_plan_utterance.py`): fires once on a resolved plan; **never** fires
on `plan_rejected` or `unknown_project`; never fires when the detail key is absent; is cancelled when
the first answer sentence arrives first.

---

## 7. Exit-test coverage map

| Exit test | Proved by |
|---|---|
| ET-13 — twelve stages, spoken == typed | T31, T32, T34, T36 |
| ET-14 — two `speech_calls` rows, costed, **both billing units** | T27, T29a, T29b, T30, T36 |
| ET-15 — no audio persisted, **unconditionally** | T27, T30, T35, T36 |
| ET-16 — voice provenance required | T31, T36 |
| ET-17 — speak ownership enforced | T32, T36 |
| ET-18 — STT interlock holds, **and synthesis is deliberately not gated** | T27, T29a, T29b, T32, T35, T36 |
| NFR-062 — latency, measured not modelled | T40 (M2, leg 6a), then T37 |

Every M9 FR in `ARCHITECTURE_M9_VOICE.md` §14.1 is claimed by at least one task above; FR-213/FR-214
(COULD) are T34 and T32 respectively and are the two safe descopes after T39.

---

## 8. The owner's four decisions — all taken 2026-08-19

Recorded here as settled, so no lane reopens them:

1. **Auto-send** — confirmed as designed (M9-A1), including that its safety expires at M5 (DC-17).
2. **Retention** — `discard` only. `local_file` is **not built** and `SUNIL_VOICE_AUDIO_RETENTION`
   does not exist (M9-A2, ADR-021 Amendment 1).
3. **Build order** — **M2 ships before M9** (M9-A5). Sentence pipelining is therefore M9 scope, not a
   later retrofit. ⚠️ The owner took this decision expecting "~3 s"; the corrected figure is **~5.3 s**
   (M9§9.1, ADR-024 Amendment 1), and he should see it before M9 starts.
4. **Vendors** — synthesis on **ElevenLabs**, transcription stays on **OpenAI** (M9-A3, ADR-026).

## 9. What the owner must create before T29b can be built or tested for real

`ELEVENLABS_API_KEY` is the only new secret. It is needed by **T29b** to verify against a live
endpoint and by **T37** to measure; every earlier task builds and tests against a loopback double, so
**nothing before T29b is blocked by its absence.**

| # | What he creates | Where it goes | Note |
|---|---|---|---|
| 1 | An **ElevenLabs account** | — | — |
| 2 | A **plan decision**. Their free tier is credit-limited and carries **no commercial-use rights and an attribution requirement**; the entry paid tier does. SUNIL answers questions about Codely work, so this is a business-use call, not a technical one | — | **ESTIMATE:** plan allowances quoted by secondary sources disagree; he should read the current pricing page rather than trust a number from here |
| 3 | An **API key** from the ElevenLabs dashboard | `.env` → `ELEVENLABS_API_KEY` | Sent as `xi-api-key`. Never in code, never in a prompt, registered with `redaction.register()` on boot |
| 4 | A **chosen voice**, and its `voice_id` | `config/speech.yaml` → `capabilities.synthesis.voice_id` | Ships as `REPLACE_ME`; the registry refuses to boot on the placeholder rather than 422-ing at first use |
| 5 | **Awareness, not an action:** ElevenLabs' `enable_logging` defaults to `true`, so **the vendor retains SUNIL's answer text**. SUNIL sends `enable_logging=false` on every call, but Zero Retention Mode *"may only be used by enterprise customers"* — so on any normal plan it will not apply | — | Threat **T-43**. Recorded so the retention posture is a decision he made, not one he discovers |

Nothing else changes for him: `OPENAI_API_KEY` and `OPENAI_BASE_URL` are unchanged, and no other
credential is added.
