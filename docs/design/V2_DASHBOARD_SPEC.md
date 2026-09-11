# SUNIL V2 — Ops Dashboard Specification (Stream D)

**Author:** UI/UX Designer, Minions Team 21 · **Date:** 2026-09-11 · **Branch:** `task/P0-ui-design`
**Status:** For owner **Gate 2 design review**. Nothing here is built yet. Stream D implements this
document; it is the reference, not the code.
**Design language:** `DESIGN_SYSTEM.md` is binding. This spec **names** tokens, it does not
redefine them. V2's visual language is **Amendment A** ("Obsidian & Gold", rounds 2–3 — replaced
wholesale after the owner's Gate-2 verdict, then comfort-tuned and de-yellowed after the owner's
round-3 verdict): dark-only black + antique gold, a contrast comfort ceiling alongside the AA
floor, status semantics for the five-state approval lifecycle, density rules, and the Space
Grotesk / Inter / JetBrains Mono type system. Token *names* are unchanged, so every reference
below still resolves; "accent" means the antique gold `#C9A227`.
**Contracts consumed:** `contracts/C4-approvals.md` + `C4-approvals-openapi.yaml` (approvals),
`contracts/C5-chat.md` + `C5-chat-openapi.yaml` (chat envelope, `outcome=parked`, trace stages).
**Scope source:** `V2_DEVELOPMENT_PLAN.md` Stream D — "approvals queue, agent activity, tasks,
projects, audit browser" + the existing chat. `ARCHITECTURE_V2.md` §2 (`apps/web/`), §6 (L-001).
**Predecessors honoured:** `M1_CHAT_SPEC.md` (the chat view is that spec, re-hosted, plus one new
state); `DASHBOARD_DIRECTION.md` (icon rail, chrome-agnostic chat components, trace view lineage).
**Mockups:** `mockups/00…06.html` — static, self-contained, **single committed dark theme**
(Obsidian & Gold, Amendment A round 3 — no `prefers-color-scheme` query, every colour painted),
realistic data. **Round 4 (owner, 2026-09-11)** adds `00-dashboard.html` — a unified Dashboard as
the landing view (§16), overriding Decision 2 and answering Q6. No token changes; Amendment A is
untouched this round.

---

## 0. Read this first — three things that decide the build

1. **Two of the five ops views have no API to read from.** C1–C5 froze tool, provider, memory,
   approvals and chat. `ARCHITECTURE_V2.md` §2 lists `api/routes/{auth,health,chat,approvals,
   conversations,projects}.py` — there is **no tasks route and no audit route**, yet Stream D's
   exit criteria name a tasks view and an audit browser that "reads `audit_events`". §9 and §10 of
   this spec each end with the **minimum read-only endpoint** that view needs, written as a
   request/response shape the Architect can freeze in an hour. This is Open Question **Q1** and it
   is the only thing that can stop Stream D dead.
2. **The approval card is a security surface, not a card.** C4 §4 is normative: `summary` and every
   `params_redacted` value embed attacker-influenceable strings and must render as **plain text
   only**. §6 of this spec turns that rule into visual design — a contained, provenance-labelled
   block that *looks* like quoted evidence rather than like SUNIL talking. Mockup
   `02-approval-card.html` carries a deliberately hostile example string so the reviewer can see
   the containment working.
3. **No optimistic UI anywhere a decision is involved.** C4 §5 refuses decision idempotency on
   purpose: "the UI must show the true state rather than a comforting echo". Approve/Refuse
   therefore render a pending-request state and then the **server's** returned row, and a 409
   re-renders the card in the status the server reports. This is specified in §6.7 and is not a
   detail an engineer may optimise away.

---

## 1. Information architecture

### 1.1 The one-line model

> SUNIL is one assistant with two ways of being used: **you talk to it** (Chat), and **you watch
> and govern it** (the ops views). The shell must never make those feel like two products.

### 1.2 Nav model — a labelled icon rail, approvals-first

`DASHBOARD_DIRECTION.md` §1 proposed a narrow icon rail with labels on hover. Hover-only labels
fail `nav-label-icon` (discoverability) and are unreachable on touch. **Resolution:** the rail is
**88px** wide and always shows an icon **with** a 10px `Micro/badge` label beneath it (mono-ui,
uppercase, `text-muted`; `text-secondary` when active). An expand control widens it to **232px**
with the labels set beside the icons, persisted in `localStorage`. Both widths are label-bearing;
neither is icon-only. Rationale recorded as Decision 1 in `V2_DESIGN_DECISIONS.md`.

| Order | Destination | Route | Icon (Lucide) | Badge |
|---|---|---|---|---|
| 1 | **Dashboard** *(round 4)* | `/` | `layout-dashboard` | — (label "Home" at the 88px width; "Dashboard" expanded) |
| 2 | **Chat** | `/chat`, `/chat/{conversation_id}` | `message-square` | — |
| 3 | **Approvals** | `/approvals`, `/approvals/{approval_id}` | `shield-check` | count of `status=pending` (see §1.5) |
| 4 | **Activity** | `/activity` | `activity` | — (live dot when ≥1 task is running) |
| 5 | **Tasks** | `/tasks`, `/tasks/{task_id}` | `list-checks` | — |
| 6 | **Projects** | `/projects`, `/projects/{key}` | `folder-git-2` | — |
| 7 | **Audit** | `/audit`, `/audit/{request_id}` | `file-search` | — |
| — | *(spacer — pushes the group below to the rail's bottom)* | | | |
| 8 | **Settings** | `/settings` | `settings` | — |
| 9 | **Sign out** | action, not a route | `log-out` | — |

Sign-out is spatially separated from the six destinations by the spacer
(`destructive-nav-separation`) and is a `<button>`, not a nav link. Settings is a stub in this
spec — not designed, listed so the rail's final shape is not a surprise later.

**Landing route — REPLACED round 4 (owner override; answers Q6).** `/` **is** the Dashboard (§16):
one composite view showing every main component at summary tier, with in-place expansion and a link
to each full view. The previous conditional redirect (`/approvals` when pending, else `/chat` —
round-1 Decision 2) is retired; the pending-approvals hero at the top of the Dashboard preserves
that decision's intent (the blocked thing is still the first thing seen). Decision 2 as amended.

### 1.3 Shell regions and focus order

```
┌─────┬──────────────────────────────────────────────────────────────────────┐
│  S  │  Approvals ▸ apr-01JQ…            ● SUNIL online      3 pending  ⟳12s│  ← topbar 56px
│─────├──────────────────────────────────────────────────────────────────────┤
│ 💬  │                                                                        │
│ ✔   │                          view content                                  │
│ ∿   │                     (max-w-6xl, centred, px-8)                         │
│ ☑   │                                                                        │
│ ⌸   │                                                                        │
│ ⌕   │                                                                        │
│     │                                                                        │
│ ⚙   │                                                                        │
│ ⏻   │                                                                        │
└─────┴──────────────────────────────────────────────────────────────────────┘
```

Topbar (56px, `surface`, bottom `border`): left = wordmark **S.U.N.I.L** (`font-display`, H2 scale)
then the breadcrumb for the active view; right = session `StatusDot` (M1 component, unchanged),
the pending-approvals count as a text+icon chip, and the poll freshness indicator (§1.5).

**Tab order (normative):** skip-link → rail items 1–6 → Settings → Sign out → topbar controls →
view heading → view filters/toolbar → main content → pagination. A `Skip to main content` link is
the first focusable element on every page and moves focus to the `<main id="main">` heading.

**Focus on route change:** after client-side navigation, focus moves to the `<h1>` of the new view
(`tabindex="-1"`), and the view name is announced in a polite live region. Without this, a keyboard
user who activates a rail item has focus left behind in the rail with no idea the page changed.

### 1.4 Responsive

| Breakpoint | Shell |
|---|---|
| ≥1280px | Rail (88 or 232px) + content `max-w-6xl` centred, `px-8`. Detail views may use a 2-column split (list 40% / detail 60%) — Approvals only. |
| 1024–1279px | Same, split view collapses to list **or** detail (route-driven, `/approvals` vs `/approvals/{id}`). |
| 768–1023px | Rail collapses to 64px icon+label (label wraps to 9px), content `px-6`. Tables drop their lowest-priority columns (§4.3). |
| <768px | Rail becomes a **bottom bar with 5 items** — Home (Dashboard), Chat, Approvals, Activity, More (Tasks/Projects/Audit/Settings in an overflow sheet). `bottom-nav-limit` honoured. Content `px-4`. Tables become stacked cards (§4.4). Safe-area insets respected top and bottom. On the Dashboard the two-column secondary grid stacks to one column (§16.2). |

The dashboard's primary device is a desktop browser (`ARCHITECTURE_V2.md` §4 TB1 — the browser at
`localhost:3001`), but the approval decision is the one action the owner will want to take from a
phone. Mobile parity is therefore **required for Approvals** and best-effort for the other views.

