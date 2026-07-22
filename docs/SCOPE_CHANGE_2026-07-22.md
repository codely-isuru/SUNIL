# Scope change — 2026-07-22

**Decided by:** the owner (Isuru), in session.
**Status:** applied to `docs/IMPLEMENTATION_PLAN.md`. Downstream documents are
annotated below rather than rewritten, so nothing already approved is silently
altered.

## 1. The decision

> "For now we will have only the daily workflows and the voice chat. Let's pause
> the AI team registration bit."

SUNIL's near-term product is a **personal assistant**: it runs the daily
workflows, and it can be spoken to and answer aloud. Everything else waits.

| Area | Was | Now |
|---|---|---|
| Foundation (Phase 1) | Built | **Unchanged** — built, pending review sign-off |
| Core SUNIL (Phase 2) | Planned | **In scope** — prerequisite for both goals |
| Daily brief (Phase 3a) | Planned | **In scope — the deliverable** |
| Voice (was an "optional adapter" in Phase 3) | Optional extra | **In scope — promoted to a first-class deliverable (3b)** |
| Business integrations (Phase 4) | Planned | ⏸ Deferred |
| **Autonomous AI teams (Phase 5)** | Planned | ⏸ **Paused — the explicit decision** |
| Computer control (Phase 6) | Planned | ⏸ Deferred |
| Production readiness (Phase 7) | Planned | Applies to the narrowed scope |

**Phase numbering is deliberately unchanged.** Voice was already assigned to
Phase 3 by three approved documents (`PHASE1_REQUIREMENTS.md` §1.3,
`design/SUNIL_PRESENCE_SPEC.md` §266, `design/PORTAL_SHELL_SPEC.md` §5.1).
Renumbering would have invalidated every one of those cross-references for no
benefit. The change is therefore *stop after Phase 3*, plus a promotion of voice
within Phase 3 — not a re-plan.

## 2. What this costs — nothing already built

Checked against the delivered code rather than assumed:

* **No team tables were ever built.** `packages/db/prisma/schema.prisma` has no
  `Team` or `TeamMember` model — the Phase 1 schema is identity, settings,
  audit, usage, agents and jobs. Pausing Phase 5 leaves **no dead schema, no
  orphan migration and no unused code**.
* **The agent runtime is unaffected.** `packages/agents` implements a *single*
  config-driven agent with envelopes, heartbeats and in-loop budget enforcement.
  That is exactly what the daily workflows need. Teams were always a layer
  *above* it, never a change to it.
* **Deferred-phase interfaces stay as seams.** `MailProvider`, `ChatProvider`,
  `IssueProvider`, `SupportProvider` remain the boundaries in `INTEGRATIONS.md`.
  The personal mailbox in Phase 3a uses the same `MailProvider` the deferred
  business mailboxes will use, so Phase 4 remains additive.
* **`<SunilPresence />` was built for this.** Its `speaking` amplitude prop was
  specified and implemented in Phase 1, documented as inert until voice arrives.
  Phase 3b finally drives it. Nothing to retrofit.

The narrowed scope removes work; it does not invalidate any.

## 3. What this newly requires — voice needs design that does not exist

Promoting voice from an optional output adapter to half of Phase 3 exposes a
genuine gap. **Voice currently has no architecture.** Before it can be built:

1. **No `VoiceProvider` interface exists.** `INTEGRATIONS.md` lists `MailProvider`,
   `CalendarProvider`, `ChatProvider`, `IssueProvider`, `SupportProvider`,
   `WeatherProvider` and `LLMProvider` — there is no speech interface at all.
2. **No STT/TTS provider decision, and it is a privacy decision, not a technical
   one.** The options differ in what leaves the machine:
   * *Browser `speechSynthesis` / Web Speech API* — free, zero setup, already
     proven in the prototype, but recognition quality is weak and on some
     browsers audio is sent to a vendor anyway.
   * *Self-hosted (e.g. Whisper locally, a local TTS voice)* — nothing leaves
     the machine, consistent with the security posture, at the cost of setup
     and local compute.
   * *Cloud APIs (e.g. Deepgram, ElevenLabs, OpenAI speech)* — best quality and
     lowest latency, but **the owner's spoken audio goes to a third party**.
3. **`SECURITY_MODEL.md` says nothing about voice.** It governs email, secrets,
   computer control and audit, but has no position on audio capture, retention,
   transcript storage, or a wake word listening continuously. This document is
   binding on every phase, so the gap must be closed before 3b is built.
4. **Conversation mechanics are unspecified** — barge-in, turn-taking, how a
   transcript is persisted, what is retained versus discarded, and what happens
   when recognition is wrong on a *mutating* request. A misheard command that
   creates or sends something is the obvious hazard; the existing approval gates
   are the natural control, but that needs stating.

These are Solution Architect deliverables (an ADR plus a `SECURITY_MODEL.md`
amendment), and they are the first work of Phase 3b.

## 4. Consequences for the current state of work

* **Phase 1 sign-off is unaffected.** The outstanding Stage 6 Security and QA
  review still applies in full and is still the gate before anything else. The
  scope change does not lower that bar.
* **The portal shell already tells the truth.** `apps/web` renders all 22
  navigation destinations with the out-of-scope ones visibly disabled and marked
  "not yet available". Deferred phases simply stay disabled for longer; the UI
  needs no change and never claimed otherwise.
* **The deferred critical test scenarios (3–7, 10) are not weakened.** The rules
  behind them — approval before any external action, no permanent deletion,
  idempotent imports, prompt injection cannot escalate permissions — remain
  binding on everything built in the meantime.

## 5. Open questions for the owner

Recorded rather than assumed. None blocks the Phase 1 review, and each has a
recommended default so it can be confirmed or corrected rather than designed.

1. **Does "daily workflows" mean the daily brief plus recurring routines, or
   also the visual workflow builder** (the triggers → conditions → actions graph
   in `SUNIL_ARCHITECTURE.md` §2.3)?
   *Recommended default:* the brief plus recurring routines on the durable
   scheduler already built. The visual builder is a large piece of UI that
   neither goal needs, and it defers cleanly.
2. **Voice privacy — which provider posture?**
   *Recommended default:* self-hosted/on-device, matching the security model's
   existing stance that SUNIL's data stays under the owner's control; accept the
   quality and setup cost. A cloud provider is a legitimate choice but should be
   a recorded, deliberate exception rather than a default.
3. **Is voice input allowed to trigger mutating actions**, or is it
   read/ask-only until confidence is proven?
   *Recommended default:* voice may *propose* any action, but anything external
   or destructive routes through the existing approval gate — no new permission
   path is created by speaking.
4. **Business integrations (Phase 4) confirmed deferred?** The daily brief needs
   only the personal mailbox. The Codely and Ezy Clean mailboxes, Teams and Jira
   were the largest remaining block of work, and "only the daily workflows and
   the voice chat" reads as excluding them.
   *Recommended default:* deferred, as recorded above.
