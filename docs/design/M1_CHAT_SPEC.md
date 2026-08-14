# SUNIL — M1 Chat Interface Specification

**Author:** UI/UX Designer, Minions Team 18
**Status:** Developer-ready for build starting 2026-08-17. Scope: **M1 chat only** — no
dashboard chrome, no conversation list/history, no approval UI, no settings. Those are M8/M5/M2
and are explicitly out of scope here (see §9).
**Traces to:** `docs/REQUIREMENTS_V1.md` FR-003, FR-020–022, FR-026, FR-060–067, FR-105, FR-107,
NFR-020, NFR-060, NFR-071, ET-1–ET-11. Roadmap `docs/ROADMAP.md` §22, §28.
**Tokens used throughout:** see `DESIGN_SYSTEM.md` — this document only names tokens, it does
not redefine them.

---

## Assumptions requiring Architect / owner confirmation at Gate 2

Read this section first — it affects how the whole "make the work visible" part of the spec is
built. I made a call in each case so the spec is buildable now, but both need sign-off.

**ASSUMPTION 1 — a lightweight progress-events channel exists in M1, separate from response
streaming.**
Per SRS FR-020, the M1 chat endpoint is a single synchronous request/response — the full answer
is not returned until the whole flow (interpret → plan → agent → tool → analyse → respond) is
done, and token-level response streaming is explicitly M2 (FR-024). Taken literally, that means
the frontend has **no live signal** to show real stage-by-stage progress during the ≤30s p95
wait — it would only know "request sent" and "response received."

Given the brief's own instruction that "a spinner for thirty seconds is not an acceptable
answer," and given roadmap §33 Rule 10 ("every important action must be observable"), I have
designed this spec **assuming a minimal one-way progress channel** exists alongside the
synchronous endpoint — e.g. Server-Sent Events or a WebSocket keyed by `request_id` that pushes
*stage-change* events only (not the final answer's tokens; that remains a single blocking
payload in M1). This is the smallest addition that lets the UI show real, honest progress instead
of either a bare spinner or fabricated/timed fake progress.

**If the Architect confirms M1 truly has zero progress channel** (the synchronous POST is the
only contract), §5.3 below documents the fallback: a **deterministic, non-random** client-side
phase stepper using realistic minimum-display durations per phase (not literally driven by
backend events). This is still honest in that it reflects the real, fixed order of work
(interpret → plan → execute → respond) — it just can't confirm timing live. Both variants use
the same visual component; only the event source differs. **This choice — build the real channel
vs. ship the client-side stepper — needs the Architect's confirmation before Day 1,** because it
changes what the frontend needs from the API surface.

**ASSUMPTION 2 — Cancel is client-side-only unless the Architect wires a server-side abort.**
Clicking Cancel mid-run aborts the client's wait (`AbortController` on the fetch/stream) and
immediately restores the composer. Whether this also stops the Orchestrator/agent/tool work
server-side, or whether that work completes anonymously in the background, is an architecture
decision. §6 below specifies UI copy that is honest for the **client-side-only** case (the safe
default assumption); if the Architect provides a real cancellation signal, the copy can be
strengthened (see the noted variant).

Neither assumption should block starting the visual/component build — the component contracts
in §7 are written so either resolution slots in without a redesign.

---

## 1. Layout

### 1.1 Desktop (≥768px)

Single-conversation, full-viewport chat. No sidebar, no nav rail in M1 (conversation
list/history is FR-025, M2; there is exactly one conversation per session in M1, auto-created on
first message per FR-022).

```
┌──────────────────────────────────────────────────────────────┐
│  S.U.N.I.L                                    ● session   ⎋  │  ← top bar, 56px, surface bg
├──────────────────────────────────────────────────────────────┤
│                                                                │
│                     (max-w-3xl, centred)                      │
│                                                                │
│   [ user message, right-aligned bubble ]                      │
│                                                                │
│   [ SUNIL avatar ]  Reading your request…            0:04     │
│                     ─ ─ ─ ─ ─ ─ ─ ─ ─ ─                        │
│                                                                │
│   [ SUNIL avatar ]  <assistant reply>                          │
│                     10:42 am · View reasoning steps ⌄          │
│                                                                │
├──────────────────────────────────────────────────────────────┤
│   [  composer textarea, auto-grow 1–6 lines   ]      [ Send ] │  ← fixed bottom, surface bg
└──────────────────────────────────────────────────────────────┘
```

