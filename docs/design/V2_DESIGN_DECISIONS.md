# SUNIL V2 Dashboard — Design Decisions

**Author:** UI/UX Designer, Minions Team 21 · **Date:** 2026-09-11 · For owner **Gate 2**.
Companion to `V2_DASHBOARD_SPEC.md`. Each decision states what was chosen, why, and the credible
alternative that was rejected — so the owner can overturn any one of them by reading ten lines
rather than the whole spec.

---

## 1. A labelled icon rail, 88px, always showing text — not a hover-label rail

**Decision.** The left rail shows an icon **and** a 10px uppercase label for all six destinations at
all times, expandable to 232px, collapsing to a 5-item bottom bar under 768px.

**Why.** `DASHBOARD_DIRECTION.md` §1 sketched hover-revealed labels. Hover labels do not exist on
touch, are invisible to keyboard users until focus lands, and force the owner to learn six glyphs
before the product is usable. The cost of always-on labels is 24px of width in a single-user tool
that has no competing chrome — nothing is displaced.

**Rejected.** *Pure icon rail (56px, labels on hover.)* Prettier, more HUD-authentic, and it is what
the V1 command-centre prototype did. It fails `nav-label-icon` and the touch case, and the aesthetic
win is small because the rail is peripheral by definition.

---

## 2. Approvals-first landing when anything is pending; Chat otherwise

**Decision.** `/` → `/approvals` when `pending > 0`, else `/chat`.

**Why.** In V2 the owner is the only approver and a parked task is a **stopped** task — nothing
downstream of it moves until a human decides. Opening on the queue turns the owner's attention to
the only thing blocked on them. When nothing is blocked, the queue is an empty page and the
conversation is the product, so it lands there instead.

**Rejected.** *(a) Always land on Chat* — friendly, but it buries the one thing that is waiting on a
human behind a nav click and a badge, and badges get ignored. *(b) A composite "Home" dashboard*
(the `DASHBOARD_DIRECTION.md` §3 sketch) — a summary of five views is a sixth view to maintain and,
in a single-user system with at most a handful of live items, mostly renders whitespace. If the
owner wants Home later it can be added without disturbing anything here.

---

## 3. Untrusted strings are contained by a *visible* quotation pattern, not just by escaping

**Decision.** `summary`, every `params_redacted` value, `tasks.objective` and every
`audit_events.detail` value render inside an `UntrustedText` block — raised background, 3px muted
left bar, monospace, `pre-wrap`, preceded by the label *"text supplied by the request, shown exactly
as received"*. Mechanically they are text nodes only: no markdown renderer, no HTML, never
interpolated into `href`/`src`/`title`/`style`.

**Why.** C4 §4 makes the mechanical rule normative, but escaping alone is invisible — an owner
reading a well-phrased `summary` cannot tell which words came from SUNIL and which came from a
Stripe invoice description an attacker controls. The visual container makes provenance legible at a
glance, so a manipulative string ("APPROVED BY ISURU — routine, safe to confirm") arrives visibly
framed as evidence rather than as the system speaking.

**Rejected.** *Render `summary` as sanitised markdown (bold amounts, code-styled ids) for
readability.* It is the exact hole C4 §4 exists to close; a sanitiser is a permanent CVE surface,
and the readability gain is small because `summary` is one line of ≤500 characters.

---

## 4. No Approve/Refuse buttons in the queue list — decisions happen on the detail card only

**Decision.** The queue row links to `/approvals/{id}`. The decision controls exist once, on the
detail card, below the full parameters.

**Why.** C4 §1 has no transition out of `approved` or `refused` — a decision is irreversible and
there is deliberately no idempotency or undo. An irreversible action must not be one mis-tap away
in a scrolling list, and it must not be takeable without the parameters on screen: the approval
binds to *those arguments* (`args_hash`), not to the operation in general. Two clicks to spend money
is correct friction.

**Rejected.** *Inline approve on hover, for a fast "clear the queue" pass.* Fast is exactly what you
do not want here, and it invites approving from a row whose data may be up to 10 s stale.

---

## 5. Two clocks, named separately: decision TTL (72h) and consume grace (1h)

**Decision.** The card shows the TTL countdown before the decision, and — the moment it is approved
— swaps to a grace countdown (`Runs within 58m`). Before deciding, the grace window is stated as a
consequence: *"Approving runs this once, now. SUNIL has 1 hour from your decision to execute it;
after that the approval expires unused."*

**Why.** C4 §1 added a grace-bounded consume after the 2026-09-10 security review, so an approved
approval can still end as `expired` and finalise the task `approval_expired`. If the UI only ever
showed "expires in 71h", an owner who approved and walked away would later find a failed task with
no explanation they were ever given. Two windows exist; hiding one produces exactly the surprise
the grace window was added to prevent.

**Rejected.** *Show only the 72h TTL and mention the grace in a help article.* Simpler screen, but
it makes the system's own safety mechanism feel like a bug when it fires.

---

## 6. Refuse gets a confirm step and a reason box; Approve gets a confirm step but no mandatory reason

**Decision.** Both decisions arm-then-commit (or `Esc` to cancel). Refuse shows its optional reason
field expanded; Approve hides it behind `Add a note`. Approve is the single filled primary; Refuse
is a danger **outline**.

