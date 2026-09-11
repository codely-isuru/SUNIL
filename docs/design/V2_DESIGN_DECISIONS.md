# SUNIL V2 Dashboard — Design Decisions

**Author:** UI/UX Designer, Minions Team 21 · **Date:** 2026-09-11 (round 2) · For owner **Gate 2**.
Companion to `V2_DASHBOARD_SPEC.md`. Each decision states what was chosen, why, and the credible
alternative that was rejected — so the owner can overturn any one of them by reading ten lines
rather than the whole spec.

**Round 2 (owner rework):** Decisions 1–9 and 11 survived the owner's Gate-2 review unchanged — the
verdict rejected the skin, not the bones. Decision 10 is **replaced** (dark-only is now the owner's
ruling), and Decisions 12–15 record the new Obsidian & Gold visual language.

**Round 3 (owner comfort/effects rework, 2026-09-11):** the owner reviewed the round-2 mockups:
*"the contrast are bit high on these designs its hard to keep on the eye for a long time. make it
so it got a cool effects. remove yellow keep black and gold colors."* Decisions 12 and 15 are
**amended** (de-yellowed ramp + comfort ceiling; expanded atmospherics), and Decision 16 is added
(the micro-animation grammar the "cool effects" ruling required). Everything else stands.

**Round 4 (owner addition, 2026-09-11):** the owner reviewed round 3 and asked for one thing —
a unified Dashboard as the landing view. Decision 2 is **amended** (owner override of the
"no composite Home" ruling; answers Q6), and Decision 17 is added (the expand-vs-navigate dual
affordance the request named). Tokens, effects and everything else stand unchanged.

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

## 2. The landing is a unified Dashboard — AMENDED round 4: OWNER OVERRIDE of this decision's own rejection

**Decision (as amended).** `/` **is** a composite Dashboard (spec §16, mockup `00-dashboard.html`):
every main component at summary tier in one view — pending approvals as the corner-ticked hero
(count + top rows + countdowns), agent activity, tasks, projects, recent audit, and a chat
quick-entry. First item in the rail. The round-1 conditional redirect (`/approvals` when pending,
else `/chat`) is retired.

**Why (round-4 driver, owner verbatim):** *"Can we have all these main components in a dashboard?
… I wanna see all the info in one place too."* This is exactly the composite Home this decision
originally rejected — the owner has overruled that rejection, and answered Q6 with it. The original
reasoning's *intent* survives intact: the thing blocked on the owner is still the first thing seen,
because pending approvals are the Dashboard's hero and only gold figure.

**How the feared maintenance cost is contained.** Round 1 rejected Home as "a sixth view to
maintain [that] mostly renders whitespace". The spec closes both prongs: (a) the Dashboard is
**composed from the five views' own components and queries at summary tier** — same `StatusPill`,
same compact `UntrustedText`, same §13 endpoints with a `limit` — and is forbidden (spec §16.1)
from growing any field its full view lacks, so there is no bespoke sixth data model to drift;
(b) the whitespace concern is answered by Amendment A §A.6's at-rest-figures rule — even collapsed,
every box states its numbers, and the all-quiet state is designed rather than blank.

**Rejected.** *(a) Always land on Chat* — still rejected, same reason as round 1. *(b) Keeping the
conditional redirect and adding Dashboard as a non-landing seventh view* — defies the request's
plain meaning ("add that dashboard too… see all the info in one place" is a description of the
place you arrive), and a dashboard nobody lands on is a dashboard nobody maintains.

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

## 12. A black + gold palette with a spending rule, not a colour scheme — AMENDED round 3: de-yellowed, and bounded by a comfort ceiling