- Top bar: 56px, `bg-surface`, bottom border `border-DEFAULT`. Left: wordmark "S.U.N.I.L" in
  `font-display`, small (H2 scale, not the huge Display scale — this is chrome, not a hero).
  Right: a session status dot (`success` = active) + a minimal sign-out affordance (icon
  button). **The login screen itself is out of scope for this spec** — FR-007 requires an
  authenticated session before the chat endpoint accepts a request, so an unauthenticated visit
  redirects to a login flow; that flow's screen is not designed here (mechanism is the
  Architect's call per SRS Open Question Q3). This chat screen is the **post-login landing
  screen**.
- Message column: `max-w-3xl`, `mx-auto`, vertical padding `py-6`, message gap `gap-4`.
  Auto-scrolls to bottom on new content; if the user has scrolled up, new content does **not**
  yank them down — instead show a small pill "↓ New reply" (see §7, `JumpToBottomPill`).
- Composer: fixed to viewport bottom, `bg-surface`, top border `border-DEFAULT`, inner padding
  `p-4`.

### 1.2 Mobile (<640px, Tailwind `sm` breakpoint)

- Message column becomes full-width with `px-4` gutter (not a fixed max-width card).
- Message bubble max-width becomes `88%` of viewport instead of a fixed px cap.
- Top bar wordmark collapses to a compact mark (e.g. just "S" in the display font) to save
  width; session dot + sign-out remain.
- Composer respects `env(safe-area-inset-bottom)` so it isn't obscured by the iOS home
  indicator/keyboard bar.
- **Enter-to-send is desktop-only.** On mobile, the on-screen keyboard's return key behaviour is
  inconsistent across devices/IMEs, so sending is **always** via the explicit Send button tap.
  Shift+Enter-for-newline doesn't apply either (soft keyboards don't reliably expose Shift) —
  the Enter/return key simply inserts a newline on mobile; only the Send button submits.
- All tap targets (Send, Cancel, the trace-disclosure chevron, sign-out) are minimum 44×44px.

---

## 2. Screen composition

```
ChatShell
 ├─ TopBar
 ├─ MessageList
 │   ├─ EmptyState              (only when zero messages)
 │   ├─ MessageBubble (user)    (one per user turn)
 │   ├─ AssistantMessage        (one per completed assistant turn, includes TraceDisclosure)
 │   ├─ WorkIndicator           (zero or one — only for the currently in-flight turn)
 │   ├─ ErrorCard               (zero or one — replaces WorkIndicator on failure)
 │   └─ JumpToBottomPill        (conditional, floating)
 └─ Composer
```

Only one of `WorkIndicator` / `ErrorCard` / (nothing) exists at a time, and only for the most
recent turn — M1 has no concurrent requests (the backend is single-turn-synchronous per FR-020,
and this spec does not attempt to design multi-turn overlap).

---

## 3. Empty state

**Trigger:** a session with zero messages (first visit, or FR-022's freshly auto-created
conversation before the first send).

**Content:**
- Centred vertically in the message column.
- A small static SUNIL mark (not the animated canvas sphere — see `DESIGN_SYSTEM.md` §0) —
  e.g. a simple glowing ring/dot rendered in CSS, `accent` colour, no motion required (a subtle
  one-time fade-in on mount is fine, respecting reduced-motion).
- Greeting line, `H1` scale: **"Ask me to check on something."**
- Two suggestion chips, populated from the FR-107 static project-name config (there is at least
  one configured project in M1 per SRS Assumption A2/A3 — engineer substitutes the real
  configured name(s) for `{Project}` below):
  - `Check on {Project}`
  - `What's changed in {Project} recently?`
