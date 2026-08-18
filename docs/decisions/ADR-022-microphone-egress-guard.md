# ADR-022 — The egress guard extends to microphone audio: a loopback speech endpoint is a separate consent

**Status:** Proposed (Architect, M9) · **Date:** 2026-08-19 · **Decider:** Solution Architect
**Supersedes nothing. Extends:** ADR-017 (which stands unamended).
**Context refs:** ADR-017; `ARCHITECTURE_V1.md` §9.7, §14.4; `THREAT_MODEL.md` T-24;
`ARCHITECTURE_M9_VOICE.md` §8; NFR-013.

## Context

ADR-017 exists because an env-settable API base URL is an exfiltration channel: redirect the Anthropic
or OpenAI URL and every prompt leaves; redirect the GitHub URL and the request carries
`Authorization: Bearer <PAT>` to the attacker's host. Its guard is one validator in `settings.py` —
**canonical, or loopback, or the application refuses to boot** — and it is enforced by construction, not
by an environment flag that can be forgotten.

ADR-017 accepted the loopback exception with an explicit argument:

> Residual risk **T-24**: a hostile process on the owner's own machine could listen on loopback and
> harvest the PAT. That process can already read `.env`, so this adds no meaningful exposure.

**M9 breaks the second half of that sentence.** A process that can read `.env` gains prompts it could
also have read from `var/sunil.db`. A process that receives *microphone audio* gains something that
exists nowhere else on the machine — a live recording of the room the owner is sitting in. The
exposure is not equivalent, so the acceptance does not transfer unexamined.

## Decision

**1. The existing validator covers speech unchanged, and no new base-URL setting is introduced.**
The speech adapter is constructed from `settings.openai_base_url`, which already carries
`_check_openai_base_url`. A non-canonical, non-loopback value still refuses to boot. One canonical
host, one validator, one place to review — **no new setting means no new hole**.

**2. NEW — the interlock. A loopback base URL disables voice unless separately opted into.**
*(Amendment 1 narrows this to the transcription leg and renames the flag `SUNIL_VOICE_ALLOW_LOOPBACK_STT`. The block below is the original wording, kept because a changed decision is a recorded change.)*

```
openai_base_url canonical                                        → voice available
openai_base_url loopback  +  SUNIL_VOICE_ALLOW_LOOPBACK_EGRESS=false (default)
                                                                 → every voice endpoint returns 503
openai_base_url loopback  +  SUNIL_VOICE_ALLOW_LOOPBACK_EGRESS=true
                                                                 → voice available (QA's harness)
anything else                                                    → the app does not boot (ADR-017)
```

The reasoning is one sentence: **"a local test double may receive my prompts" and "a local process may
receive my microphone" are different consents, and one flag should not grant both.**

It is expressed as a computed `Settings.voice_available`, checked at startup (and logged) and again per
request, **not** as a construction-time raise — because raising would prevent QA booting an app against
a speech double at all, and ADR-017's boot-refusal already covers the case that genuinely must be
fatal. This is the one place M9 chooses a 503 over a boot failure, and the reason is written here so
it is not read as inconsistency.

**3. NEW — one startup line naming where audio goes**, following ADR-017's own "both are logged at
startup, which is how a wrong one becomes visible immediately":

```
voice.egress base_url=https://api.openai.com/v1 canonical=true
             stt=gpt-4o-mini-transcribe tts=gpt-4o-mini-tts retention=discard
```

**4. `SUNIL_VOICE_ENABLED` ships `false`** and is flipped when the last M9 task lands and is verified —
the pattern `SUNIL_PROGRESS_EVENTS` used (§8.4). **It is a delivery switch, not a security control**,
and is not presented as one. Disabled voice returns **404**, not 403: a disabled feature should not
confirm its own existence.