### 1.5 Polling, freshness, and the badge

C4 §2 fixes the mechanism: **`GET /api/v1/approvals?status=pending` every 10 s. There is no push
channel in Phase 0/1.** The UI must be honest that its data is a snapshot.

- A `⟳ 12s` freshness chip sits in the topbar: seconds since the last **successful** poll, plus a
  manual refresh button (same control — clicking re-polls immediately and resets the counter).
- Between 10–30 s stale: chip stays `text-muted`. Over 30 s (i.e. a poll has failed): the chip
  turns `warning`, gains the `alert-triangle` icon and the text `stale 41s`, and a non-blocking
  banner appears above the view: *"Can't reach SUNIL — showing data from 10:41 am."* The list keeps
  rendering the last good data (do not blank it) but every decision button is **disabled** with the
  tooltip/`aria-describedby` text *"Reconnect before deciding — this list may be out of date."*
  Deciding from a stale queue is exactly how an owner approves something they already refused.
- The rail badge shows the pending count from the same poll, capped at `99+`, with
  `aria-label="Approvals, {n} pending"`. It clears only because the server says so, never locally.
- Polling pauses when the document is hidden and resumes with an immediate poll on `visibilitychange`.

---

## 2. Component inventory (keyed to `DESIGN_SYSTEM.md`)

Reused from M1 unchanged: `StatusDot`, `AssistantMessage`, `MessageBubble`, `Composer`,
`WorkIndicator`, `ErrorCard`, `TraceDisclosure`, `JumpToBottomPill`, `SuggestionChips`.

New for V2. "Tokens" names the `DESIGN_SYSTEM.md` tokens the component is built from; `[A]` marks a
token introduced by Amendment A.

| Component | Purpose | Tokens | Notes |
|---|---|---|---|
| `AppShell` | Rail + topbar + `<main>` | `surface`, `border`, `canvas` | Owns skip-link, focus-on-route-change, live regions |
| `NavRail` / `NavBottomBar` | §1.2 | `surface`, `text-muted`/`text-secondary`, `radius-md`, `surface-raised` (active ground) | Active item: 2px left bar `accent` (gold) + `text-secondary` label + `aria-current="page"`. **No glow at rest** — glow is reserved for armed/live elements (Amendment A §A.4) |
| `PollFreshness` | §1.5 | `text-muted`, `warning`, `micro` | Button + status text, `aria-live="polite"` on the stale transition only |
| `StatusPill` | Approval/task/stage status | `status-*` `[A]`, `radius-full`, `micro` | **Icon + uppercase label + colour**, never colour alone (§12.3) |
| `DataTable` | Queue/tasks/audit lists | `surface`, `surface-raised` (hover/zebra), `border`, `small` | Sortable headers carry `aria-sort`; row = link, not a click handler on a div |
| `ListCard` | Mobile row form of `DataTable` | as above, `radius-md`, `p-4` | ≥44px targets |
| `FilterBar` | Status/project/date filters | `surface-raised`, `radius-md`, `accent` (active) | Filters are URL query params (deep-linkable, back-restorable) |
| `EmptyState` | Zero rows | `text-secondary` (line 1), `text-muted` (line 2), `accent` (action) | Always: what's missing, why that's normal, one action |
| `SkeletonRow` | Loading | `surface-raised`, `radius-sm` | Shimmer only when motion allowed; static block otherwise |
| `ErrorPanel` | Fetch failure | `danger`, `border` | Cause + retry, never a bare "Error" |
| `ApprovalCard` | §6 — the money screen | `surface`, `warning`/`accent`/`success`/`danger` `[A]`, `radius-lg`, `elev-2` | Contains `UntrustedText`, `ParamsTable`, `ExpiryMeter`, `DecisionBar` |
| `UntrustedText` | Plain-text containment | `surface-raised`, `border`, `font-mono-body`, `text-primary` | §6.3. Renders `textContent` only. Never a markdown or HTML renderer |
| `ParamsTable` | `params_redacted` | `surface-raised`, `border`, `code` scale | Each value is an `UntrustedText`; redacted values get the `redacted` `[A]` treatment |
| `ExpiryMeter` | Time remaining | `warning`, `danger`, `micro` | Text first, bar second; never a bar alone (§6.5) |
| `DecisionBar` | Approve / Refuse | `accent` (approve fill), `danger-strong` (refuse), `radius-md` | §6.6–6.7. Refuse opens a confirm step; Approve does not (see Decision 6) |
| `TraceTimeline` | 12-stage trace | `border`, `accent`, `text-muted`, `code` | Shared by the audit browser and chat's `TraceDisclosure` |
| `StageRow` | One `audit_events` row | `surface`, `surface-raised` (expanded), `border` | Native `<details>`; `detail` JSON shown in a `<pre>` with plain-text rules |
| `AgentActivityCard` | One in-flight task | `surface`, `elev-2` + `animate-work-pulse` | The M1 `WorkIndicator` visual family, one per running task |
| `ProjectCard` | One configured project | `surface`, `radius-md`, `border-accent` | |
| `ParkedTurnCard` | Chat's `outcome=parked` | `warning` border, `surface`, `radius-md` | §11.2 — the link from a conversation to its approval |

### 2.1 The four states — the rule, not a suggestion

Every view in this spec specifies **loading, empty, error and populated**, and every list also
specifies **stale** (§1.5). A view that ships without all five is incomplete, not "mostly done".

| State | Trigger | Pattern |
|---|---|---|
| Loading (first paint) | No cached data for this route | 5 `SkeletonRow`s at the real row height (no layout shift when data lands), `aria-busy="true"` on the region. Never a centred spinner for a list |
| Loading (refresh) | A poll/refetch with data already on screen | Do **not** skeleton. Keep the data, animate only the `PollFreshness` chip |
| Empty | 200 OK, zero rows | `EmptyState`: headline, one explanatory line, one action. Never "No data" alone |
| Error | Non-2xx, or network failure with no cached data | `ErrorPanel`: what failed, what the owner can do, `Try again` (re-runs the exact request). 401 → route to sign-in with a return URL. 403 (`forbidden_client`) → "This browser session isn't trusted; sign in again" |
| Populated | ≥1 row | The view |

---

## 3. Colour, type and density in an ops context

- **Spacing density.** Chat is spacious (`max-w-3xl`, `gap-4`). Ops views are dense: table rows `py-2.5`
  (44px effective target on touch via padding, not by shrinking), section gap `gap-6`, card padding
  `p-4`/`p-6`. This is the deliberate spacing-scale split — one product, two densities, matching how
  the surfaces are used.
- **Type.** `font-body` (Inter) for all UI text, tables and prose; `font-mono` (JetBrains Mono)
  for everything machine-shaped — ids, hashes, params, offsets, countdowns, JSON; `font-display`
  (Space Grotesk) for the wordmark, view headings and summary-rail figures. Amendment A §A.5 carries
  the full scale and the rationale (Orbitron and Share Tech Mono are retired from V2 surfaces).
  **All numeric columns and every countdown use tabular figures**
  (`font-variant-numeric: tabular-nums`) so a ticking timer does not reflow its row — now
  load-bearing, since Inter is proportional by default.
