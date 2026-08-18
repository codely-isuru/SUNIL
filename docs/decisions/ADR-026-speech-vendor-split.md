# ADR-026 — Transcription on OpenAI, synthesis on ElevenLabs: two speech vendors, one boundary

**Status:** Proposed (Architect, M9 amendment) · **Date:** 2026-08-19 · **Decider:** owner's decision
2026-08-19, designed by the Solution Architect
**Context refs:** `ROADMAP.md` §6; ADR-003, ADR-019, ADR-021, ADR-022, ADR-024;
`ARCHITECTURE_M9_VOICE.md` §2, §4.5, §8, §9, §11; `ARCHITECTURE_V1.md` §4.6, §14.3.

## Context

M9 was designed against a single speech vendor: OpenAI for both transcription and synthesis, because
the owner already held that key and it was funded. **The owner has now decided that synthesis moves to
ElevenLabs and transcription stays on OpenAI.**

`ROADMAP.md` §6 anticipated exactly this: *"the reasoning model does not need to be the same service
used for STT or TTS."* ADR-019 already put the two speech capabilities behind a capability-keyed
registry precisely so a vendor could move without touching an agent. **This ADR is the first real test
of that claim, and it is the reason the claim was worth making.**

The owner does not yet hold an ElevenLabs key. The API surface below was verified against ElevenLabs'
own published API reference on 2026-08-19; anything that could not be verified without a key is marked
**ESTIMATE**, following the discipline `config/models.yaml` already applies to OpenAI's pricing.

## Decision

**Two speech vendors, behind the one `SpeechProvider` protocol, selected by the two capabilities that
already exist.**

| Capability | Provider | Model | Endpoint |
|---|---|---|---|
| `transcription` | `openai` | `gpt-4o-mini-transcribe` | `POST https://api.openai.com/v1/audio/transcriptions` |
| `synthesis` | `elevenlabs` | `eleven_flash_v2_5` | `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream` |

`config/speech.yaml` already maps capability → `{provider, model, …}`. **The change is values in that
file plus one new adapter module.** Nothing in `core/`, `agents/`, `tools/` or `api/routes/voice.py`
names a vendor, then or now.

### 1. The ElevenLabs surface, verified 2026-08-19

| Fact | Value |
|---|---|
| Method + path | `POST /v1/text-to-speech/{voice_id}/stream` |
| Auth header | **`xi-api-key: <key>`** — *not* `Authorization: Bearer` |
| Request content type | `application/json` |
| Body | `{ "text": …, "model_id": …, "voice_settings": {…}, "language_code": … }` |
| Query params | `output_format` (default `mp3_44100_128`), `enable_logging` (default **`true`**), `optimize_streaming_latency` (**deprecated — do not use**) |
| Response | streaming audio; `mp3_44100_128` is MP3, which `<audio>` plays progressively |
| `eleven_flash_v2_5` | ~75 ms model latency, **40,000** character maximum, **0.5 credits per character** |
| `eleven_multilingual_v2` | 10,000 character maximum |
| Billing unit | **characters** (as credits, with a per-model multiplier) |
| Per-request id response header | **not documented** — the adapter reads `request-id`/`x-request-id` if present and stores `NULL` otherwise |

Sources: ElevenLabs API reference (`/docs/api-reference/text-to-speech/stream` and `/convert`), models
page, and pricing page, all read 2026-08-19.

**No SDK, and therefore no new dependency.** ElevenLabs is a plain JSON-over-HTTPS API, and `httpx`
0.28.1 is already pinned in `ARCHITECTURE_V1.md` §14.3 and already used in exactly this shape by
`tools/github/adapter.py`. The adapter is `httpx.AsyncClient(...).stream("POST", …)` forwarding
chunks. **M9 still adds zero dependencies.**

**ESTIMATE, and stated as such:** the ~75 ms figure is ElevenLabs' own published model-latency number,
not an end-to-end time observed from this machine, and secondary sources disagree with each other about
plan allowances. `config/speech.yaml` ships prices as clearly-marked zeros (debt D-15, unchanged) and
T37 measures the real latency.

### 2. Two vendors, two billing units — and the schema change that makes cost honest

This is the concrete thing the second vendor forces, and it is a **simplification**, not a
complication:

| Leg | Vendor | Unit billed |
|---|---|---|
| `transcription` | OpenAI | **audio seconds** (`usage.duration.seconds`) |
| `synthesis` | ElevenLabs | **characters** |
| *(synthesis, had it stayed on OpenAI)* | *OpenAI* | *characters* |

Three vendor/leg combinations; **two units**. `speech_calls` gains two columns — `billing_unit`
(`audio_second | character`) and `billed_units` — and `config/speech.yaml` names the unit and the price
per unit alongside the model. Cost becomes `billed_units × unit_price`, computed by one line in
`SpeechService`, with **no vendor-specific arithmetic anywhere in code**.

