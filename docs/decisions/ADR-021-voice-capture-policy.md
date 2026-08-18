# ADR-021 — Captured audio is discarded by default; the transcript is the only survivor

**Status:** Proposed (Architect, M9) · **Date:** 2026-08-19 · **Decider:** Solution Architect
**Context refs:** ADR-014 and its Amendment 1; `ARCHITECTURE_V1.md` §7.3.1, §8.3, §13.2;
`THREAT_MODEL.md` T-22, DC-15, DC-16; `ARCHITECTURE_M9_VOICE.md` §7, §11; NFR-050, NFR-052.

## Context

ADR-014 governs what may become training data. It classifies every record on the capture path at
insert time with four columns, resolved by one function, with defaults in `config/capture.yaml`. It was
written for text.

**Audio is worse than text in three specific ways.**

1. **A person speaking aloud says things they would never type.** A password read to yourself while you
   look for it. A client's full name. A third party audible in the room who never consented to
   anything. Typing is edited; speech is not.
2. **Redaction cannot work on audio.** §8.3's mechanism walks strings, dicts and lists, replacing
   registered secret values, secret-ish key names and high-signal patterns. There is no mechanism in
   SUNIL — and no cheap one anywhere — that removes a spoken API key from a waveform. **`redacted_full`
   is therefore unachievable for audio bytes**, and ADR-014's own standing rule is that a policy value
   which cannot be honoured must not be offered.
3. **A voice recording is biometric.** A stored corpus of the owner's speech is a voiceprint, which is
   a different category of data from a stored corpus of his typing and deserves a different default.

ADR-014 also fixed the vocabulary shape in Amendment 1: `CaptureKind` is **table-keyed**, one member
per capture-column-bearing table, because the four capture columns live on the row.

## Decision

| Artefact | What happens | Configurable |
|---|---|---|
| **The captured audio bytes** | **Discarded when the request ends.** One request-scoped `bytes` object, handed to the STT client, dropped. **No database column and no default file path can hold it** | `SUNIL_VOICE_AUDIO_RETENTION` = **`discard`** (default) \| `local_file` |
| **The transcript** | Becomes `messages.content` for the user's turn, exactly as a typed message would, under the existing `message` kind (`redacted_full / internal / standard`) | `config/capture.yaml` as today |
| **A second copy of the transcript in `speech_calls`** | **Not written.** The new `speech_call` kind defaults to **`metadata_only`**: duration, bytes, model, latency, cost, error kind — no content | `config/capture.yaml` → `speech_call` |
| **The synthesised reply audio** | Streamed to the browser; held in a bounded RAM cache for ≤10 minutes; never written to disk or database | not configurable |

**One new `CaptureKind` member — `SPEECH_CALL` — because M9 adds exactly one capture-bearing table.**
No new `ContentSource`: a transcript is `OWNER`, a synthesis input is `SUNIL_GENERATED`.
`audit_events` still has no member and never will.

**`messages.input_modality` (`text|voice`) is a column, not a `detail` key**, because a transcript has
different error characteristics from typed text — homophones, dropped words, punctuation invented by
the model — and a V3 corpus that cannot tell them apart will learn from both as if they were the same
artefact. That is ADR-014's argument applied to a new axis.

**`local_file`, and exactly what turning it on means.** It writes `var/voice/<request_id>.<ext>` at
mode `0600` (`var/` is already gitignored) and records the path in `speech_calls.audio_path`, NULL
under the default. It is implemented so the setting is a real choice rather than theatre, and because
reproducing a bad transcription is otherwise impossible. **Turning it on means accepting that anything
spoken is on disk verbatim, unredactable and unredacted, including anything said by accident.** That
sentence sits in `.env.example` beside the setting. Nothing purges it — the same gap `retention_class`
already has (D-11, M11) — and it is not exempted from that gap (DC-18).

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Retain the audio by default, classified `full_local_only`** | Superficially "capture everything for V3", and it is the option ADR-014 already rejected in its text form: `full_local_only` is **recorded, not enforced** (DC-15), so the label would protect nothing while the biometric data accumulated. Safe-looking defaults that are not enforced are the worst of both. |
| **Retain the audio classified `redacted_full`** | Not achievable. §8.3 cannot redact a waveform. It would be a claim the code does not have, which this project's threat model forbids in one sentence. |
| **`speech_call` defaults to `redacted_full` (store the transcript on the row)** | Stores the transcript **twice**, in `messages.content` and `speech_calls.transcript`, under two independent policies — so tightening one silently leaves the other in place. `metadata_only` keeps the shape and drops the duplicate. `redacted_full` is still a real, implemented value for debugging a bad transcription. |
| **`speech_call` defaults to `none`** | Nulls the metadata columns too, destroying the cost and latency record that FR-209 exists for. Cost data is not content. |
| **No `speech_calls` table; put speech metadata in `audit_events.detail`** | `audit_events` deliberately carries no capture columns (ADR-014 §2) precisely so a policy can never suppress an audit row; putting classified content there would invert that. It also has no place for cost, and ET-6 grades that table's row count. |
| **A new `CaptureKind` per artefact (`voice_clip`, `transcript`, `tts_input`)** | Directly contradicts Amendment 1: kinds are table-keyed because the four columns live on the row, and a kind finer than a row cannot be honoured. It is the exact mistake Amendment 1 was written to correct. |
| **No configurability — `discard`, full stop** | Defensible, and it was the first draft. Rejected because reproducing a mis-transcription is otherwise impossible, and because a setting whose *unsafe* value the owner must consciously choose, with the consequence written next to it, is a better control than an undocumented absence. |
| **A PII/DLP pass over the transcript before storage** | ADR-014 already rejected this for text ("a detector that misses one field is more dangerous than a declared policy that a human set"). It is worse here: the highest-risk content is exactly the free-form spoken aside a detector will not match. |

## Consequences

* `0002_voice` adds `speech_calls` with the four ADR-014 columns and `messages.input_modality`. No
  back-fill of policy is needed for existing rows: they are all `text`, which is true.
* **"Discarded" means no code path writes it.** It does not mean the bytes are scrubbed from process
  memory or from OS socket buffers, and it says nothing about what the vendor does after receipt —
  threat **T-40**, accepted, because the owner chose a cloud STT vendor knowingly and R§16 Epic 5's
  local voice is the answer. That limit is stated rather than implied.
* Redaction still runs on the transcript like any other text, so `sk-…`-shaped tokens are caught. **A
  spoken passphrase is not** — threat **T-41**, Partial, stated as Partial.
* `training_eligible` stays derived, never hand-set. A `metadata_only` `speech_calls` row is therefore
  not training-eligible, which is correct: there is nothing on it to train on.