- **Theme.** **Dark-only, committed** (owner's Gate-2 ruling; Decision 10 round 2). One painted
  theme — layered blacks, rationed gold, hue-separated status colours — no
  `prefers-color-scheme` query, no toggle, no light map. Elevation is surface lightness, never
  shadow; gold glow appears only on an armed decision control and the live WorkIndicator
  (Amendment A §A.1/§A.4).
- **Density (Amendment A §A.6, from the owner's "all the info displayed properly").** Every list
  view opens with a **summary rail** of 3–5 at-rest figures. Timestamps show relative *and*
  absolute together — never absolute behind hover. Nothing meant to be read hides behind hover;
  hover adds affordance only. Collapsed audit rows surface their key figures inline.

---

## 4. Shared list mechanics (applies to §5, §9, §10)

### 4.1 Pagination
C4's list endpoint is cursor-paged (`limit` ≤200 default 50, opaque `cursor`, `next_cursor: null`
on the last page). The UI therefore uses **"Load more"**, not numbered pages — a cursor API cannot
answer "page 7 of 12" and inventing that control would force the API to change. Button label:
`Load 50 more`; when `next_cursor` is null it is replaced by the muted line
`End of list — 137 shown`.

### 4.2 Sorting
Server order is `created_at desc, id desc` (C4 §6.5). Columns are **not** client-sortable across
pages (sorting a partial page lies). The only sort control is a single toggle `Newest first /
Oldest first`, which is a query param the server honours — flagged in Q1 as a required parameter if
it does not exist.

### 4.3 Column priority (drop order as width shrinks)
Each table declares a priority; columns drop from the lowest priority up, never wrapping into a
horizontal scroll (`horizontal-scroll` is banned).

### 4.4 Row → card at <768px
Every table has a defined card form: line 1 = the identity (status pill + tool.operation), line 2 =
the summary (2-line clamp), line 3 = meta (agent · time · expiry). The whole card is one link with
a ≥44px target; actions live inside the detail view, not on the card, so a mis-tap can never decide
an approval.

---

## 5. View — Approvals queue (`/approvals`) · mockup `01-approvals-queue.html`

The default landing view when anything is pending. Source: `GET /api/v1/approvals`
(`status`, `limit`, `cursor`), polled per §1.5.

### 5.1 Layout
Heading `Approvals` (H1) + subhead `{n} waiting for you · {m} decided in the last 7 days`.
`FilterBar`: status segmented control `Pending | Approved | Refused | Expired | Consumed | All`
(default `Pending`, reflected in `?status=`), plus an agent filter and a tool filter (client-side
over the loaded page only — labelled as such: `filtering the {n} loaded`).
Then the `DataTable`, then pagination (§4.1).

### 5.2 Columns → contract fields

| # | Column | Field (C4 `Approval`) | Rendering | Priority |
|---|---|---|---|---|
| 1 | Status | `status` | `StatusPill` — icon + uppercase text + colour (§12.3) | P1 |
| 2 | Action | `tool` + `.` + `operation` | `code` scale, `text-primary`. **Trusted** (registry values, `config/tools.yaml`) — may be styled as an identifier | P1 |
| 3 | What it does | `summary` | `UntrustedText`, single line, `text-overflow: ellipsis`, full value in the detail view — **never** a `title` tooltip built by string concatenation | P1 |
| 4 | Agent | `agent_id` | Display name from the agents registry if present, else the raw key in `code` style | P2 |
| 5 | Requested | `created_at` | Relative (`14 min ago`) with the absolute ISO value in `<time datetime>` and visible on hover/focus | P2 |
| 6 | Expires | `expires_at` | `ExpiryMeter` compact: `in 71h 46m`, `warning` under 12h, `danger` under 1h, `EXPIRED` after | P1 (pending rows) / P3 (decided rows) |
| 7 | Decided | `decided_at`, `decided_by` | `10:07 am by owner` — blank for pending | P3 |
| 8 | Task | `task_id` | Link to `/tasks/{task_id}` | P4 |

Row click → `/approvals/{id}` (§6). **How that is implemented matters:** an `<a>` cannot wrap
`<tr>`/`<td>`, and one link per cell would give a single row five focus stops. So each row has
**exactly one** primary link, in the Action cell, whose accessible name carries the whole row
(`aria-label="Pending — stripe_mcp.refunds.create — refund AUD 240.00 … — review and decide"`).
The Task cell's link is the row's only other focus stop. Mouse users additionally get a row-level
click (an `onClick` on the `<tr>` that navigates to the same href) purely as a convenience — the
keyboard and assistive-technology path is always the real anchor, never the row handler, and the
row handler must ignore clicks that originate on the Task link.

**No Approve/Refuse buttons in the list.** A decision is irreversible (C4 §1: no transition out of
`approved`/`refused`), so it may only be made on a screen that shows the full params. Decision 4.

### 5.3 States

| State | Content |
|---|---|
| Loading | 5 `SkeletonRow`s at 52px |
| Empty (`status=pending`) | Headline **"Nothing needs your approval."** · line 2: *"SUNIL parks a task here whenever a plan reaches an action it isn't allowed to take on its own."* · action `View decided approvals` (`?status=all`) |
| Empty (filtered) | **"No {status} approvals."** · action `Clear filters` |
| Error | `ErrorPanel`: *"Couldn't load the approvals queue."* + the HTTP kind from `error.kind` in plain words + `Try again` |
| Stale | §1.5 banner; rows dimmed to 85% opacity; the detail view's decision buttons disabled |
| Populated | Pending rows first regardless of filter when `status=all` (server order otherwise) |

### 5.4 Priority signalling without a priority field
C4 has no risk/priority field, so the queue must not invent one. What it *can* signal honestly is
**time pressure** (from `expires_at`) — rows under 12h remaining carry the `warning` expiry
treatment, and under 1h the row's left edge takes a 2px `danger` bar plus the `EXPIRING` pill
suffix. This is derived data, not an invented attribute. Q4 asks whether the owner wants a real
risk classification added to C4 later.

---

## 6. View — Approval detail (`/approvals/{approval_id}`) · mockup `02-approval-card.html`

**The money screen.** Source: `GET /api/v1/approvals/{approval_id}`; decision via
`POST /api/v1/approvals/{approval_id}/decision`.

### 6.1 Anatomy (top to bottom)

```
┌─ ApprovalCard ────────────────────────────────────────────────────────┐
│ ◷ PENDING            apr-01JQ8Z…                    expires in 2h 14m │  ← 1 status strip
├───────────────────────────────────────────────────────────────────────┤
│ SUNIL is asking to run                                                │  ← 2 provenance block
│   stripe_mcp . refunds.create                                         │
│   requested by  project_manager (Project Manager Agent)               │
│   at            11 Sep 2026, 09:41:06 (18 min ago)                    │
│   expires       14 Sep 2026, 09:41:06                                 │
├───────────────────────────────────────────────────────────────────────┤
│ ▌ SUMMARY — text supplied by the request, shown exactly as received   │  ← 3 untrusted summary
│ ▌ ┌───────────────────────────────────────────────────────────────┐   │
│ ▌ │ Refund AUD 240.00 on charge ch_3Qk2p… — "EasyClean — Feb deep │   │
│ ▌ │ clean <b>URGENT</b> [click here](http://x.invalid) "           │   │
│ ▌ └───────────────────────────────────────────────────────────────┘   │
├───────────────────────────────────────────────────────────────────────┤
│ EXACT PARAMETERS (redacted)                            args_hash …a91 │  ← 4 params table
│   charge          ch_3Qk2p9LmQfT0Xv                                   │
│   amount_cents    24000                                               │
│   currency        aud                                                 │
│   reason          requested_by_customer                               │
│   idempotency_key ●●●●●●●● redacted                                   │
├───────────────────────────────────────────────────────────────────────┤
│ WHERE THIS CAME FROM                                                  │  ← 5 context links
│   Conversation  "EasyClean February billing" →                        │
│   Task          task-01JQ8Z… (parked) →                               │
│   Trace         request 01JQ8Z… — 12 stages →                         │
├───────────────────────────────────────────────────────────────────────┤
│ ⓘ Approving runs this once, now. SUNIL has 1 hour from your decision  │  ← 6 grace note
│   to execute it; after that the approval expires unused.              │
├───────────────────────────────────────────────────────────────────────┤
│                            [ Refuse ]        [ Approve this action ]  │  ← 7 decision bar
└───────────────────────────────────────────────────────────────────────┘
```

### 6.2 Field map

| Region | Element | Field | Trust |
|---|---|---|---|
| 1 | Status pill | `status` | trusted enum |
| 1 | Id (monospace, click-to-copy) | `id` | trusted |
| 1 | Countdown | `expires_at` − now | derived |
| 2 | Operation identifier | `tool`, `operation` | **trusted** — registry keys from `config/tools.yaml`; may be styled as code |
| 2 | Agent | `agent_id` (+ display name from the agents registry) | trusted |
| 2 | Requested at | `created_at` | trusted |
| 2 | Expires at | `expires_at` | trusted |
| 3 | Summary | `summary` | **UNTRUSTED** — C4 §4 plain text only |
| 4 | Params rows | `params_redacted` (keys and values) | **UNTRUSTED values**; keys are schema-derived but rendered with the same escaping |
| 4 | `args_hash` (truncated, copyable, full value on expand) | `args_hash` | trusted |
| 5 | Conversation link | `conversation_id` → `/chat/{conversation_id}` | trusted |
| 5 | Task link | `task_id` → `/tasks/{task_id}` | trusted |
| 5 | Trace link | `request_id` → `/audit/{request_id}` | trusted |
| 6 | Grace note | `SUNIL_APPROVAL_CONSUME_GRACE_HOURS` (default 1) | config-derived — see Q3 |
| 7 | Decision | `POST …/decision` `{decision, reason?}` | — |
| post-decision | Decided by/at | `decided_by`, `decided_at`, `decision_reason` | trusted |
| post-decision | Executed at | `consumed_at` | trusted |

### 6.3 How untrusted text is contained (the C4 §4 rule, made visual)

Three mechanisms, all of them necessary:

1. **Mechanical.** The value is inserted as a text node (`textContent` / React's default escaping
   of `{value}`). No `dangerouslySetInnerHTML`, no markdown component, no `innerHTML`, no
   `v-html`-equivalent, no template that interpolates it into an `href`, `src`, `style` or `title`
   attribute. The same applies to every `params_redacted` value and to any tooltip text.
2. **Visual.** The summary and each param value sit inside an `UntrustedText` block: `surface-raised`
   background, 1px `border`, 3px left bar in `text-muted`, `font-mono-body`, `white-space:
   pre-wrap`, `overflow-wrap: anywhere`. It **looks quoted** — visibly different from SUNIL's own
   voice, which everywhere else in the product is unboxed text on `surface`. An owner who has seen
   this pattern twice will distrust anything inside it by reflex, which is the point.
3. **Labelled.** Directly above the block, in `Micro/badge` scale, `text-muted`:
   **`SUMMARY — text supplied by the request, shown exactly as received`**. Params get
   **`EXACT PARAMETERS (redacted) — values shown exactly as received`**. Provenance is stated, not
   implied.

Additional hardening the design assumes:
- **Length cap.** `summary` is ≤500 chars by schema; render it fully (no truncation on this screen)
  but cap the block's height at ~12 lines with an internal scroll so a 500-char single-word string
  cannot push the decision buttons below the fold.
- **Control/bidi characters.** Render with a font and CSS that make direction overrides visible;
  strip nothing, but apply `unicode-bidi: plaintext` so an RTL-override character cannot visually
  reorder the summary to read as a different action. Flagged to Security as Q5.
- **Long tokens.** `overflow-wrap: anywhere` prevents a 500-char unbroken string from blowing the
  layout out horizontally.
- **No linkification.** URLs inside the summary are never turned into links. If the owner needs to
  visit one, they copy it deliberately.

### 6.4 Redacted values
Values redacted by ADR-006 render as `●●●●●●●● redacted` in `text-muted` with an `eye-off` icon and
the tooltip-free helper line *"SUNIL removed this value before showing it to you — it is still part
of what gets executed."* An owner must not read a redaction as "empty".

### 6.5 Expiry — how the two clocks are communicated

There are **two** different deadlines and conflating them is the single most likely
misunderstanding on this screen:

| Clock | From → to | Default | Where shown |
|---|---|---|---|
| **Decision TTL** | `created_at` → `expires_at` | 72h (`SUNIL_APPROVAL_TTL_HOURS`) | Status strip countdown + the `expires` row in the provenance block. Under 12h: `warning`. Under 1h: `danger` + the `alert-triangle` icon + the line *"If this expires the task fails — SUNIL will not run it."* |
| **Consume grace** | `decided_at` → `decided_at + grace` | 1h (`SUNIL_APPROVAL_CONSUME_GRACE_HOURS`) | **Before** the decision: the §6.1 region-6 note, phrased as a consequence of approving. **After** approving: replaces the TTL countdown with `Runs within 58m` and, if it lapses, `EXPIRED UNUSED`. |

Countdown rendering: text is primary (`in 2h 14m`, tabular figures, updating every 30s — not every
second; a per-second timer on a 72-hour window is noise and a needless repaint). A thin progress
bar under the text is decorative reinforcement only, with `aria-hidden="true"`; the text carries
the meaning. The live-region announcement fires **once** at each threshold crossing (12h, 1h,
expired), never on every tick.

### 6.6 Decision controls

- **Approve** — primary, `accent` fill, `accent-on` label, text **`Approve this action`** (not
  "OK"). One primary CTA per screen.
- **Refuse** — `danger` outline (not a filled red button; filled danger next to filled accent
  makes a 50/50 choice out of an asymmetric one), text **`Refuse`**. Opens an inline confirm step
  rather than acting immediately (see below).
- Both are ≥44px tall, ≥120px wide, separated by 16px, right-aligned, with Refuse **left** of
  Approve (destructive action away from the resting cursor/thumb position on the primary).
- **Keyboard:** `A` approves and `R` refuses — but **only** when the card has focus within it and
  the confirm step is shown; a single unguarded keystroke must never move money. Precisely: `A`
  focuses and arms the Approve confirm, `R` arms the Refuse confirm; `Enter`/`Space` on the armed
  button commits; `Escape` disarms. The shortcuts are listed in a `?`-triggered shortcut sheet and
  in the card's `aria-describedby` help text. Tab order inside the card: back-link → copy-id →
  summary block (scrollable region, focusable) → params expand → context links → Refuse → Approve.
- **Reason** — an optional `reason` textarea (≤1000 chars, `DecisionRequest.reason`) is shown
  expanded for Refuse (a refusal the owner will read back in three weeks needs a why) and behind a
  `Add a note` disclosure for Approve.
- Both decisions are irreversible; the confirm step says so in words: *"There is no undo — a
  decision is final (you can always ask SUNIL to do it again from chat)."*

### 6.7 Decision flow states (normative)

| State | UI |
|---|---|
| Idle (pending, fresh data) | As §6.1 |
| Idle (pending, stale data §1.5) | Buttons disabled, helper line *"Reconnect before deciding — this page may be out of date."* |
| Armed | The chosen button gains a confirm affordance (`Confirm approve` / `Confirm refuse`), the other dims, `Escape` cancels |
| Submitting | The pressed button shows an inline spinner and the label `Approving…` / `Refusing…`; **both** buttons disabled; the card is `aria-busy="true"`. No optimistic status change |
| Success | The card re-renders from the **response body** (the server's `Approval` row): status strip becomes `✓ APPROVED` / `✕ REFUSED`, decision bar is replaced by a decision receipt (`Approved by owner at 10:07 am` + the reason if given), and — for approve — the grace countdown (§6.5). A polite live-region announcement states the new status. A success toast is **not** used; the card itself is the confirmation |
| Conflict (409) | The card re-renders in the status from `error.current_status` with the banner *"This was already {status} — your decision was not applied."* This is the honest path C4 §5 deliberately designed for (no idempotent echo) |
| Expired at decision time (409, `current_status=expired`) | Same, with copy *"This approval expired before your decision landed. The task has been failed as `approval_expired`. Ask SUNIL again if you still want it."* |
| Not found (404) | Full-view `ErrorPanel`: *"That approval doesn't exist."* + `Back to the queue` |
| Network failure | Card stays in Idle with the banner *"Your decision didn't reach SUNIL — nothing has changed. Try again."* Retry re-sends; a 409 on retry is handled as above (so a lost-response double-submit is safe) |
| Terminal (`consumed`) | Status strip `✓✓ CONSUMED`, receipt shows `Executed at {consumed_at}`, plus `See what happened →` linking to `/audit/{request_id}` |

### 6.8 Empty / loading / error for the detail route
Loading: the card's skeleton at full height (strip, 4 provenance lines, summary block, 5 param
rows, decision bar) so nothing shifts when it lands. Error/404: §6.7. There is no "empty" state for
a detail route — an id either resolves or 404s.

---

## 7. View — Agent activity (`/activity`) · mockup `03-agent-activity.html`

"What is SUNIL doing right now, and what did it just do?" This is the `WorkIndicator` family from
M1 (`DASHBOARD_DIRECTION.md` §3), unscoped from a single chat turn.

### 7.1 Layout
- **Now** — 0..n `AgentActivityCard`s, one per non-terminal task. Each: agent display name, the
  current phase label (the 12→4 phase map from `M1_CHAT_SPEC.md` §5.3 — *Understanding / Planning /
  Working / Finishing*, reusing `apps/web/src/lib/phases.ts`), the dynamic detail (`Checking
  EasyClean Workforce…` from `plan_created.detail.project_display_name` or
  `tool_requested.detail.tool`), elapsed time, the originating conversation link, and `Open trace →`.
  `elevation-2` + `animate-work-pulse`, disabled under reduced motion per `DESIGN_SYSTEM.md` §6.
- **Waiting on you** — parked tasks, rendered as compact approval rows that link to `/approvals/{id}`.
  A parked task is *activity that has stopped*, and it belongs where the owner is looking for
  movement.
- **Recently finished** — last 20 terminal tasks: status pill, objective, agent, duration,
  `request_id` link to the audit browser.

### 7.2 Data
Every field here comes from `tasks` + the latest `audit_events` row for that `request_id`
(`ARCHITECTURE_V1.md` §3.4/§7.3, carried into V2). No endpoint currently returns it — see **Q1**
and the proposed `GET /api/v1/activity` in §13.2.

| Element | Source |
|---|---|
| Agent | `tasks.assigned_agent` → display name from `config/agents.yaml` |
| Objective | `tasks.objective` — **treat as untrusted** (it is plan text derived from a user/LLM string): `UntrustedText` rules, single-line clamp |
| Phase | latest `audit_events.stage` for the `request_id`, mapped 12→4 |
| Detail line | `audit_events.detail.project_display_name` / `.tool` / `.operation` (contracted keys, `ARCHITECTURE_V1.md` §3.4) — trusted, from config |
| Elapsed | now − `tasks.started_at` |
| Status | `tasks.status` (`pending\|in_progress\|completed\|failed\|parked`) |
| Failure | `tasks.failure_kind` → the C5 failure-kind copy table (§11.3) |

### 7.3 States
Loading: 3 skeleton cards. **Empty (the common case): "SUNIL is idle."** + *"Nothing is running.
Scheduled workflows and your chat messages both show up here while they work."* + action `Ask SUNIL
something →` (routes to `/chat`). Error: `ErrorPanel` with retry. Stale: §1.5 — an activity view
showing a 40-second-old "running" card without saying so is a lie about liveness, so the freshness
chip is mandatory on this view and the elapsed counters freeze (and grey) while the poll is failing.

---

## 8. View — Tasks (`/tasks`) · mockup `04-tasks-projects.html`

### 8.1 Layout
`DataTable` with a `FilterBar`: status segmented control (`Running | Parked | Completed | Failed |
All`), project filter, date range, and a text search over `objective` (server-side — see Q1).

| # | Column | Source | Priority |
|---|---|---|---|
| 1 | Status | `tasks.status` → `StatusPill` | P1 |
| 2 | Objective | `tasks.objective` (untrusted, 1-line clamp) | P1 |
| 3 | Agent | `tasks.assigned_agent` | P2 |
| 4 | Project | `plan_created.detail.project_key` (see Q2 — `tasks` has no project column) | P2 |
| 5 | Started | `tasks.started_at` (relative + `<time>`) | P2 |
| 6 | Duration | `completed_at − started_at`, or live elapsed | P3 |
| 7 | Outcome | `tasks.failure_kind` or `—` | P3 |
| 8 | Trace | `tasks.request_id` → `/audit/{request_id}` | P4 |

Row → `/tasks/{task_id}`: objective, status history (`task_status_events`: `from_status →
to_status @ at` — a vertical timeline), the linked approval if the task parked, the conversation
link, and the full trace inline (`TraceTimeline`, §10).

### 8.2 States
Loading 5 skeleton rows · Empty: **"No tasks yet."** + *"A task is created whenever SUNIL makes a
plan. Start a conversation and one will appear here."* + `Go to chat →` · Filtered-empty: *"No
{status} tasks in this range."* + `Clear filters` · Error: retryable `ErrorPanel`.

---

## 9. View — Projects (`/projects`) · mockup `04-tasks-projects.html`

Projects are **static config** (`config/projects.yaml`, FR-107) — this view is a reference list,
not a CRUD surface. Say so on the page: *"Projects come from SUNIL's configuration. Add one by
editing `config/projects.yaml` and restarting."* An empty-looking editable-looking grid that cannot
be edited is worse than an honest read-only list.

| Element | Source |
|---|---|
| Project name | `ProjectSummary.display_name` (C5 schema; `GET /api/v1/projects`) |
| Key | `ProjectSummary.key`, `code` style |
| Recent activity | Count of tasks per project over 7 days (needs Q2's project linkage) |
| Last touched | Most recent task `created_at` for that project |
| Open tasks / pending approvals | Counts, each linking to the filtered list |

**States:** Loading 4 skeleton cards · Empty: **"No projects configured."** + *"SUNIL can only work
on projects it knows about. Add them to `config/projects.yaml`."* (this is also what the chat's
`unknown_project` error refers to — one source of truth for the project list, per
`M1_CHAT_SPEC.md` §5.9) · Error: retryable.

---

## 10. View — Audit browser (`/audit`, `/audit/{request_id}`) · mockup `05-audit-browser.html`

The full-scope version of M1's `TraceDisclosure` (`DASHBOARD_DIRECTION.md` §5): the same
plain-English rendering rule, unscoped from one turn, searchable by `request_id`.

### 10.1 `/audit` — the index
`DataTable` of turns (grouped `audit_events` by `request_id`): request id, when, conversation,
outcome (from `final_response.detail.outcome` / `failure_kind`), stage count (`12` normally — a
number other than 12 is itself a signal and is rendered `warning`), duration (last `at` − first
`at`), agent. Filters: date range, outcome, agent, and a `request_id` exact-match box (the primary
way in — the owner usually arrives with an id from another view).

### 10.2 `/audit/{request_id}` — the trace
A `TraceTimeline` of the twelve `audit_events` rows, in `seq` order, each an expandable `StageRow`
(native `<details>` — keyboard operable for free, `aria-expanded` handled by the browser).

Collapsed row: `seq` · plain-English stage label · `+2.4s` offset from the first row · a one-line
`summary` (from `audit_events.summary`) · a chevron. Expanded: the contracted `detail` keys as a
definition list (`ARCHITECTURE_V1.md` §3.4 table), then the raw `detail` JSON in a `<pre>` — plain
text, never rendered as markup, `overflow-wrap: anywhere`.

**Stage → label map** (reuse `phases.ts`; these are the exact NFR-020 names):

| # | `stage` | Plain-English label | Contracted `detail` keys surfaced |
|---|---|---|---|
| 1 | `message_received` | Received your message | — |
| 2 | `context_loaded` | Loaded conversation context | — |
| 3 | `memory_retrieved` | Checked memory | — |
| 4 | `model_selected` | Chose a model | `capability`, `provider`, `model` |
| 5 | `llm_io` | Interpreted the request | `purpose`, `provider_attempts`, `input_tokens`, `output_tokens` |
| 6 | `plan_created` | Created a plan | `project_key`, `project_display_name`, `agent`, `plan_attempts` |
| 7 | `agent_started` | Started the agent | `agent`, `agent_display_name` |
| 8 | `tool_requested` | Asked to use a tool | `tool`, `operation` |
| 9 | `permission_decision` | Permission check | `decision`, `tool`, `operation` |
| 10 | `tool_result` | Tool result | `ok`, `duration_ms`, `error_kind` |
| 11 | `agent_result` | Analysed the result | `ok` |
| 12 | `final_response` | Prepared the answer | `outcome`, `failure_kind` |

**Approval episodes.** When a turn parked, stage 9's `decision` is `ask_user` and the timeline
continues past the twelve with the approval's own audit rows (`approval_requested`,
`approval_approved`/`approval_refused`, then the continuation's `tool_call` row with
`approval_id`, `ARCHITECTURE_V2.md` §6 Leg 6). Render these as a **second, visually distinct
segment** headed `AFTER YOUR DECISION — continuation (resumed_from_approval_id …)`, with the human
wait shown as an explicit gap marker: `⏸ waiting for you — 26 min`. Without that marker the offset
column jumps from `+3.1s` to `+1583s` and reads as a performance disaster rather than a human
lunch break. Decision 8.

**Highlighting.** Rows where `permission_decision.detail.decision != "allow"`, or
`tool_result.detail.ok == false`, or `final_response.detail.outcome != "ok"` take a left bar in
`warning`/`danger` and are expanded by default. Everything else is collapsed. An owner opening a
trace wants the exception, not row 1.

**Copy/export.** `Copy request_id`, and `Copy trace as text` (the plain-English list with offsets,
exactly the M1 §5.5 format) — the fastest possible path from "something looks wrong" to a message
to a developer.

### 10.3 States
Loading: the 12 row skeletons (a trace is always ~12 rows, so the skeleton can be exact) · Empty
(index, no turns): **"No activity recorded yet."** · Empty (id not found): **"No trace for that
request id."** + *"Ids look like `01JQ8Z…`. Check the id, or browse recent turns."* + `Browse
recent` · Partial (<12 stages and the turn is terminal): a `warning` banner *"This trace has {n} of
12 stages — the turn ended early."* — the missing-stage case is information, not an error to hide ·
Error: retryable `ErrorPanel`.

---

## 11. Chat inside the shell (`/chat`) · mockup `06-nav-shell.html`

### 11.1 What does not change
`M1_CHAT_SPEC.md` is intact: `MessageList`, `Composer`, `WorkIndicator`, `AssistantMessage`,
`TraceDisclosure`, `ErrorCard`, `JumpToBottomPill`, `SuggestionChips`, all four composer states, all
four error variants, the 12→4 phase map, the 45s client timeout, the cancel semantics. The M1
`TopBar` is **replaced** by the shell's rail + topbar (exactly the coupling `DASHBOARD_DIRECTION.md`
§2 warned about). The message column keeps `max-w-3xl` inside the wider content pane.

### 11.2 What is new — the parked turn (C5 `outcome=parked`)
A new terminal turn state alongside ok/failed. Rendered as `ParkedTurnCard` in the message list
where the assistant reply would have been:

> **⏸ This needs your approval before I can continue.**
> `UntrustedText` block: `approval.summary` (C5 `ApprovalRef.summary` — same plain-text rule)
> `Expires {relative}` (`approval.expires_at`)
> `[ Review and decide → ]` (primary, routes to `/approvals/{approval.approval_id}`)

Card styling: `surface`, `warning` 1px border + 3px left bar, `pause` icon. Not `danger` — parking
is the system working correctly, and colouring it as a failure trains the owner to dread it.
Announced `aria-live="polite"`. The composer returns to Idle (the turn is over; the owner may keep
chatting) — this differs from M1's Busy behaviour and must be explicit in the build.

When the continuation later appends its assistant message to the same conversation (C4 §3), it
renders as an ordinary `AssistantMessage` with a small preceding system line: *"Continued after you
approved `stripe_mcp.refunds.create` at 10:07 am."* The refusal/expiry paths render a system line
from the failure kind (§11.3) — the conversation must never simply go silent after a park.

### 11.3 Failure-kind copy (extends `M1_CHAT_SPEC.md` §5.6–5.9 with C5's three new kinds)

| `failure.kind` | Copy | Action |
|---|---|---|
| `approval_refused` | *"You refused this, so I didn't run it."* (+ the reason, as `UntrustedText`, if one was given) | `View the approval →` |
| `approval_expired` | *"The approval ran out of time, so I didn't run it."* | `Ask again` (pre-fills the composer with the original message) |
| `continuation_interrupted` | *"I was interrupted part-way through running this. Check the trace before retrying — the action may already have happened."* | `Open trace →` |

That last copy is deliberately cautious: C4 §3 rule 3 says the tool call may or may not have fired,
and the reconciliation never re-executes. Telling the owner "it failed, try again" would be wrong
and could double-refund a customer.

---

## 12. Accessibility specification

Everything in `DESIGN_SYSTEM.md` §7 applies unchanged. This section adds what is specific to the
ops views.

### 12.1 Focus order and keyboard
- Global tab order per §1.3. Every view's toolbar precedes its content; pagination is last.
- **Every row is a real `<a>`**; every action is a real `<button>`. No `div` with `onClick`.
- **`<table>` semantics** for tabular data (not a grid of divs), with `<caption>` (visually hidden),
  `scope="col"` headers, and `aria-sort` on the sort toggle.
- Expandable trace rows use `<details>/<summary>` — native keyboard support, no ARIA to get wrong.
- **Escape** closes any transient overlay (confirm step, overflow sheet, shortcut sheet) and
  returns focus to the control that opened it.
- **Shortcut sheet** on `?`, listing: `g` then `d/a/c/t/p/u` to jump (dashboard/approvals/chat/
  tasks/projects/audit), `/` focuses the view's search, `r` refreshes, `A`/`R` arm approve/refuse
  on an approval card (§6.6), `Esc` cancels.
- No keyboard traps; no shortcut overrides a browser/AT shortcut; all shortcuts are disabled while
  focus is in a text input.

### 12.2 Screen reader
- One `aria-live="polite"` region per page for: route change ("Approvals queue"), poll-stale
  transition, decision result, and each approval expiry threshold crossing. Throttled — never one
  announcement per poll and never per countdown tick.
- `aria-live="assertive"` reserved for decision **failures** and the stale-data warning that
  disables the decision buttons.
- Tables announce their row count via the visually hidden `<caption>` (`"Approvals, 7 rows, page 1"`).
- The approval card's decision buttons carry `aria-describedby` pointing at the grace note and the
  irreversibility line — a screen-reader user must not have to hunt for the consequence.
- Countdowns: the visible text updates every 30s but the accessible name is refreshed at threshold
  boundaries only, to avoid a chattering live region.

### 12.3 Colour is never the only signal
Every status is **icon + uppercase text + colour**, and additionally a **border pattern** where it
sits on a row edge:

| Status | Icon (Lucide) | Text | Colour token | Row edge |
|---|---|---|---|---|
| `pending` | `clock` | PENDING | `warning` | 2px solid |
| `approved` | `check` | APPROVED | `accent` | 2px solid |
| `consumed` | `check-check` | CONSUMED | `success` | 2px solid |
| `refused` | `x` | REFUSED | `danger` | 2px dashed |
| `expired` | `ban` | EXPIRED | `text-muted` | 2px dotted |
| task `in_progress` | `loader` (static under reduced motion) | RUNNING | `accent` | 2px solid |
| task `parked` | `pause` | PARKED | `warning` | 2px solid |
| task `failed` | `alert-triangle` | FAILED | `danger` | 2px dashed |
| task `completed` | `check` | DONE | `success` | 2px solid |

Printed in greyscale or seen by a fully colour-blind user, every row remains classifiable.

### 12.4 Contrast (Amendment A round-3 pairs, computed by the WCAG relative-luminance method)

Grounds: canvas `#0B0906` (L .0028), surface `#16120C` (.0063), raised `#201A11` (.0109),
high `#2B2315` (.0177). Every text token is checked against **its actual worst ground** — and,
new in round 3, against the **comfort ceiling** (Amendment A §A.7): sustained-reading text must
land 9–13:1 and never exceed 13.5:1, because on an hours-a-day dark console maximum contrast is
glare, not accessibility.

| Pair | Ratio | Requirement | Result |
|---|---|---|---|
| `text-primary` `#CEC5B4` on canvas / surface / raised / high | 11.6 / 10.9 / 10.1 / 9.1:1 | 4.5:1 floor · 9–13:1 band | Pass — in the comfort band on all four grounds |
| `text-secondary` `#C4B48D` on canvas / high | 9.7 / 7.6:1 | 4.5:1 | Pass |
| `text-muted` (sand) `#9A8D71` on canvas / surface / raised / high | 6.1 / 5.7 / 5.3 / 4.7:1 | 4.5:1 | Pass on all four grounds |
| `accent` (gold) `#C9A227` on canvas / surface / high | 8.2 / 7.7 / 6.4:1 | 4.5:1 text / 3:1 ring | Pass, both uses |
| `gold-deep` `#B08A2A` on canvas / surface | 6.2 / 5.8:1 | 4.5:1 | Pass |
| ink `#14100A` on gold fill `#C9A227` / hover `#DBBE7F` / pressed `#A6801F` | 7.8 / 10.5 / 5.2:1 | 4.5:1 | Pass at every stop of the metallic sheen |
| ink on `status-pending` fill `#D98E4A` (rail badge) | 8.1:1 | 4.5:1 | Pass |
| `status-pending` (copper) `#D98E4A` on canvas / high | 7.5 / 5.9:1 | 4.5:1 | Pass |
| `status-approved` `#5E96E0` on canvas / high | 6.5 / 5.1:1 | 4.5:1 | Pass |
| `success` `#3FAE6C` on canvas / high | 7.1 / 5.5:1 | 4.5:1 | Pass |
| `danger` `#E8685C` on canvas / surface / raised / high | 6.2 / 5.8 / 5.4 / 4.9:1 | 4.5:1 | Pass |
| ink on `danger-strong` fill `#E5484D` | 4.8:1 | 4.5:1 | Pass — white on it is 3.9:1 and **fails**, hence dark ink on all fills |
| focus ring (gold) vs `surface-high` | 6.4:1 | 3:1 | Pass |
| *(retired)* round 2's `text-primary` `#F5EFE3` on canvas | 18.3:1 | ≤13.5:1 ceiling | **Above the ceiling** — the value the owner reported as eye strain |
| *(rejected)* `#FFD700` web-gold accent | — | — | Rejected as costume in round 2 (Decision 12); doubly out under the round-3 "remove yellow" ruling |
| *(rejected)* `#8A7D63` as text-muted | 3.8:1 on high | 4.5:1 | **Fails** — why muted stops at `#9A8D71` |

### 12.5 Motion, zoom, touch
- `prefers-reduced-motion` is already a global kill-switch (`DESIGN_SYSTEM.md` §7, confirmed in
  `globals.css`). The activity pulse, skeleton shimmer and expand/collapse all collapse to instant;
  no state is motion-only.
- All type in rem; tables must survive 200% zoom by dropping to the card layout (§4.4) rather than
  clipping. No fixed-height row containers.
- Touch targets ≥44×44 everywhere, including table row links (achieved with row padding) and the
  trace disclosure chevrons; 8px minimum between adjacent targets.

---

## 13. What the API must provide that it currently does not

Written as proposals so the Architect can freeze or correct them quickly — Stream D's frontend
cannot start §7, §8 or §10 without something of this shape. All are **read-only, owner-session
only**, same auth as C4 (`sessionCookie` + `X-SUNIL-Client: web`), same error envelope, same cursor
pagination.

### 13.1 `GET /api/v1/tasks`
`?status=&project_key=&q=&order=&limit=&cursor=` → `{tasks: Task[], next_cursor}` where `Task` =
`{id, objective, status, assigned_agent, priority, project_key, request_id, conversation_id,
approval_id?, created_at, started_at, completed_at, failure_kind}`.
`GET /api/v1/tasks/{id}` adds `status_events: [{from_status, to_status, at}]` (from
`task_status_events`).

### 13.2 `GET /api/v1/activity`
`{running: ActivityItem[], parked: ActivityItem[], recent: ActivityItem[]}` where `ActivityItem` =
the `Task` above plus `{latest_stage, latest_stage_at, latest_detail: {project_display_name?, tool?,
operation?}}`. One request, because the alternative — list tasks then fetch a trace per task — is an
N+1 on a 10-second poll.

### 13.3 `GET /api/v1/audit`
Index: `?request_id=&from=&to=&outcome=&agent=&limit=&cursor=` →
`{turns: [{request_id, started_at, ended_at, stage_count, outcome, failure_kind, agent,
conversation_id, task_id}], next_cursor}`.
Detail: `GET /api/v1/audit/{request_id}` → `{events: [{seq, stage, actor, summary, detail, at,
task_id}], approval_events?: [...]}` in `seq` order.
**Security note carried forward:** `audit_events.detail` may contain a truncated excerpt of
untrusted content (`ARCHITECTURE_V1.md` §3.4, T-32). The audit browser renders every `detail` value
under the §6.3 plain-text rules — the same containment as the approval card, no exceptions for
"developer-facing" screens.

### 13.4 Projects
`GET /api/v1/projects` exists in the module layout; the view needs it to return at least C5's
`ProjectSummary {key, display_name}`. Counts (§9) require the task→project linkage of Q2.

---

## 14. Open questions for the owner / Architect (Gate 2)

| # | Question | Blocks | My default if unanswered |
|---|---|---|---|
| Q1 | Tasks, activity and audit have no HTTP contract (§13). Freeze the three read-only endpoints now, or cut those three views from Stream D's first release and ship approvals + chat only? | §7, §8, §10 | Build against §13's shapes as a mock; do not start Stream D's data layer for those views until frozen |
| Q2 | `tasks` has no `project_key` column; the project is only in `audit_events.detail`. Add the column, or accept that Tasks/Projects cannot filter by project in v1? | §8 col 4, §9 counts | Show the project column only where `plan_created.detail` is available; hide the filter |
| Q3 | The consume-grace window (`SUNIL_APPROVAL_CONSUME_GRACE_HOURS`, default 1h) is invisible to the API — the dashboard cannot read it. Expose it (e.g. on the approval row, or a `GET /api/v1/config/public`), or hardcode "1 hour" in the UI copy? | §6.5 grace note | Hardcode "1 hour" **and** render the post-approval countdown from `decided_at + 1h`, with a build-time constant that must be changed alongside the env var. Fragile — I recommend exposing it |
| Q4 | Should C4 gain a risk/impact classification (e.g. `low/medium/high`, or "spends money / changes code / sends a message")? Today the queue can only sort by time, so a `$4,000 refund` and a `label added to an issue` look identical until opened | §5.4 | Ship without it; signal time pressure only |
| Q5 | Confirm with Security: is `unicode-bidi: plaintext` + no-linkification + text-node-only rendering the accepted containment set for `summary`/`params_redacted`/`detail`, or is a stricter character policy (e.g. rejecting C0/bidi control chars at park time) wanted? | §6.3 | Ship the CSS/rendering set above and flag the character policy as a backend hardening item |
| Q6 | ~~Landing route: approvals-first when pending (Decision 2). Or would you rather always land in Chat?~~ **ANSWERED (round 4, owner 2026-09-11): neither — the landing view is a unified Dashboard** ("all these main components in a dashboard… once I click the box it expands or redirects to the page. I wanna see all the info in one place"). §16 specifies it; Decision 2 amended | — | — |
| Q7 | ~~Light theme: do you want it at all, or is SUNIL dark-only as a brand position?~~ **ANSWERED at Gate 2 (round 2): dark-only is the brand position.** The light map is deleted; Amendment A is the committed Obsidian & Gold theme; Decision 10 records the ruling | — | — |
| Q8 | Mobile: is a phone-usable approval decision a v1 requirement, or is desktop-only acceptable for the rebuild? | §1.4 | Approvals mobile-complete, other views best-effort |
| Q9 | **Architect:** does a **parked** turn emit all twelve stages, or short-circuit after `permission_decision`? ET-8 guarantees stage 12 always fires, but stages 10–11 (`tool_result`, `agent_result`) have no obvious value on a turn whose tool never executed | §10.2 stage count, §10.3 partial banner | Render whatever arrives; flag any count ≠ 12 in `warning` and never pad or hide a missing stage |

---

## 15. Traceability

| Spec section | Contract / doc | Requirement honoured |
|---|---|---|
| §1.5 | C4 §2 | 10s poll, no push channel, dashboard queue is the source of truth |
| §5.2, §6.2 | C4 OpenAPI `Approval` | Every rendered element maps to a named schema field |
| §6.3, §6.4 | C4 §4 (Security 2026-09-10 item 8) | Plain-text-only rendering of `summary`/`params_redacted` |
| §6.5 | C4 §1 grace-bounded consume | Two clocks distinguished, `SUNIL_APPROVAL_CONSUME_GRACE_HOURS` surfaced |
| §6.7 | C4 §5 | No decision idempotency → no optimistic UI; 409 shows the true state |
| §10.2 | `ARCHITECTURE_V1.md` §3.4, ADR-023 | Exactly twelve stages, contracted `detail` keys, plain-English labels |
| §10.2 (continuation segment) | C4 §3, `ARCHITECTURE_V2.md` §6 | The approval episode's audit chain is one story, not two |
| §11.2 | C5 §2.1, ADR-031 | `outcome=parked` + `ApprovalRef` rendered; exactly-one rule respected |
| §11.3 | C5 `ChatFailure.kind` | All seven kinds have shippable copy |
| §12 | `DESIGN_SYSTEM.md` §7 | Accessibility floor unchanged, extended for tables/decisions |
| Amendment A (round 2) | `DESIGN_SYSTEM.md` §0 rule; owner Gate-2 verdict | Amendment section replaced wholesale (it was PROPOSED, unapproved); nothing above the amendment line changed; every pair ships with a computed contrast ratio |
| §16 (round 4) | Owner verdict 2026-09-11; C4 §2/§4; §13 shapes | Dashboard composes the five views' own queries at summary tier; approval rows keep the C4 §4 quotation pattern; no new endpoint, token or moving element introduced |

---

## 16. View — Dashboard (`/`, the landing) · mockup `00-dashboard.html` — ROUND 4

**Owner's request (verbatim intent, 2026-09-11):** *"Can we have all these main components in a
dashboard? So say for approvals, there's a section — once I click the box it expands or redirects
to the page. I wanna see all the info in one place too."* This overrides round-1 Decision 2 (which
rejected a composite Home) and answers Q6: **the landing view is a unified Dashboard.** Recorded as
Decision 2 (amended) and Decision 17 in `V2_DESIGN_DECISIONS.md`.

