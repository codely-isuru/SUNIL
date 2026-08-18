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