- Clicking a chip **populates the composer with that exact text and focuses it** — it does not
  auto-send. The user still presses Send. (This avoids surprising the user with an instant
  network call from what looks like a static suggestion.)
- No other copy. Do not list capabilities SUNIL doesn't yet have in M1 (no "I can also check
  your email/calendar" — those tools don't exist yet; overpromising here is a real risk given
  how much of the roadmap is still ahead).

---

## 4. Composer states

| State | Trigger | Visual | Behaviour |
|---|---|---|---|
| **Idle** | No text entered | Placeholder: *"Ask SUNIL to check on something…"*, in `text-muted`. Send button disabled (dim, `text-disabled`, `cursor-not-allowed`). | — |
| **Typing** | User has entered non-whitespace text | Send button enabled (`accent` fill). | Enter sends (desktop only, see §1.2); Shift+Enter inserts newline (desktop only). Textarea auto-grows 1→6 lines, then becomes internally scrollable. |
| **Busy** | A request is in flight (from send until complete/error/cancel) | Textarea becomes read-only and visually dimmed (`text-disabled` overlay, not removed from DOM — content stays visible). The Send button **is replaced in the same slot** by a **Cancel** button (`danger` outline style) — no layout shift. | User cannot start a second message while one is in flight (M1 has no concurrent-turn design — see Assumption 2 context). Clicking Cancel triggers §6. |
| **Recovery** | After an error/cancel | Textarea returns to **Typing** state, pre-filled with the original message text (not cleared) so the user can edit and retry without retyping. | Send button re-enabled immediately. |

---

## 5. Message list states

### 5.1 User message