### 16.1 The rule that contains the maintenance cost

The Dashboard is **not a sixth data model**. Each section is the *summary tier* of an existing
view: the same components (`StatusPill`, `UntrustedText` compact form, `ExpiryMeter` compact,
the relative+absolute timestamp pattern), the same queries, the same copy voice. A change to a
view's row rendering changes its dashboard section for free. The Dashboard may never grow a field
that its full view does not have.

### 16.2 Layout — summary tier above the fold, detail tier by expansion

Top to bottom (desktop; the two-column grid stacks under 1000px):

1. **H1 + chat quick-entry** — a full-width affordance styled like the composer, honestly an
   `<a>` to `/chat` (`aria-label` says so); the real composer lives on the Chat view and receives
   focus on arrival (`?focus=composer`). No message is ever sent from the Dashboard.
2. **Hero — Pending approvals** (`<details open>`, the view's one corner-ticked primary panel).
   Summary row: the pending **count** as the view's single gold key figure (it carries the
   §A.4 key-figure glow), next-expiry and oldest-wait at rest, `Open full view →` to `/approvals`.
   Body: the **top 3 pending rows by urgency** (soonest `expires_at` pressure first, then age):
   operation identifier (trusted, links to `/approvals/{id}`), the `summary` in the **compact
   quotation pattern** (same `UntrustedText` grammar as §5.2 col 3 — mono, barred, single-line
   ellipsis, plain text node only), and the expiry countdown (`danger` under 1h). **No decision
   controls here** — Decision 4 stands; the dashboard shows, the card decides.
