# SUNIL V2 Dashboard — Design Decisions

**Author:** UI/UX Designer, Minions Team 21 · **Date:** 2026-09-11 (round 2) · For owner **Gate 2**.
Companion to `V2_DASHBOARD_SPEC.md`. Each decision states what was chosen, why, and the credible
alternative that was rejected — so the owner can overturn any one of them by reading ten lines
rather than the whole spec.

**Round 2 (owner rework):** Decisions 1–9 and 11 survived the owner's Gate-2 review unchanged — the
verdict rejected the skin, not the bones. Decision 10 is **replaced** (dark-only is now the owner's
ruling), and Decisions 12–15 record the new Obsidian & Gold visual language.

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

## 10. Dark-only, committed — the owner's ruling (REPLACED in round 2; supersedes the round-1 light theme)

**Decision.** SUNIL is **dark-only as a brand position**. One theme, painted explicitly: no
`prefers-color-scheme` media query, no toggle, no dormant light map. The round-1 light derivation
(Amendment A §A.2) is deleted, and the palette moves to Obsidian & Gold (Amendment A, round 2).

**Why.** The owner answered Q7 directly at Gate 2: *"Dark mode where it looks and feels like a
futuristic design. I like black and gold."* SUNIL is the owner's personal command-centre — the V1
prototype was a dark HUD and this is that taste, matured. Beyond taste, dark-only halves the visual
QA surface, removes an entire class of contrast re-derivation bugs, and — for a single-user product
— serves exactly one context: the owner's. Committing (rather than defaulting) means every colour is
authored against a known ground; nothing can silently render on a background it was never checked
against.

**Rejected.** *Keeping the light map dormant "in case".* A palette nobody renders is a palette
nobody maintains: it drifts, then one day an OS preference resurrects it broken. If light is ever
wanted, it should be re-derived deliberately from a live decision, not exhumed.

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

---

## 12. A black + gold palette with a spending rule, not a colour scheme

**Decision.** Layered blacks (true-black void `#000000` → `#12100B` → `#1C1913` → `#282318`;
elevation is lightness, never shadow), one saturated gold `#F0B429` for everything interactive plus
at most one key figure per view, a dark ochre `#C9971F` for non-interactive warmth, sand `#A89A7E`
for muted text — and **status hues that never share the brand hue**: pending moves from amber to
orange `#FF9E45`, approved moves from accent to signal blue `#6EA8FE`. Full table + ratios in
Amendment A.

**Why.** Gold only reads as precious if it is scarce; the moment a whole table is gold, the one
button that spends money stops standing out. And with a *yellow* brand, round 1's aliases become
traps: amber PENDING pills would look clickable, gold APPROVED pills would look like chrome. Status
must survive the question "is this the system's voice or the situation's state?" at a glance —
which forces the hue separation. Every pair was computed on its actual ground (worst case 4.8:1,
most pairs 7–18:1).

**Rejected.** *Monochrome gold-on-black HUD (every element a gold intensity).* It is the most
"futuristic" looking option and the least usable one: with one hue, status collapses into
brightness, colour-blind-safe becomes impossible to reason about, and the money screen loses its
red. Instruments are mostly monochrome *until something matters* — which is exactly the status
palette's job.

---

## 13. Space Grotesk + Inter + JetBrains Mono — futurism carried by type geometry, not costume faces

**Decision.** V2 surfaces retire Orbitron and Share Tech Mono. Display = **Space Grotesk**
(squared, technical grotesk; wordmark, view titles, stat figures). Body/UI = **Inter** (all prose,
tables, controls, with `tabular-nums`). Data = **JetBrains Mono** (ids, params, hashes, offsets,
countdowns, JSON — anything machine-shaped).

**Why.** "Futuristic precision instrument" is carried by squared terminals, tight uppercase
micro-labels and columns of tabular figures — not by a sci-fi display face. Orbitron at data sizes
is a costume with a weak lowercase; Share Tech Mono ships one weight and cannot express emphasis.
Inter at 13–14px buys roughly 20% more characters per line than the round-1 mono body — the
cheapest possible answer to "all the info displayed properly". The mono earns its keep by contrast:
when only machine-text is monospaced, provenance becomes visible in the letterforms themselves,
which reinforces the untrusted-text containment.

**Rejected.** *(a) Keeping Orbitron for continuity* — continuity with a skin the owner just
rejected is not a virtue. *(b) An all-mono body (round 1's choice)* — authentic HUD, but it taxes
every sentence to make no distinction, and it spends the width the density mandate needs.

---

## 14. Density: summary rails, both timestamps at rest, and nothing readable behind hover

**Decision.** Every list view opens with a summary rail of 3–5 at-rest figures (pending count,
oldest wait, next expiry, decided-7d, …). Timestamps render relative **and** absolute together
(`18 min ago · 09:41:06`) — the round-1 hover-`<time>` pattern is removed. Audit exception rows
still arrive expanded, and collapsed rows now surface their key figures (offset, duration, tokens)
inline. Hover may add affordance, never reveal content. Normative as Amendment A §A.6.

**Why.** The owner's verdict — "all the info displayed properly" — is a report that round 1 felt
like it hid things. The expensive information in this product is small (counts, deadlines, ids);
what made it feel hidden was that it lived one interaction away (hover, expand, navigate). Hover
reveals also simply do not exist on touch and are invisible to keyboard users, so removing them is
an accessibility repair, not just a density one.

**Rejected.** *Round 1's progressive-disclosure-first calm.* Defensible for a consumer product;
wrong for an operator's console, where the cost of a hidden number is a wrong decision, and the
operator is one known person who asked for the data.

---

## 15. An atmospherics budget: hairlines, corner ticks, one whisper of texture, glow only when armed

**Decision.** Exactly four atmospherics are permitted (Amendment A §A.4): hairline gold rules;
14px corner ticks on the single primary panel per view; a ≤2% scanline texture on the void only;
and the gold glow on precisely two carriers — an **armed** decision control and the **live**
WorkIndicator. Everything at rest is flat, layered black. Parallax, animated backgrounds,
glassmorphism blur and neon gradients are forbidden in writing.

**Why.** The futuristic feel has to survive daily 8am use over a screen where real money moves.
Each permitted item earns its place by carrying meaning: the ticks say "this panel is the
instrument", the texture keeps true black from reading as a dead void, and the glow — because it is
otherwise absent — makes *armed* unmistakable from across the room. An effects budget written down
is the only thing that stops a future contributor from adding "just one more" glow.

**Rejected.** *(a)* Ambient animated background (the V1 prototype's point-sphere) — already
rejected in §0 of the design system for legibility, doubly wrong behind tables. *(b)* Zero
atmospherics (flat dark-grey admin) — safe, cheap, and a failure of the actual brief: the owner
asked for a design with a face.