**5. The audio has exactly one way out of the process, and it is mechanised.** Two DC-10 import rules
(T35): `sunil/speech/` joins `sunil/providers/` as the only packages permitted to import a vendor SDK,
and only `sunil/api/routes/voice.py` may import `sunil.speech.*`. `core/`, `agents/` and `tools/`
cannot reach speech at all.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **A separate `SUNIL_SPEECH_BASE_URL` with its own validator** | A second env-settable outbound destination to review, guard, log and get wrong — the exact surface ADR-017 minimised. Reusing `OPENAI_BASE_URL` means the vendor's canonical host is asserted in one place. R§6's "need not be the same service" is honoured by adding a *second speech provider with its own credentials* (ADR-003 §4.6's recipe), not by splitting one vendor's key in two. |
| **A separate `SUNIL_SPEECH_API_KEY`** | Same reasoning, plus it forces the owner to paste one key twice, and a second copy of a secret is a second thing that can be committed. One key per vendor. |
| **Forbid loopback for speech entirely** | Then the real adapter is never executed by a test — the exact failure ADR-017 was written to prevent, where "a protocol-level fake cannot test the adapter that the fake replaces". The exit suite would assert a fake. |
| **Allow loopback for speech under the same flagless rule as prompts** | Reuses an acceptance whose stated justification does not hold for audio. Re-deriving the argument and finding it fails, then keeping the conclusion anyway, is how controls rot. |
| **`SUNIL_ENV=test` gating the whole thing** | ADR-017 already rejected this by name: it adds an environment concept whose only job is to be set correctly, and whose failure mode is a production instance quietly talking to an arbitrary host. |
| **Refuse to *boot* when loopback + interlock unset** | Would stop QA running the exit suite against a speech double with voice disabled, and would make an unrelated misconfiguration fatal to the whole API rather than to one feature. The fatal case (non-canonical, non-loopback) is already fatal. |
| **A warning log instead of the interlock** | ADR-017's own words: "a warning in a log nobody reads is not a control." |

## Consequences

* **V1 still cannot use a forward proxy or an audio gateway.** ADR-017's limitation, unchanged and
  deliberate.
* QA's speech double needs **two** settings, not one: a loopback `OPENAI_BASE_URL` and
  `SUNIL_VOICE_ALLOW_LOOPBACK_EGRESS=true`. That is friction, and it is the friction the decision is
  buying.
* Residual **T-35**: a hostile local process, with the interlock explicitly enabled by the owner, could
  receive audio. That now requires two deliberate configuration acts rather than one, and both are
  logged at startup.
* Residual **T-40**, unchanged and outside architecture: what the vendor does with received audio.
  Accepted by explicit roadmap design; R§16 Epic 5's local voice is the answer and it is V2.
* `THREAT_MODEL.md` gains **§12** — a new boundary **TB8** (API ↔ speech vendor), a new asset **A8**
  (captured audio and its transcript), threats T-35…T-42, and DC-17…DC-19.

---

## Amendment 1 — a third destination, and the interlock is narrowed to the leg it was argued for

**Date:** 2026-08-19 · **Origin:** ADR-026 (synthesis moves to ElevenLabs)
**Status:** Accepted · **Applies to:** decision items 1 and 2, and the config inventory.

### 1. `ELEVENLABS_BASE_URL` joins the ADR-017 validator, unchanged

A third canonical host, the same one validator, the same rule: **canonical, or loopback, or the
application does not boot.**

```python
_CANONICAL_BASE_URLS = {
    "anthropic_base_url":  "https://api.anthropic.com",
    "github_api_base_url": "https://api.github.com",
    "openai_base_url":     "https://api.openai.com/v1",
    "elevenlabs_base_url": "https://api.elevenlabs.io",     # NEW — note: no /v1 suffix
}
```

`ELEVENLABS_API_KEY` is a `SecretStr | None` and joins the redaction registry. Its documented prefix
(`sk_…`) is close enough to OpenAI's `sk-` that §8.3's pattern list should gain an explicit
`sk_[A-Za-z0-9]{20,}` entry rather than relying on the registered-value match alone — belt and braces,
the same posture ET-10 already takes.

A redirected ElevenLabs base URL leaks the **`xi-api-key` header**, not `Authorization: Bearer`. Same
class of theft, different header name; the guard does not care, and neither does this amendment beyond
recording that the adapter must not be written to assume one shape.

### 2. **The microphone interlock does NOT extend to the synthesis leg** — and this is the substantive ruling

`SUNIL_VOICE_ALLOW_LOOPBACK_EGRESS` is renamed **`SUNIL_VOICE_ALLOW_LOOPBACK_STT`** and gates only the
transcription leg.

The Delivery Manager asked whether the interlock's reasoning applies to synthesis. **It does not, and
saying so is more honest than extending a control by reflex.** The original argument was specific:

> ADR-017 accepted the loopback exception because a hostile local process *"could already read
> `.env`"*, so loopback added no meaningful exposure. That reasoning holds for prompts. **It does not
> hold for microphone audio, which exists nowhere else on the machine.**

Now apply the same test to the synthesis leg. What crosses it outbound is **the text of SUNIL's own
answer** — already persisted in `messages.content`, already readable from `var/sunil.db` by any
process that can reach the file. That is TB2's disclosure profile exactly, and ADR-017 already
reasoned about it and accepted it. What comes back is audio SUNIL asked to be generated. **Neither
direction carries anything that exists nowhere else.** So the extra consent has nothing to protect,
and a flag guarding nothing is worse than no flag: it dilutes the one that does protect something.

Stated as a rule: **the interlock exists for the microphone, not for the word "voice".** Renaming it to
say `STT` removes the ambiguity that let this question arise at all.

| Leg | Outbound content | Guard |
|---|---|---|
| `transcription` | **the owner's microphone audio** — exists nowhere else | ADR-017 validator **+ `SUNIL_VOICE_ALLOW_LOOPBACK_STT`** |
| `synthesis` | SUNIL's own answer text, already in `messages.content` | ADR-017 validator alone |

**Consequence, stated so it is not mistaken for an oversight:** with `ELEVENLABS_BASE_URL` pointed at
loopback, a local process receives SUNIL's answer text and the ElevenLabs key with no second flag.
That is deliberate, it is identical to what `ANTHROPIC_BASE_URL` and `OPENAI_BASE_URL` have always
permitted, and it is covered by the existing residual **T-24** rather than by a new one.

It also makes QA's life correct rather than merely easier: an exit test for synthesis needs a loopback
double and one setting, while an exit test for transcription needs a loopback double and **two** —
which is exactly the asymmetry the threat model claims.

### 3. The startup egress line names both destinations

```
voice.egress stt=openai base_url=https://api.openai.com/v1 canonical=true model=gpt-4o-mini-transcribe
             tts=elevenlabs base_url=https://api.elevenlabs.io canonical=true model=eleven_flash_v2_5
             retention=discard zero_retention_requested=true
```

### 4. `SUNIL_VOICE_AUDIO_RETENTION` is gone from the inventory

Withdrawn by ADR-021 Amendment 1. `retention=discard` above is a statement of fact, not of
configuration.