3. **Secondary grid, 2×2 `<details>` boxes**, each summary row readable without expanding
   (Amendment A §A.6 — the at-rest figures ARE the summary tier):
   - **Agent activity** — at rest: `{n} running · {p} waiting on you · {f} finished today`, plus
     the **live pulse dot** when `n ≥ 1` (see 16.4). Expanded: one row per running task (phase +
     elapsed) and per parked task. Source: `GET /api/v1/activity` (§13.2).
   - **Tasks** — at rest: `{n} in flight · {x} failed today · {y} done today`. Expanded: the 3–5
     most recent/in-flight rows with `StatusPill`s, objectives in the untrusted compact form.
     Source: `GET /api/v1/tasks?limit=5` (§13.1).
   - **Projects** — at rest: `{n} tracked · last activity {time} ({project})`. Expanded: each
     tracked project with last-activity time and its open-items count. Source:
     `GET /api/v1/projects` + Q2's linkage for the counts.
   - **Recent audit** — at rest: `last turn {time} · {failures} failed · {parked} parked today`.
     Expanded: the last 3–4 turns, one line each — `request_id` link, conversation label, outcome
     pill, absolute time. Source: `GET /api/v1/audit?limit=4` (§13.3).
4. Everything in 1–3 fits above the fold at 1280×800 with the hero expanded; anything deeper is
   reached by expanding a box or leaving for the full view.