Before this ADR, `SpeechService` would have carried an `if direction == "stt"` branch choosing which
column to multiply. The second vendor removed the branch. That is the tell that the abstraction was
drawn in the right place.

### 3. Zero Retention Mode — send it, do not claim it

ElevenLabs' `enable_logging` defaults to **`true`**, which means the request — **the text of SUNIL's
answer**, which may carry private-repository content projected into it — is retained by the vendor.
Setting `enable_logging=false` enables Zero Retention Mode, and their documentation states plainly that
it **"may only be used by enterprise customers."**

**Decision: SUNIL sends `enable_logging=false` on every synthesis request, unconditionally.** It costs
nothing, it is honoured if the account is eligible, and it is the correct request to make. **It is not
counted as a control anywhere in this architecture**, because on a non-Enterprise plan it will not
apply — threat **T-43**, and the owner should know it before he signs up.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Both legs on ElevenLabs** — they do have an STT product (Scribe), so this was a real option, and *the owner considered it and declined* | One vendor, one key, one base URL, one guard — genuinely simpler, and I would have argued for it on those grounds alone. It fails on the disclosure argument: it moves the **microphone audio** to a vendor whose retention default is `enable_logging=true` and whose Zero Retention Mode is Enterprise-only. Under ADR-021 that audio is the most sensitive thing SUNIL handles and is *unredactable*. Sending it to a retaining-by-default vendor, when the incumbent already holds the key and is funded, trades a real increase in disclosure for a configuration convenience. **The split keeps the worse disclosure with the known vendor.** |
| **Both legs on OpenAI** (the original M9 design) | Synthesis quality is the owner's judgement and not mine to relitigate. Worth recording that this ADR is nearly free to reverse: `config/speech.yaml` keeps the OpenAI `synthesis` block commented in place, exactly as `config/models.yaml` keeps `general_reasoning_anthropic` (T24's pattern), so reverting is a config edit and never a code change. |
| **One `SpeechProvider` implementation with an `if vendor ==` branch** | The exact shape ADR-003 exists to prevent, one layer down. Two adapters, one protocol, one registry line each. |
| **Put the vendor choice in `Settings` rather than `config/speech.yaml`** | Contradicts ADR-016 ("config is not code") and FR-084. A vendor swap should be a reviewed config edit visible in `git diff`, not an environment variable with no history. |
| **Add the official `elevenlabs` Python SDK** | A dependency outside §14.3's approved list, for a single JSON POST returning a byte stream. `httpx` is already pinned and already used for this exact shape. An SDK would also add a second place where vendor knowledge lives. |
| **Use `optimize_streaming_latency` to cut TTS latency** | **Deprecated** in ElevenLabs' own documentation. It is absent from this design only because the surface was verified before being specified — the same practice that caught four SDK defects in the original M9 pass. |
| **Validate `voice_id` at startup with `GET /v1/voices`** | Makes booting SUNIL depend on a vendor being reachable, contradicting ADR-016's restart model and turning a vendor outage into a boot failure. Instead the registry validates the field is present and non-empty, and a vendor 404/422 maps to a named permanent error `unknown_voice`, legible at first synthesis. |
| **Pin a well-known "premade" voice id in `config/speech.yaml` so the owner need not choose** | Ships a hard-coded vendor identifier read from a blog post, which is exactly the class of unverified constant this project writes zeros for. The owner picks a voice; the config carries his choice. |

## Consequences

1. **`sunil/speech/` now holds two adapters** — `openai_speech.py` (STT) and `elevenlabs_speech.py`
   (TTS). ADR-019's import rules are unchanged and now do real work.
2. **A third outbound destination.** `ELEVENLABS_BASE_URL` joins the ADR-017 canonical-or-loopback
   validator; `ELEVENLABS_API_KEY` joins the redaction registry (`sk_…`-shaped, so it also wants a
   pattern entry in §8.3). ADR-022 Amendment 1 covers the guard — **including why the microphone
   interlock deliberately does not extend to the synthesis leg.**
3. **`speech_calls` gains `billing_unit` and `billed_units`**; `config/speech.yaml` gains
   `billing_unit` and `unit_price` per capability. Migration `0002` is not yet written, so this changes
   an unwritten migration rather than adding a new one.
4. **Two vendors, two failure domains.** Transcription can succeed while synthesis is down. FR-207
   (a synthesis failure never fails the turn) is now load-bearing rather than defensive: muted playback
   is the *expected* behaviour during an ElevenLabs outage, not an edge case.
5. **The owner must create an account, a key and choose a voice.** The exact list is
   `M9_BUILD_PLAN.md` §9.
6. **This strengthens ADR-019 rather than complicating it** — argued in ADR-019 Amendment 1.