**Decision (as amended).** Layered warm blacks (`#0B0906` → `#16120C` → `#201A11` → `#2B2315`;
elevation is lightness, never shadow — the canvas is deliberately lifted off pure `#000000`), one
**antique/metallic gold** `#C9A227` for everything interactive plus at most one key figure per
view (hover `#DBBE7F` pale champagne, pressed `#A6801F` bronze), dark antique gold `#B08A2A` for
non-interactive warmth, sand `#9A8D71` for muted text — and **status hues that never share the
brand hue**: pending is **copper** `#D98E4A`, approved is signal blue `#5E96E0`, consumed green
`#3FAE6C`, refused red `#E8685C`. Contrast is now governed **on both sides**: AA 4.5:1 floor
everywhere, **and a comfort ceiling** — sustained-reading text lands 9–13:1 (body `#CEC5B4`,
11.6:1 on canvas), never above 13.5:1. Full table + ratios in Amendment A §A.7.

**Why (round-3 driver, owner verbatim):** *"the contrast are bit high on these designs its hard to
keep on the eye for a long time … remove yellow keep black and gold colors."* Two distinct reports:
(a) round 2's 18.3:1 body text was clinically bright — correct by WCAG, wrong for an 8-hours-a-day
operator console, so maximum contrast is now treated as a defect, not a virtue; (b) `#F0B429` and
the orange pending `#FF9E45` read *yellow*, not *gold*. Real gold is a low-saturation, mid-lightness
metal — the ramp now behaves like metal (champagne when light hits it, bronze when pressed).
Pending's copper sits at hue ≈28° with visible red content against the gold's ≈46°; the named
distinction rule — **gold is the system's voice, copper is a situation's state, and status colour
only ever appears in the pill/edge grammar with icon + label** — keeps them unmistakable at a
glance. Round 2's hue-separation logic and gold-spending rules survive unchanged.

**Rejected (round 3).** *(a) Keeping the ratios and just darkening the gold* — halves the fix; the
eye-strain complaint was about the text/ground contrast, not only the accent. *(b) Dimming body
text below 9:1 for an even softer image* — drifts toward the gray-on-gray dashboards this product
exists to not be, and squeezes muted text against the AA floor on the lightest ground.
**Rejected (round 2, still standing).** *Monochrome gold-on-black HUD (every element a gold
intensity).* With one hue, status collapses into brightness, colour-blind-safe becomes impossible
to reason about, and the money screen loses its red.

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

## 15. An atmospherics budget — AMENDED round 3: the budget is raised, and it is still a budget

**Decision (as amended).** The owner asked for *"cool effects"*; the budget grows from four items
to eight, each still named in writing (Amendment A §A.4): hairline gold rules; corner ticks on the
one primary panel per view; the ≤1.5% scanline texture on the void only; **a barely-there panel
sheen** (≤3% gold top-gradient on panels/cards/tables — never on untrusted blocks or chat message
bodies); **a metallic gradient on gold button fills** (light top edge, weighted base — CSS only,
ink AA-verified at every stop); **a faint text-glow on the single key figure per view**; the gold
glow on the two state carriers (armed control, live WorkIndicator — **pulse slowed from 1100ms to
2600ms**, calm breathing instead of urgency); and **one shimmer sweep on the armed confirm button
only**. Every animation dies under `prefers-reduced-motion` and none sits on a reading surface.
Parallax, animated backgrounds, glassmorphism blur and neon gradients stay forbidden in writing.

**Why.** Round 2 bought legibility with near-total flatness, and the owner's verdict says it
undershot the brief's *feel*. The added items are all material, not decoration: the sheens make
black surfaces read as brushed metal (which is what "black and gold" wants to be), the key-figure
glow spends light on the number the view exists for, and the shimmer marks the one control whose
next press is irreversible as live. Meaning-carrying effects survive daily 8am use; decorative ones
do not — which is why the list is still enumerated and closed, not "tasteful effects allowed".

**Rejected.** *(a)* Ambient animated background (the V1 point-sphere) — still rejected; it is the
one "cool effect" that provably costs reading. *(b)* Glassmorphism blur panels — the most-requested
"futuristic" look of this era, and wrong here twice: blur behind an approval card makes untrusted
text harder to inspect, and backdrop-filter is the single most expensive paint on a 10s-polling
page. *(c)* Round 2's near-zero budget — rejected by the owner in so many words.