**Element → endpoint mapping (and the Q1 consequence).** Approvals: C4's
`GET /api/v1/approvals?status=pending` — the same §1.5 poll, no extra request. Activity, tasks and
audit: the §13.2/§13.1/§13.3 **proposed** shapes. **The Dashboard makes Q1 more pressing**: the
missing endpoints previously blocked three of six views; they now also degrade the landing view
itself. If Q1 resolves as "cut for v1", the Dashboard ships with the hero, projects and chat entry
only, and the three dark sections render an honest *"coming with the {tasks} API"* placeholder —
never an empty box pretending to be a quiet system.

### 16.3 Expand or navigate — both, honestly, zero JS

Each section is a native `<details>`; its `<summary>` is the "box" the owner clicks to expand
in place. The explicit `Open full view →` is a real `<a>` inside the summary row — activating a
link inside a `<summary>` follows the link without toggling, so both behaviours coexist without
script. Defaults per render: **hero open, all other boxes closed** (no persistence — the server
default is the design). Expansion state is presentation, not data: expanding never fetches; the
summary-tier payloads already include the detail-tier rows (they are ≤5 rows each by design).

### 16.4 Motion and gold budget (Amendment A round 3 — inherited, not extended)

The Dashboard adds **no new moving elements**. Its one animated element is the existing live pulse
(the activity section's dot, the `WorkIndicator` family on the single 2600ms system clock —
Decision 16), rendered **only while ≥1 task is running** and frozen to a static ring when the §1.5
poll goes stale (a glow may only claim liveness that is real) and under `prefers-reduced-motion`.
Its one gold key figure is the pending-approvals count, carrying the §A.4 key-figure glow. Panel
sheen applies to the section boxes; untrusted blocks stay flat as everywhere.