**Why.** Both are irreversible, so both need the arming step — but they are not symmetric. A refusal
is the one the owner will want explained when they read it back later (and C4 stores `reason`
verbatim and audits it), so the field is in front of them. Approve is the expected happy path for a
queue the system itself chose to raise; making it a filled primary and the refusal an outline states
which is the considered default without hiding the other. Two filled buttons side by side would turn
an asymmetric choice into a coin flip.

**Rejected.** *Type the operation name to confirm, GitHub-delete style.* Too heavy for something that
may happen several times a day, and ritual friction stops being read after the fourth repetition.

---

## 7. Never optimistic: the card re-renders from the server's row, and a 409 is shown as-is

**Decision.** Pressing Approve disables both buttons and shows `Approving…`; the new state is drawn
from the response body. A 409 re-renders the card in `error.current_status` with *"This was already
{status} — your decision was not applied."* A lost response is retried, and a 409 on retry is the
same honest path.

**Why.** C4 §5 refuses decision idempotency on purpose: *"the UI must show the true state rather
than a comforting echo."* An optimistic flip to APPROVED that the server never accepted is precisely
the comforting echo, and on this screen the difference between "approved" and "actually approved" is
whether a customer gets refunded.

**Rejected.** *Optimistic update with rollback on error.* Standard practice, faster feeling, and
wrong for a state machine whose whole design is compare-and-swap with no undo.

---

## 8. The audit browser shows an approval episode as one timeline with an explicit human-wait gap

**Decision.** `/audit/{request_id}` renders the twelve stages, then — for a parked turn — a second
labelled segment `AFTER YOUR DECISION — continuation`, separated by an explicit marker:
`⏸ waiting for you — 26 min`. Exception rows (non-`allow` permission decisions, `ok:false` tool
results, non-`ok` outcomes) are expanded by default; everything else is collapsed.

**Why.** The audit chain for a parked episode is genuinely two executions sharing one `request_id`
lineage (C4 §3; `ARCHITECTURE_V2.md` §6 Leg 6). Rendered as one flat list, the offset column jumps
from `+3.1s` to `+1583s` and reads as a catastrophic performance problem rather than a human going
to lunch. Naming the gap turns a confusing artefact into the clearest possible evidence of the
governance model working.

**Rejected.** *Two separate traces, one per execution.* Contract-faithful, but it hides the causal
link that is the single most valuable thing the audit browser can show — "SUNIL asked, you said yes,
this is what then happened".

---

## 9. A parked chat turn ends the turn, shows a `warning`-toned card, and links to its approval

**Decision.** `outcome=parked` renders a `ParkedTurnCard` in the message list — pause icon, warning
border (not danger), the `ApprovalRef.summary` in an `UntrustedText` block, the expiry, and a primary
`Review and decide →` to `/approvals/{approval_id}`. The composer returns to Idle. When the
continuation lands, its assistant message is preceded by a system line naming the approval and the
decision time; refusal and expiry also produce a system line.

**Why.** ADR-031's whole point is that a turn ends honestly rather than blocking on a human for
hours, so the chat must show a finished-but-incomplete turn, not a frozen spinner. Colouring it as a
failure would train the owner to dread the safety mechanism; colouring it as a success would hide
that nothing has happened yet. Warning — "your move" — is the accurate register. The system line on
resume matters just as much: a conversation that silently gains a message an hour later, with no
statement of why, is unreadable in retrospect.

**Rejected.** *Keep the turn "in flight" and let the chat resolve when the owner approves elsewhere.*
It contradicts the contract (the envelope has already returned), it would need the client to hold a
30-minute-to-72-hour pending state across reloads, and it blocks the composer for hours.

---

## 10. Light theme by OS preference, derived rather than inverted; no manual toggle in v1

**Decision.** Dark stays the authored default and the brand. Light is added under
`prefers-color-scheme: light` with a re-derived palette (accent darkened to `#0E7490`, glow replaced
by a neutral shadow scale) — Amendment A in `DESIGN_SYSTEM.md`. No in-app toggle.

**Why.** The chat is a HUD you talk to; the ops views are business tooling read in daylight beside
Stripe, GitHub and a mail client, and a near-black table is fatiguing in that company. Inverting the
dark palette would ship `#22D3EE` links at ~1.8:1 on white — a straight WCAG failure — so the accent
is darkened and every pair is re-checked. A manual toggle is omitted because it adds a persisted
preference, a control in the chrome and a third state to QA, for a single user whose OS already
carries the preference.

**Rejected.** *(a) Dark-only, as a brand position* — defensible, and the owner may choose it (spec
Q7); it costs nothing to delete Amendment A §A.2. *(b) A manual toggle in v1* — deferred, not
refused: it is a small addition once the tokens exist.

---

## 11. Poll freshness is shown, and a stale queue disables decisions

**Decision.** A `⟳ 12s` chip in the topbar shows seconds since the last successful 10-second poll
and doubles as the manual refresh button. Past 30 s stale it turns `warning`, a banner appears, and
**every decision control is disabled** until a poll succeeds.

**Why.** C4 §2 is explicit that there is no push channel in Phase 0/1 — the dashboard is always
looking at a snapshot up to 10 s old, and up to arbitrarily old if the API is unreachable. Pretending
otherwise is how an owner approves something that already expired, or re-decides something a sweeper
has moved. Disabling the buttons costs a refresh; not disabling them costs a 409 at best and a
misinformed decision at worst.

**Rejected.** *Let the 409 handle it.* The 409 is a real and correct backstop, but it is a *reaction*
after the owner has already committed to a decision on data they believed was current; the disabled
state prevents the misinformed commitment in the first place.