Right-aligned bubble, `bg-accent` at 12% (a light tint, not full accent fill, so `text-primary`
stays legible on it — do not put white/primary text on a full-strength `#22D3EE` fill without
switching to `--color-accent-on`), `radius-md`, `p-3`. Timestamp in `Small/meta` scale,
`text-muted`, shown on hover/focus (desktop) or always visible (mobile, since there's no hover).

### 5.2 Assistant message — complete

Left-aligned, prefixed with a small static SUNIL mark (16–20px). Body in `Body` scale on
`bg-surface`, `radius-md`, `p-4`. Markdown supported: bold, lists, inline code, fenced code
blocks (rendered in `surface-raised` per `DESIGN_SYSTEM.md` Code style). Below the message:

- Timestamp (`Small/meta`, `text-muted`).
- **`View reasoning steps ⌄`** — a small text link (not a button-styled control) that expands
  `TraceDisclosure` (see §7). Collapsed by default; state does not persist across page reload in
  M1 (no conversation history to restore it into, per FR-025 being M2).

### 5.3 Thinking / working — stage progression

**This is the core design problem the brief calls "the interesting part."** A chat turn here
represents up to 30 seconds (p95) of genuine multi-step work: interpret → plan → start agent →
call tool → analyse → respond. Twelve raw backend stages exist (NFR-020). Showing all twelve as
a scrolling log turns the chat into a log viewer, which the brief explicitly rejects; showing
nothing for 30 seconds is explicitly rejected too. The resolution: **compress 12 raw stages into
4 visible phases**, shown live in place (updating in-place, never stacking/scrolling), with one
dynamic, specific detail substituted in where possible (which tool/project) so it reads as real
progress rather than a generic loader — and keep the full 12-stage detail available, but only on
demand, after completion, via `TraceDisclosure` (§5.5/§7), not during the wait.

**Stage → phase mapping** (left column = exact NFR-020 stage names; right column = what the
user sees):

| # | Backend stage (NFR-020) | Visible phase | Live label shown |
|---|---|---|---|
| 1 | message received | Understanding | *"Reading your request…"* |
| 2 | context loaded | Understanding | *(same label — stages 1–5 share one visible phase)* |
| 3 | memory retrieved | Understanding | " |
| 4 | model selected | Understanding | " |
| 5 | LLM input/output | Understanding | " |
| 6 | plan created | Planning | *"Working out a plan…"* |
| 7 | agent started | Working | *"Checking {Project}…"* — substitute the resolved project/tool name once the plan is known; before that's known, *"Working on it…"* |
| 8 | tool requested | Working | *(same label)* |
| 9 | permission decision | Working | " |
| 10 | tool result | Working | " |
| 11 | agent result | Finishing | *"Putting your answer together…"* |
| 12 | final response | Finishing | *(same label)* |

**Visual treatment:** a single card, left-aligned like an assistant message, `bg-surface`,
`radius-md`, `elevation-2` (active glow, per `DESIGN_SYSTEM.md` §5), containing:
- The current phase label (`Body` scale, `text-secondary`).
- A small breathing-glow indicator (the `pulse` motion token) — three dots or a short dashed
  line animating, **not** a percentage bar (M1 cannot know true % complete, and a fake
  percentage would be dishonest).
- An elapsed-time counter, small, `text-muted`, format `0:04`, `0:12`, etc.
- A text **Cancel** control, right-aligned within the card (see §6).

**Timing rules (apply regardless of which Assumption-1 variant is built):**
- Minimum display time per phase: 400ms, even if the real/simulated event for the next phase
  arrives sooner — prevents flicker on fast tool calls.
- Past **20 seconds** elapsed: append a second, smaller line under the phase label:
  *"Still working — larger checks can take a little longer."* (`Small/meta`, `text-muted`).
- Past **45 seconds** elapsed (a safety margin above the 30s p95 target — since p95 means some
  requests legitimately exceed 30s, but 45s is past the point of reasonable doubt): the client
  treats this as a timeout and transitions to the generic **Error** state (§5.6) with the
  timeout copy, and aborts the wait. This 45s figure is a frontend UX default, not an
  architectural constraint — it can move without a Gate 2 conversation.
- **Reduced motion:** the pulse animation is replaced by a static glow border only; the phase
  label and elapsed counter still update (they're text, not motion) — no information is lost.
- **Screen reader:** the phase label lands in `aria-live="polite"`, updated once per phase
  change only (4 updates max per turn, never once per raw backend stage) — see
  `DESIGN_SYSTEM.md` §7.

**Fallback variant (if Assumption 1 resolves to "no progress channel exists"):** the same visual
component runs on a fixed, non-random client-side timer instead of real events: Understanding
0–3s, Planning 3–5s, Working 5s→(response received), Finishing shown for the final 1s before the
reply replaces it. These durations are illustrative defaults tuned to feel plausible against the
30s target, not measured — flag this clearly to the Architect as the inferior of the two options
before committing to it.

### 5.4 Reply arriving

Per FR-020, M1 has **no token-level response streaming** — the full answer text arrives as one
payload. Rather than either (a) a fake per-character typewriter effect implying live generation
that isn't happening, or (b) an instant, jarring swap, the `WorkIndicator` card is replaced by
the `AssistantMessage` with a single **250ms fade+8px-rise** transition (`duration-base`,
`ease-standard`; disabled under reduced motion — the swap becomes instant). Name this state
"reply arriving" rather than "streamed reply" in any code/comments — it is honest about what M1
actually does. **Forward-compatible note:** when M2 adds real WebSocket token streaming
(FR-024), this exact slot (the `AssistantMessage` body) is where progressive token rendering
gets added — no restructuring needed, just an incremental-render mode inside the same component.

### 5.5 Complete

Final state of §5.2. Additionally: focus is **not** stolen from the composer when a reply
lands (the user may already be typing their next message) — the message list update must not
move keyboard focus. The `TraceDisclosure`, when expanded, renders the 12 stages from the table
in §5.3 in plain, human-readable form (not raw JSON/log lines), each with its own short
timestamp offset, e.g.:

```
Received your message                         +0.0s
Loaded conversation context                    +0.1s
Checked memory                                 +0.2s
Selected Claude for reasoning                   +0.3s
Interpreted the request                        +2.1s
Created a plan: check {Project} activity        +2.4s
Started Project Manager Agent                   +2.5s
Requested GitHub — recent activity              +2.6s
Permission: Allowed (read-only)                 +2.6s
Received result from GitHub                     +4.8s
Analysed the result                             +7.2s
Prepared your answer                            +7.9s
```

This is the human-readable rendering of NFR-020's audit trail and is the seed of the full M8
debug trace view (`NFR-021`) — see `DASHBOARD_DIRECTION.md`.

### 5.6 Error (generic / provider or timeout failure)

**Trigger:** provider failure after retries exhausted (NFR-071), or the client-side 45s timeout
(§5.3).

**Visual:** replaces the `WorkIndicator` card. Same card shape, `border-danger` instead of
accent glow, a warning icon, and:

> **"Something went wrong on my end and I couldn't finish that."**
> `[ Try again ]`

`Try again` re-submits the exact same original user message (not a copy into the composer —
one click, one retry, per FR-071's "clear, non-crashing error" requirement). The user's message
bubble above it is untouched.

### 5.7 Tool-failed

**Trigger:** the M1 tool adapter itself errors (FR-104) — e.g. GitHub unreachable/rate-limited —
distinct from a model/provider failure.

> **"I couldn't reach GitHub to check that just now. Try again in a moment."**
> `[ Try again ]`

Same visual treatment as §5.6 (danger border, warning icon), different copy so the user knows
*what* failed (external tool vs. SUNIL's own reasoning) — this distinction matters because the
correct next action differs (retrying immediately after a rate-limit rarely helps; the copy says
"in a moment" deliberately).

### 5.8 Plan-rejected

**Trigger:** the Orchestrator's own generated plan fails schema/whitelist validation on every
retry attempt (FR-062) — the system rejected its own plan as unsafe/invalid; this is **not** a
human-in-the-loop approval rejection (there is no approval UI in M1, per SRS Q4 — that's M5).

> **"I wasn't able to work out a safe plan for that request. Could you rephrase it?"**
> `[ Edit message ]`

`Edit message` returns focus to the composer with the original text intact for editing (matches
the Composer "Recovery" state, §4) rather than offering a blind retry — since the same phrasing
failed once, re-sending it unchanged is unlikely to help.

### 5.9 Unknown project

**Trigger:** FR-107 / ET-11 — the request names a project with no entry in the static config
mapping.

> **"I don't recognise that project. Right now I only know about: {Project A}, {Project B}."**
> `[ Edit message ]`

The `{Project A}, {Project B}` list is populated from the same FR-107 config the suggestion
chips in §3 use — engineer should share one source of truth for "configured project display
names" between the empty-state chips and this error copy, so they never drift out of sync.

---

## 6. Cancel — what it means mid-run

Cancel is available throughout the entire `WorkIndicator` lifecycle (§5.3), as a text control
inside the card.

**Behaviour (client-side-only default — see Assumption 2):**
1. On click, the client immediately aborts its wait for the response (`AbortController`).
2. The `WorkIndicator` card is replaced by a small, neutral, centred system note (not a
   bubble, not danger-styled — cancellation is not an error):
   > *"You cancelled this. I'll stop showing progress for it — it won't appear as a reply, even
   > if I finish it in the background."*
3. The composer returns to **Recovery** state (§4) with the original text intact.

**If the Architect confirms a real server-side cancellation signal is wired** (the abort
actually stops the Orchestrator/agent/tool call rather than orphaning it), simplify the copy to:
*"Cancelled."* — drop the "even if I finish it in the background" clause, since it would no
longer be true. Flag this copy change as dependent on that confirmation.

---

## 7. Component inventory

| Component | Key props | Behaviour notes |
|---|---|---|
| `ChatShell` | — | Page-level layout: `TopBar` + `MessageList` (flex-1, scrollable) + `Composer` (fixed). |
| `TopBar` | `sessionStatus: 'active'` | Wordmark + status dot + sign-out icon button. No nav in M1. |
| `MessageList` | `messages: Message[]`, `activeTurn: WorkingTurn \| ErrorTurn \| null`, `onJumpToBottom` | Renders `EmptyState` when `messages.length === 0`. Auto-scrolls on append unless user has scrolled up >~100px, in which case shows `JumpToBottomPill`. |
| `MessageBubble` (user) | `content: string`, `timestamp: string` | Right-aligned, tinted accent bg. |
| `AssistantMessage` | `content: string (markdown)`, `timestamp: string`, `trace: TraceStep[]`, `expanded: boolean`, `onToggleTrace` | Renders markdown; `TraceDisclosure` is a child. |
| `TraceDisclosure` | `steps: {label: string, offset: string}[]`, `expanded: boolean`, `onToggle` | Collapsed by default; plain-language 12-line list per §5.5; keyboard-toggleable (Enter/Space on the chevron), `aria-expanded`. |
| `WorkIndicator` | `phase: 'understanding' \| 'planning' \| 'working' \| 'finishing'`, `dynamicLabel?: string`, `elapsedSeconds: number`, `showReassurance: boolean`, `onCancel` | Drives §5.3. `dynamicLabel` substitutes into the "Working" phase copy once the plan names a project/tool. Emits one `aria-live="polite"` announcement per phase change. |
| `ErrorCard` | `variant: 'generic' \| 'tool_failed' \| 'plan_rejected' \| 'unknown_project'`, `message?: string` (for `unknown_project`, the formatted project list), `onRetry`, `onEdit` | Renders the exact copy blocks from §5.6–5.9 keyed by `variant`. Never invents its own copy. |
| `Composer` | `value: string`, `onChange`, `onSend`, `onCancel`, `busy: boolean`, `maxRows: 6` | Drives §4's four states. Enter/Shift+Enter behaviour is desktop-only (see §1.2). |
| `SuggestionChips` | `suggestions: string[]`, `onPick(text: string)` | Empty-state only (§3). Populates composer, does not auto-send. |
| `JumpToBottomPill` | `visible: boolean`, `onClick` | Floating pill, bottom-centre above composer, shown only once user has scrolled up during/after new content. |
| `StatusDot` | `state: 'online' \| 'warn' \| 'offline'`, `label: string` | Reused pattern from the prototype's "lamp" — colour + adjacent text label always together, never colour alone. Used in `TopBar`'s session indicator. |

---

## 8. Accessibility specifics for this screen

- `MessageList` region has `aria-live="polite"` scoped to assistant content only (user's own
  sent messages don't need re-announcing — they typed them).
- `ErrorCard` announcements use `aria-live="assertive"` (a failure is important enough to
  interrupt).
- Sending a message does **not** move focus away from the composer (the textarea keeps focus so
  the user can immediately type the next thing once the current one resolves — even though they
  can't send until `Busy` clears, per §4).
- `TraceDisclosure`'s toggle is a real `<button aria-expanded>`, not a bare `<div onClick>`.
- Cancel and Try-again/Edit-message controls are real `<button>` elements, reachable by Tab,
  minimum 44×44px hit target on touch.
- All copy in §5.6–5.9 is final, shippable text — do not paraphrase at build time.

---

## 9. Explicitly out of scope for this spec

Restated so no one designs-by-inference beyond it:

- Conversation list / history / resuming a past conversation (FR-025, M2).
- Real token-level response streaming (FR-024, M2) — §5.4 documents the seam it will use.
- The login screen itself (mechanism is Architect's call, SRS Q3).
- Any Approval UI (M5) — M1's only tool is pre-configured `ALLOW`, read-only (FR-121); the
  `ASK_USER` path is never exercised in M1, so no approve/reject UI is designed here.
- Dashboard shell, nav rail, Home/Tasks/Agents/Workflows/Projects/Calendar/Notifications/
  Activity-Log/Settings views (all M8) — see `DASHBOARD_DIRECTION.md` for the forward sketch
  only, not a spec.
- Voice (M9), Scheduler (M10).