### 16.5 States

| State | Content |
|---|---|
| Loading (first paint) | Each section box skeletons at its own summary height (hero: summary + 3 row skeletons, since it ships open); `aria-busy` per region; no layout shift |
| **All-quiet** (0 pending, 0 running) | The hero does **not** render a gold zero — a zero is not a key figure. It collapses to a single calm line: **"Nothing needs your approval."** + *"SUNIL parks a task here whenever a plan reaches an action it can't take on its own."* + `View decided approvals →`; the activity dot is a static muted ring with "SUNIL is idle."; the chat quick-entry becomes the visually leading affordance. A quiet dashboard should feel like good news, not like a broken page |
| Error (a section's fetch fails) | That section's box renders its `ErrorPanel` inline with `Try again`; the other sections keep working — one failed endpoint never blanks the landing view |
| Stale (§1.5) | The standard banner + freshness chip; hero rows dim to 85%; the live pulse freezes. Nothing to disable — the Dashboard hosts no decision controls |
| Populated | As 16.2 |

### 16.6 Accessibility

- `<details>/<summary>` gives expansion its keyboard semantics **for free**: `<summary>` is
  natively focusable, Enter/Space toggles, and the browser reports the expanded/collapsed state to
  assistive technology — no ARIA to hand-roll or get wrong (same reasoning as the §10.2 trace rows).
- Each summary row is one focus stop plus its `Open full view →` link (a second, real `<a>`);
  the hero's approval rows are one link each, carrying the full row context in `aria-label`
  exactly as §5.2 specifies for the queue.
- Focus on landing goes to the `<h1>` per §1.3; the section heading levels are `h1` (view) →
  `h2` (each section) with no skips.
- The live pulse dot carries `role="img"` + `aria-label="Live — agents are running now"`; liveness
  is also stated in the at-rest text (`2 running`), so the signal is never colour/motion-only.