---

## 16. Motion means liveness, and only liveness — one clock (2600ms), two moving elements, zero on reading surfaces (NEW in round 3)

**Decision.** The expanded effects budget needed a grammar before it needed CSS, so it is one rule:
**a thing may animate if and only if it is claiming "this is live right now", and every such
animation shares one clock.** Exactly two elements move: the live WorkIndicator (breathing glow)
and the armed confirm button (shimmer sweep) — both on a 2600ms cycle with the system's single
easing curve (`cubic-bezier(.4,0,.2,1)`), both reduced to a static glow border under
`prefers-reduced-motion`, and neither anywhere near body text. Everything else on every view is
still. Hover/press feedback stays in the 150–250ms transition family from §6 — transitions are
responses, not animations, and are exempt from the two-element cap.

**Why.** "Cool effects" fails in exactly one way: accumulation. Three independent pulse rates on
one screen read as noise; two elements sharing one slow clock read as a machine idling — which is
the futurism the owner is asking for. Tying motion to liveness also makes it *honest*: the stale
state (Decision 11) already freezes the pulse because a glow may only claim liveness that is real,
and the shimmer exists precisely because the armed control is the one place where "live right now"
is a safety-relevant fact. The single clock is also the cheap-to-enforce version of the rule: any
future animation proposal must either join the 2600ms clock and name what liveness it signals, or
it is decoration and is refused.

**Rejected.** *(a) Per-effect bespoke timings* (a 1100ms pulse + an 1800ms shimmer + 3s ambient
drift) — each defensible alone, unarguably restless together; rhythm is a system property, not a
component property. *(b) Entrance animations on rows/cards* (stagger-in on poll refresh) — this
dashboard re-renders from a 10-second poll; animating arrival would make routine data refresh look
like events, twelve times a minute. *(c) An animated topbar poll-countdown ring* — a permanently
moving element in the periphery is exactly the fatigue the round-3 verdict complains about.

---

## 17. Dashboard sections expand in place with native `<details>` AND carry an explicit "Open full view →" link (NEW in round 4)

**Decision.** Every Dashboard section is a native `<details>` box: clicking the box (its
`<summary>`) expands it in place to the section's fuller list; a real `<a>` labelled
`Open full view →` sits in the same summary row and navigates to the section's page. Both
affordances always present, no JavaScript. Per render, the approvals hero ships `open` and every
other box ships closed; expansion state is never persisted and never fetches — the summary payload
already contains the ≤5 detail rows.

**Why.** The owner named both behaviours in one sentence — *"once I click the box it expands or
redirects to the page"* — and they are genuinely different intents (glance deeper vs. go work
there), so the design gives each its own control rather than guessing which the click meant.
Native `<details>/<summary>` makes the expansion honest in a static mockup and cheap in the build:
keyboard operability and the expanded/collapsed announcement come from the browser, the same
pattern the audit browser's stage rows already use (one grammar for "this opens in place" across
the product). A link inside a `<summary>` follows the link without toggling the box, so the dual
affordance needs no event plumbing. Shipping the hero pre-expanded means the at-rest landing frame
itself teaches the mechanism — the owner sees one box open and four closed and infers the rest.

**Rejected.** *(a) Hover previews* (peek a section's rows on hover) — nothing readable may live
behind hover (Amendment A §A.6, Decision 14); it does not exist on touch and is invisible to
keyboard users. *(b) Modal drill-ins* (the box opens a dialog over the dashboard) — a modal is a
dead end that hides the other sections, duplicates the full view's layout at a second size, and
breaks deep-linking; the full views already exist and are one honest link away. *(c) Making the
whole box a navigation card and dropping in-place expansion* — simpler, but it discards half of
what the owner asked for by name.

