# SUNIL — Portal Shell Specification (Phase 1)

_Owner: UI/UX Designer (Minions delivery team)_
_Status: **Developer-ready.** Blocks BL-502, BL-504, BL-505._
_Covers: FR-101, FR-103, FR-104, FR-105, FR-020 (UI side), FR-031 (UI side), FR-065 (UI side), FR-091 (UI side), NFR-016, NFR-019, A-09, A-10, Q10_
_Depends on: `DESIGN_TOKENS.md` (all values below are token references — no literal may be introduced in code)_

> **Reading rule for the engineer.** Where this document gives a number, it is the number. Where
> it says "token", use the token, never the value the token happens to hold. If a value you need
> is missing, that is a defect in this spec — raise it rather than inventing one, because an
> invented value is exactly what the token layer exists to prevent.
>
> **Honesty rule (NFR-019, architectural rule 7).** Phase 1 is an empty platform. Nothing in this
> shell may imply data that does not exist. There are no placeholder metrics, no sample charts, no
> greyed-out fake rows implying "content loading soon". Where there is nothing, the screen says so
> in words.

---

## 1. What actually works in Phase 1

| Destination | Phase 1 behaviour |
|---|---|
| Sign-in (`/sign-in`) | **Functional** |
| MFA challenge (`/sign-in/mfa`) | **Functional** |
| Invitation acceptance (`/invite/[token]`) | **Functional** |
| Dashboard (`/`) | **Functional shell** — renders structure and real system-health data only |
| Settings (`/settings`) | **Functional, minimal** — profile, regional, security, appearance, about |
| System Health (`/system-health`) | **Functional** — real data from `GET /api/system-health` |
| The other 18 navigation destinations | **Present, disabled, unmistakably marked, no route registered** |

Per Gate 1 (Q10) the full 22-item navigation is shown. The disabled treatment in §5 is therefore
one of the most-seen components in the product and is specified in full.

---

## 2. Layout system

### 2.1 Breakpoints

| Name | Range | Token | Shell mode |
|---|---|---|---|
| `xs` | 0–479px | — | Drawer navigation, compact header |
| `sm` | 480–767px | `--sunil-bp-sm` | Drawer navigation, compact header |
| `md` | 768–1023px | `--sunil-bp-md` | **Icon rail** sidebar (72px) |
| `lg` | 1024–1279px | `--sunil-bp-lg` | Expanded sidebar (264px) |
| `xl` | 1280–1535px | `--sunil-bp-xl` | Expanded sidebar (264px) |
| `2xl` | ≥1536px | `--sunil-bp-2xl` | Expanded sidebar (264px), content capped at 1440px and centred |

Media queries are **min-width only** (mobile-first). The prototype's single `max-width:960px`
query is superseded; recorded as a deviation in §12.

FR-101 requires verification at 1920px, 1280px and 390px. Those land in `2xl`, `xl` and `xs`
respectively; all three must show no horizontal page scroll and no overlap.

### 2.2 Shell dimensions

| Property | xs / sm | md | lg / xl / 2xl | Token |
|---|---|---|---|---|
| Header height | 56px | 64px | 64px | `--sunil-shell-header-h-compact` / `--sunil-shell-header-h` |
| Sidebar width | 0 (drawer 288px) | 72px | 264px | `--sunil-shell-drawer-w` / `-w-rail` / `-w` |
| Content padding X | 16px | 24px | 24px | `--sunil-shell-pad-x-compact` / `--sunil-shell-pad-x` |
| Content padding Y | 16px | 24px | 24px | same |
| Content max width | 100% | 100% | 1440px (2xl centres it) | `--sunil-shell-content-max` |
| Page section gap | 16px | 20px | 24px | `--sunil-space-16/20/24` |

### 2.3 Grid

```
xl / 2xl / lg                       md                          xs / sm
┌────────┬───────────────────┐   ┌──┬────────────────────┐   ┌────────────────────┐
│ brand  │ header      64px  │   │▤ │ header       64px  │   │ ☰ header     56px  │
├────────┼───────────────────┤   ├──┼────────────────────┤   ├────────────────────┤
│  nav   │                   │   │▤ │                    │   │                    │
│ 264px  │   main            │   │▤ │  main              │   │  main              │
│        │   (scrolls)       │   │▤ │  (scrolls)         │   │  (scrolls)         │
│        │                   │   │▤ │                    │   │                    │
├────────┤                   │   ├──┤                    │   │                    │
│ user   │                   │   │▤ │                    │   │                    │
└────────┴───────────────────┘   └──┴────────────────────┘   └────────────────────┘
     grid-template-columns:            72px 1fr                  drawer overlays main
     var(--sunil-shell-sidebar-w) 1fr
```

- The **sidebar is fixed**, full viewport height, and does **not** scroll with the page. Its nav
  region scrolls independently: `overflow-y: auto; overscroll-behavior: contain;` (the 22-item
  list is ≈1060px tall and overflows every laptop viewport).
- The **header is sticky** (`position: sticky; top: 0; z-index: var(--sunil-z-header)`), with
  `background: var(--sunil-surface-solid)` — **opaque, not the translucent panel token**, because
  content scrolling under a translucent header produces an unmeasurable text backdrop
  (`DESIGN_TOKENS.md` §5.4.3).
- **`main` is the only scroll container** for page content. `body { overflow: hidden }` — the
  prototype's `html,body{overflow:hidden}` is retained deliberately: the shell is an application
  frame, not a document.

### 2.4 Ambience layers (prototype-faithful, and where they may go)

| Layer | z-index | Applies to | Rule |
|---|---|---|---|
| `<SunilPresence />` canvas | `--sunil-z-canvas` (0) | Dashboard and auth pages only | Never behind Settings, System Health or any table |
| `.vignette` | `--sunil-z-ambience` (1) | Same pages as the canvas | `pointer-events: none` |
| `.scanlines` | `--sunil-z-ambience` (1) | Whole app background | `pointer-events: none`, opacity `.05`. **Must remain below the content layer** — see `DESIGN_TOKENS.md` §5.4.7 |
| Content | `--sunil-z-content` (10) | Everything | — |

Scanlines are retained on data-dense pages at the app-background level only, never over a panel.
Reduced motion does not remove them — they are static — but see §11.6 for the opt-out.

---

## 3. Shell structure and landmarks

```html
<!-- illustrative structure, not application code -->
<a class="skip-link" href="#main">Skip to main content</a>
<a class="skip-link" href="#primary-nav">Skip to navigation</a>

<div class="shell">
  <header role="banner" id="app-header"> … §4 … </header>

  <nav id="primary-nav" aria-label="Primary"> … §5 … </nav>

  <main id="main" tabindex="-1" aria-labelledby="page-title"> … page … </main>

  <div id="live-polite" role="status"  aria-live="polite"  class="sr-only"></div>
  <div id="live-alert"  role="alert"   aria-live="assertive" class="sr-only"></div>
</div>
```

| Landmark | Element | Accessible name |
|---|---|---|
| `banner` | `<header>` | implicit |
| `navigation` | `<nav>` | `aria-label="Primary"` |
| `main` | `<main>` | `aria-labelledby` → the visible `<h1>` page title |
| `status` | `#live-polite` | Single app-wide polite region. Route changes, save confirmations, presence-state changes |
| `alert` | `#live-alert` | Single app-wide assertive region. **Errors only.** Never used for anything routine |

**Exactly one `<h1>` per page**, and it is the page title in the header (§4). Panel titles are
`<h2>`; content inside a panel starts at `<h3>`. No heading level may be skipped, and no heading
may be chosen for its size — size comes from a type token.

### 3.1 Skip links

- Two links, first two elements in the DOM, in the tab order before everything.
- Visually hidden until focused: `position:fixed; top:8px; left:8px; transform:translateY(-200%)`
  → on `:focus-visible`, `transform:translateY(0)`.
- When focused: 40px tall, 16px horizontal padding, `--sunil-surface-raised` background,
  `--sunil-text-accent` label, `--sunil-radius-4`, `--sunil-shadow-overlay`,
  `z-index: var(--sunil-z-skiplink)`.
- Activating "Skip to main content" moves focus to `<main tabindex="-1">`, which must **not**
  receive a focus ring (it is a programmatic target, `outline: none` is correct here and only here).

---

## 4. Header

Height 64px (56px below `md`). Horizontal padding matches `--sunil-shell-pad-x` for the breakpoint.
`border-bottom: 1px solid var(--sunil-border-subtle)`.

| Slot | Content | Breakpoints | Notes |
|---|---|---|---|
| 1 | Drawer toggle `☰` | xs, sm only | 44×44px hit area, `aria-expanded`, `aria-controls="primary-nav"`, `aria-label="Open navigation"` / `"Close navigation"` |
| 2 | `<h1 id="page-title">` | all | `--sunil-type-title`, `--sunil-text-primary`. Truncates with ellipsis at one line; full text in `title` |
| 3 | spacer | all | `flex: 1` |
| 4 | System status pill | ≥md | Link to `/system-health`. Lamp + text. See §4.1 |
| 5 | Clock | ≥lg | See §4.2 and §6 |
| 6 | User menu | all | Avatar-less initial chip 32×32, `--sunil-radius-full`. Menu: display name, role, Settings, Sign out |

Below `md`, slots 4 and 5 collapse into the drawer footer rather than being dropped — status and
time are not decoration.

### 4.1 System status pill

- 28px tall, 10px horizontal padding, `--sunil-radius-full`, `--sunil-accent-tint-weak` background,
  `1px solid var(--sunil-border-subtle)`.
- 8px lamp (`--sunil-lamp-*`) + `--sunil-type-micro` label.
- States and their sources — all from `GET /api/system-health`:

| State | Lamp token | Label | Condition |
|---|---|---|---|
| Loading | `--sunil-lamp-unknown`, no glow | `CHECKING` | Request in flight |
| Healthy | `--sunil-lamp-on` | `NOMINAL` | All dependencies healthy |
| Degraded | `--sunil-lamp-warn` | `DEGRADED` | Any dependency degraded |
| Unhealthy | `--sunil-lamp-error` | `FAULT` | Any dependency down |
| Unreachable | `--sunil-lamp-off` | `NO SIGNAL` | Health request itself failed |

- Never colour-only: the text label always renders (SC 1.4.1).
- Polls every 30s. **Polling is paused when `document.hidden`.** A state *change* writes one
  sentence to `#live-polite` ("System status: degraded"). Unchanged polls announce nothing — a
  region that speaks every 30 seconds is a screen-reader denial of service.

### 4.2 Clock

- `--sunil-type-display-sm` (22px Orbitron 600), `tabular-nums`, `--sunil-text-accent`.
- Second line `--sunil-type-micro`, `--sunil-text-muted`: the zone label, e.g. `HOBART · AEDT`.
- **The zone comes from settings. It is never hard-coded. See §6.**
- Ticks once per second via a single app-level interval; **cleared on unmount and paused on
  `document.hidden`**.
- Screen readers: the ticking element is `aria-hidden="true"`. A sibling `.sr-only` element carries
  the time at **minute** granularity and updates only when the minute changes, with `aria-live` **off**
  (it is read on demand, not announced). A per-second live region is unusable.

---

## 5. Navigation

### 5.1 Information architecture — all 22 destinations

Grouped into five sections. Groups exist because a flat 22-item list at 40px per row is 880px of
undifferentiated text, and because grouping makes the Phase 1 / later-phase split legible at a
glance instead of item by item.

| Group | Destination | Phase 1 | Marker |
|---|---|---|---|
| **Overview** | Dashboard | ✅ live | — |
| | SUNIL Chat | disabled | `PHASE 2` |
| | Daily Brief | disabled | `PHASE 3` |
| **Work** | Tasks | disabled | `PHASE 2` |
| | Calendar | disabled | `PHASE 3` |
| | Emails | disabled | `PHASE 3` |
| | Support | disabled | `PHASE 4` |
| | Jira | disabled | `PHASE 4` |
| | Teams | disabled | `PHASE 4` |
| **Intelligence** | Agents | disabled | `PHASE 2` |
| | AI Teams | disabled | `PHASE 5` |
| | Workflows | disabled | `PHASE 3` |
| | Memory | disabled | `PHASE 2` |
| **Governance** | Approvals | disabled | `PHASE 2` |
| | Notifications | disabled | `PHASE 2` |
| | Activity Logs | disabled | `PHASE 2` |
| **Platform** | Integrations | disabled | `PHASE 3` |
| | LLM Providers | disabled | `PHASE 2` |
| | Model Routing | disabled | `PHASE 2` |
| | Usage | disabled | `PHASE 2` |
| | Settings | ✅ live | `MINIMAL` |
| | System Health | ✅ live | — |

Phase attributions are taken from the §1.3 exclusion table of `PHASE1_REQUIREMENTS.md`, not
invented. Where that table gives a range ("Phase 2/3"), the later phase is shown, because
over-promising is the failure mode this marker exists to prevent.

### 5.2 Sidebar composition

| Region | Height | Content |
|---|---|---|
| Brand | 64px (matches header) | `S.U.N.I.L` in `--sunil-type-eyebrow`, `--sunil-text-accent`, 12px `--sunil-panel-accent-w` rule beneath in `--sunil-accent-fill` with `--sunil-glow-xs` (the prototype's `.panel::before` motif) |
| Nav | `1fr`, scrolls | Groups and items |
| Footer | 64px | User chip, role, sign-out. On xs/sm also the clock and status pill |

Group header: 28px tall, padding `16px 12px 4px`, `--sunil-type-micro`, `--sunil-nav-group-fg`.
First group has no top padding.

### 5.3 Nav item — enabled

| Property | Value |
|---|---|
| Height | `--sunil-nav-item-h` (40px) |
| Padding | `0 var(--sunil-nav-item-pad-x)` (12px) |
| Icon | 18×18px, `currentColor`, `aria-hidden="true"` |
| Gap | `--sunil-nav-item-gap` (10px) |
| Label | `--sunil-type-body-sm` (13px) |
| Radius | `--sunil-nav-item-radius` (4px) |
| Element | `<a href>` inside `<li>` inside `<ul>` |

| State | Foreground | Background | Extra |
|---|---|---|---|
| Rest | `--sunil-nav-item-fg` | transparent | — |
| Hover | `--sunil-nav-item-fg-hover` | `--sunil-nav-item-bg-hover` | transition `--sunil-motion-hover` |
| Focus-visible | unchanged | unchanged | `outline: var(--sunil-focus-w) solid var(--sunil-focus-color); outline-offset: var(--sunil-focus-offset)` |
| Active (current page) | `--sunil-nav-item-fg-active` | `--sunil-nav-item-bg-active` | 2px left marker in `--sunil-nav-item-marker`, full item height, `--sunil-glow-xs`. `aria-current="page"` |
| Active + hover | `--sunil-nav-item-fg-active` | `--sunil-accent-tint-strong` | — |

Measured: active label `#22D3EE` on the active tint `#092535` = **8.73:1**.

### 5.4 Nav item — disabled destination (the treatment that matters)

This is the Gate 1 decision made visible. It has to communicate three things at once: the
destination exists, it is not available yet, and *when* it will be.

**Markup — deliberately not a link and not a button:**

```html
<li class="nav-item nav-item--unavailable">
  <span class="nav-item__icon" aria-hidden="true"><!-- icon --></span>
  <span class="nav-item__label">SUNIL Chat</span>
  <span class="nav-item__badge">Phase 2</span>
  <span class="sr-only">— not yet available</span>
</li>
```

| Decision | Rule | Why |
|---|---|---|
| No `<a>`, no `href` | It is a `<span>` inside `<li>` | FR-101: "none linking to a broken page". An `<a href="#">` is a broken page with extra steps |
| No `<button disabled>` | — | A disabled button is removed from the tab order *and* commonly skipped by AT heuristics; the item would vanish for some users |
| Not focusable | No `tabindex` | Nothing to activate. Keyboard users tab through 4 real destinations, not 22 dead ones |
| Discoverable by screen reader | Plain text in a list item | Browsing the nav list reads "SUNIL Chat, Phase 2, not yet available" |
| Not `aria-disabled` | — | `aria-disabled` on a non-interactive element is meaningless; the visible badge plus the `.sr-only` phrase carry the meaning |
| `cursor: not-allowed` | On hover | Cheap, unambiguous |
| No hover background, no colour change | — | Nothing happens because nothing can happen |

| Property | Value |
|---|---|
| Label colour | `--sunil-nav-item-fg-disabled` (`#6499AE`, **6.19:1** on the panel) |
| Icon opacity | `0.55` — icon only; **never** apply opacity to the label (it would silently change the measured contrast) |
| Badge | `--sunil-badge-*` tokens: 18px tall, 6px padding, 2px radius, `--sunil-type-micro`, fg `#9AC5D4` on bg `#092131` = **8.87:1** |
| Badge text | `PHASE 2` … `PHASE 5`, or `MINIMAL` for Settings |

> **Deliberately not dimmed to the point of decoration.** The instinct is to fade unavailable items
> to near-invisibility. That both fails contrast and makes the list feel broken. 6.19:1 with a
> badge reads as *"scheduled"*, not *"greyed out"* — which is the honest message.

**On the icon rail (`md`, 72px):** disabled items keep their icon at 0.55 opacity with a 6px
`--sunil-status-unknown` dot at the top-right of the icon box. Because rail items are not
focusable and a `title` tooltip is unreachable by keyboard, the rail must expose the label
another way: hovering shows a tooltip anchored right, and every rail item retains its `.sr-only`
label text. **The rail is a convenience, not the accessible path** — the drawer/expanded sidebar
is, and the toggle to expand is always available.

### 5.5 Permission-aware navigation (FR-101)

- An item the user lacks permission for is **hidden**, not disabled. "Disabled" means *not built
  yet*; "hidden" means *not yours*. Conflating them would tell a `viewer` that Settings is coming
  in a later phase.
- Hiding is presentation only. The API enforces independently (ET-2 step 2.6). No comment,
  variable name or code path in `apps/web` may suggest the UI is the control.
- If every item in a group is hidden, the group header is hidden too.

### 5.6 Mobile drawer (xs, sm)

| Property | Value |
|---|---|
| Width | `--sunil-shell-drawer-w` (288px) |
| Position | Fixed left, full height, `z-index: var(--sunil-z-sidebar)` |
| Backdrop | `--sunil-surface-scrim`, `z-index: var(--sunil-z-scrim)`, closes on click |
| Transition | `transform` only, `--sunil-motion-surface` (400ms). Never animate `width` or `left` |
| Open | `aria-expanded="true"` on the toggle; focus moves to the drawer's first focusable element |
| Focus trap | Yes, while open |
| Close | `Escape`, backdrop click, toggle, or activating any nav link. Focus returns to the toggle |
| Reduced motion | Transition duration collapses via the global token override; the drawer appears instantly |
| Body scroll | Locked while open |

---

## 6. Time zone — resolving the Melbourne defect (A-10, `CURRENT_ARCHITECTURE.md`)

**The defect.** `prototype/sunil-command-centre.html` line 199:

```js
new Date().toLocaleTimeString('en-AU', { hour12:false, timeZone:'Australia/Melbourne' })
```

The owner operates on `Australia/Hobart`. Melbourne and Hobart share an offset for most of the
year, which is exactly why this bug would survive casual testing and then be wrong during the
DST transition weeks and in every exported timestamp.

**The specification.**

1. **No component may call `toLocaleString` / `toLocaleTimeString` / `toLocaleDateString` without
   an explicit `timeZone` argument, and that argument always comes from the resolved setting.**
   This is a lint-enforceable rule (`no-restricted-syntax` on those calls without a `timeZone`
   property) and should be enforced, not trusted.
2. **Resolution order:** user preference (`user.settings.timezone`) → system setting
   (`system_settings['regional.timezone']`) → environment default → **`'Australia/Hobart'`**.
   The final fallback is a constant in one module, exported once, named `DEFAULT_TIMEZONE`.
3. **The browser's zone is never used silently.** Settings offers an explicit "Use this device's
   time zone (`<detected>`)" option; choosing it stores the resolved IANA name, not "auto".
4. **Storage is always UTC.** Formatting is a presentation concern and happens at the edge.
5. **Zone abbreviation is derived, never hard-coded.** The prototype prints the literal string
   `MELBOURNE · AEST`; Hobart is AEDT for part of the year. Derive it via
   `Intl.DateTimeFormat(locale, { timeZone, timeZoneName: 'short' })` and render the city name from
   the IANA identifier's last segment with underscores replaced.
6. **Every rendered timestamp carries the full value in `title`** — ISO 8601 with offset — so a
   user can always recover the unambiguous instant.
7. **A single `<TimeZoneProvider>` at the shell root supplies the resolved zone.** No page reads
   the setting directly; changing it in Settings re-renders every timestamp in the app without a
   reload.
8. **Test:** with the setting at `Australia/Hobart` and the host clock in UTC, on a date inside
   Australian DST, the header clock must show `AEDT` and an 11-hour offset. That single assertion
   catches every regression of this defect.

---

## 7. Authentication pages

Shared auth layout, used by sign-in, MFA and invitation acceptance:

| Property | Value |
|---|---|
| Background | `--sunil-bg` + `<SunilPresence state="idle" size="lg">` centred, `--sunil-z-canvas` |
| Vignette + scanlines | Present, `--sunil-z-ambience` |
| Card | 400px wide (100% − 32px below `sm`), centred, `--sunil-surface-solid` (**opaque — it sits over the canvas**), `1px solid var(--sunil-border-subtle)`, `--sunil-radius-6`, 32px padding, `--sunil-panel::before` accent bar retained |
| Card vertical position | Centred; `min-height: 100dvh` on the wrapper (`dvh`, not `vh` — mobile browser chrome) |
| Wordmark | `S.U.N.I.L` `--sunil-type-display-lg`, `--sunil-text-accent`, `--sunil-glow-lg var(--sunil-accent-glow)` |
| Subtitle | `Systems Utility & Neural Intelligence Liaison`, `--sunil-type-micro`, `--sunil-text-muted` |
| Card gap | 20px between wordmark block, form and footer |

`autocomplete` is mandatory on every auth field. Password managers are a security control, not a
convenience.

### 7.1 Sign-in (`/sign-in`)

**Fields**

| Field | Type | `autocomplete` | Label | Validation |
|---|---|---|---|---|
| Email | `email`, `inputmode="email"` | `username` | "Email" | Required; format checked on blur |
| Password | `password` | `current-password` | "Password" | Required; **no strength meter, no policy hints** — this is sign-in, not sign-up |

- Field height 44px, `--sunil-field-*` tokens, 16px vertical gap, labels **always visible** above
  the field (never placeholder-as-label), `--sunil-type-micro`, `--sunil-field-label-fg`.
- Password field has a show/hide toggle: 40×40px, inside the field, `aria-pressed`,
  `aria-label="Show password"` / `"Hide password"`. Toggling does **not** move focus.
- Submit: full-width primary button, 44px, `--sunil-type-action`, label `ACCESS`.
- **No "create account", "sign up" or "register" affordance anywhere** (FR-020). No social sign-in.
  A single line in the card footer reads: *"Access is by invitation only."*
- "Forgot password?" — **omitted in Phase 1.** No recovery flow exists and no mail transport exists
  (A-03); a link to nothing is worse than no link. If the owner wants it visible, it must read
  *"Password recovery is not available in Phase 1 — contact the system owner."* as static text.

**Four states**

| State | Presentation |
|---|---|
| **Empty** | Both fields blank, submit **enabled** (never disable a submit button pending validation — it hides the reason for the block). Focus is on the email field on mount |
| **Loading** | Submit shows an inline 16px spinner and the label `AUTHENTICATING`; button `aria-busy="true"`; both fields `readonly` (not `disabled` — disabled fields lose their accessible name in some AT); a 10s watchdog moves to the error state with "The server did not respond." |
| **Success** | No success message. Immediate navigation to the next step (shell, or `/sign-in/mfa`). Route change writes `"Signed in. Dashboard."` to `#live-polite` |
| **Error** | Single generic alert above the form: **"Sign-in failed. Check your email and password."** — identical text for wrong password, unknown email, disabled account and expired invitation (FR-022, FR-104). `role="alert"`, focus moves to the alert. Fields keep their values; the password field is cleared and re-focused |

**Rate-limit / lockout error (FR-029)** is the one differentiated message, because the user
genuinely cannot proceed and needs to know why: *"Too many attempts. Try again in N minutes."*
This is not an account-existence disclosure — the lockout applies regardless.

**Error alert styling:** `--sunil-status-danger-text` (`#FCA5A5`, 10.20:1) on
`--sunil-surface-raised`, `1px solid var(--sunil-border-danger)`, 12px padding, 4px radius, with a
16px warning glyph marked `aria-hidden`.

### 7.2 MFA / TOTP challenge (`/sign-in/mfa`)

Reached only after a correct password when the user is enrolled (FR-027). The session is **not**
established until this passes.

| Element | Spec |
|---|---|
| Heading | `<h1>` "Verification required", `--sunil-type-title` |
| Instruction | "Enter the 6-digit code from your authenticator app." `--sunil-type-body`, `--sunil-text-secondary` |
| Code input | **One `<input>`, not six boxes.** `inputmode="numeric"`, `pattern="[0-9]*"`, `maxlength="6"`, `autocomplete="one-time-code"`, `autofocus`. 56px tall, 24px `--sunil-type-display-sm`, `letter-spacing: 0.4em`, centred, `tabular-nums` |
| Auto-submit | On the 6th digit, after a 250ms settle. Manual submit button remains, always |
| Submit | `VERIFY`, full width, 44px |
| Secondary | Text button: "Use a recovery code instead" → swaps the input to `text`, `maxlength` per the code format, label "Recovery code", `autocomplete="off"` |
| Escape hatch | Text link "Cancel and sign out" — clears the partial authentication server-side |

> **Six separate boxes are rejected.** They break paste, break `one-time-code` autofill, break
> mobile keyboards, and create six tab stops for one value. A single tracked input looks identical
> and works.

**Four states**

| State | Presentation |
|---|---|
| **Empty** | Input focused and empty. Hint text below: "Codes refresh every 30 seconds." |
| **Loading** | Input `readonly`, button `aria-busy`, label `VERIFYING` |
| **Success** | Navigate to the shell; `"Verified. Dashboard."` to `#live-polite` |
| **Error** | "That code is not valid. Try the next code from your app." — identical for an invalid code and a replayed code (FR-027 audits the difference; the user is not told). `role="alert"`, input cleared and re-focused, `aria-invalid="true"`, border `--sunil-field-border-error`. After the configured failure threshold, the lockout message from §7.1 replaces it |

### 7.3 Invitation acceptance (`/invite/[token]`)

| State | Presentation |
|---|---|
| **Loading** | Card with a centred 24px spinner and "Checking invitation…". Never render the form before the token is validated |
| **Empty (valid token)** | Heading "Set your password". The invited email shown read-only as text (not an editable field). Password + confirm fields, `autocomplete="new-password"`. A **live password-policy checklist** (FR-104): each rule is a list item with a state icon and text, `aria-live="polite"` on the list, updating on input with a 300ms debounce. Submit `CREATE ACCESS` |
| **Success** | Full-card confirmation: "Your account is ready." + a `SIGN IN` button. **No auto-redirect** — the user just set a credential and should see it succeed |
| **Error** | Generic card, no form: **"This invitation link is not valid."** plus "Ask the system owner for a new invitation." Identical for consumed, expired and mutated tokens (FR-021, FR-104) — the page must not disclose whether the invitation ever existed |

Policy checklist rules render from the server-supplied policy, never hard-coded in the UI, so
FR-030's configurable minimum stays in one place.

---

## 8. Dashboard (`/`) — an honest empty foundation

**The design problem.** The prototype's dashboard is dense with connectors, a content queue,
priority tasks and four metric tiles — every one of them hard-coded (`window.SUNIL_DATA`). Phase 1
has none of that data and must not imply it does (A-09, NFR-019, architectural rule 7). Copying
the layout and filling it with placeholders would produce a screen that lies at a glance.

**The design response.** Keep the prototype's *spatial language* — centre stage, flanking panels,
a bottom bar — but let the empty regions be genuinely, visibly empty, and give the page one real
job: tell the owner what the platform can currently do and prove it with live data. The only live
data available in Phase 1 is system health, and that is exactly what the page shows.

### 8.1 Composition

```
xl / 2xl                                     xs / sm (single column, this order)
┌───────────────────────────────────────┐    1  Phase banner
│  Phase 1 banner (full width)          │    2  Presence + greeting
├──────────┬──────────────┬─────────────┤    3  Foundation status
│ Platform │              │ Not yet     │    4  Not yet available
│ status   │  PRESENCE    │ available   │    5  Where to go next
│ (live)   │  + greeting  │ (static)    │
│          │              │             │
├──────────┴──────────────┴─────────────┤
│  Where to go next (3 cards)           │
└───────────────────────────────────────┘
  320px      1fr             320px
  gap 24px
```

At `lg`: two columns (`1fr 320px`) with the presence block spanning the left column above the
platform-status panel. At `md` and below: one column in the order listed.

### 8.2 Phase banner — permanent, not dismissible

Full-width, 12px padding, `--sunil-surface-raised`, left border 2px `--sunil-status-warn`,
`--sunil-radius-6`.

> **Phase 1 — Foundation.** SUNIL is installed and secured, but has no assistant features yet.
> Sign-in, settings and system health work. Everything else in the navigation arrives in a later
> phase. **No business data is connected.**

`--sunil-type-body`, `--sunil-text-primary`. Not dismissible: NFR-019 says nothing mocked is
presented as complete, and a banner the user can hide is a banner that stops being true.

### 8.3 Presence block

- `<SunilPresence state="idle" size="md" />` (320px), centred.
- Below it, the state caption: `--sunil-type-micro`, `--sunil-text-muted`, e.g. `STATE · IDLE`.
  This is the visible half of the canvas's accessible status (`SUNIL_PRESENCE_SPEC.md` §8.3).
- Below that, a greeting line, `--sunil-type-body-sm`, `--sunil-text-emphasis`, on
  `--sunil-surface-scrim` with 8px padding and 4px radius (mandatory scrim over the canvas —
  `DESIGN_TOKENS.md` §5.4.3).
- **The greeting is generated client-side from the clock and the user's display name only**
  ("Good morning, Isuru."). It is not an assistant output and must not be styled as one. The
  prototype's `"All systems are operational."` clause is removed — Phase 1 cannot assert that, and
  the platform-status panel says it properly with real data.

### 8.4 Platform status panel (the only live-data panel)

Titled `PLATFORM STATUS`. Rows in the prototype's `.sysrow` form: lamp + name + right-aligned state.
Data from `GET /api/system-health`. Rows: `DATABASE`, `REDIS`, `API`, `WORKER`, `SCHEDULER`,
`PGVECTOR`. Footer link: "Full system health →".

### 8.5 "Not yet available" panel — replaces the fake content queue and task list

Titled `NOT YET AVAILABLE`. A plain list of the capability groups that are coming, with their
phase badge — the same vocabulary as the nav so nothing has to be learned twice. Static content,
no API call, no loading state, no skeleton (there is nothing to load).

This panel is doing real work: it is the difference between "the dashboard is empty because it is
broken" and "the dashboard is empty because the product is honest about its phase".

### 8.6 "Where to go next" — 3 cards

`Settings`, `System Health`, `Sign-out / sessions`. Each: title (`--sunil-type-eyebrow`,
`--sunil-text-heading`), one sentence (`--sunil-type-caption`, `--sunil-text-secondary`), whole
card is one link. 120px min height, `--sunil-panel-*` tokens. Focus ring on the card, not the text.

### 8.7 What must NOT appear on the Phase 1 dashboard

MRR / subscriber / ad-spend / ticket tiles (all fabricated in the prototype); a content queue; a
priority task list; connector lamps for Gmail / RevenueCat / Metricool / Meta Ads (they are not
SUNIL's integration targets and none is connected); a "Brief Me" button (voice is Phase 3, §1.3);
any chart; any number that is not sourced from `GET /api/system-health`.

---

## 9. Settings (`/settings`) — minimal

Two-column at `lg`+ (200px section nav / `1fr` content, 24px gap); stacked accordion below.
Section nav uses the same nav-item tokens with `aria-current="true"`.

| Section | Fields | Phase 1 |
|---|---|---|
| **Profile** | Display name (editable), Email (read-only, with "Contact the system owner to change this"), Role (read-only chip) | ✅ |
| **Regional** | **Time zone** (searchable select of IANA zones, default `Australia/Hobart`, plus "Use this device's time zone"), Time format (24-hour default — the prototype's `hour12:false`), Date format (`en-AU` default), live preview line showing the current time in the chosen zone | ✅ **This is where the Melbourne defect is closed** |
| **Security** | MFA status + Enrol / Disable, Recovery codes (Generate / Regenerate — shown once), Active sessions table (device, IP, last seen, current marker) with "Revoke all other sessions", Change password | ✅ |
| **Appearance** | Theme (single option "Dark", disabled select with the note "The light theme arrives with a later phase"), Motion (Follow system / Always reduce / Never reduce), Ambience (Scanlines on/off) | ✅ |
| **About** | App version, phase, build id, and a link to the Phase 1 limitations list | ✅ |

**Save model:** per-section save with an explicit `SAVE` button. **No autosave** — Phase 1 settings
include security-relevant values, and silent persistence of a security setting is a bad habit to
establish. Save is disabled only when the section is unmodified (a state the user caused and can
see), and the section shows an unsaved-changes marker.

**Four states, per section**

| State | Presentation |
|---|---|
| **Empty** | Not applicable to Profile/Regional/Appearance (always populated). For "Active sessions": impossible (there is always the current session), so the table renders one row and no empty state is needed. For "Recovery codes": empty state — "No recovery codes generated." + `GENERATE CODES` |
| **Loading** | Skeleton rows using `--sunil-skeleton-*`: label bars 80×11px, field bars 100%×44px, 3 per section, 16px gap, `aria-busy="true"` on the section, and a `.sr-only` "Loading settings". Skeleton shimmer is a 1200ms linear translate — **and is replaced by a static block under reduced motion** |
| **Success** | Inline confirmation beside the save button: 8px `--sunil-status-ok` lamp + "Saved" in `--sunil-type-micro`, auto-clearing after 4s. Written once to `#live-polite`. The saved values remain visible — **never** replace the form with a success screen |
| **Error** | Section-level alert above the fields (`role="alert"`, focus moved): "Could not save. <server message>." Field-level errors additionally set `aria-invalid="true"`, `aria-describedby` → the error text, and `--sunil-field-border-error`. Values are **not** discarded. A `RETRY` button re-submits the same payload |

**MFA enrolment sub-flow** (FR-027): QR code + manual secret shown **once**, on
`--sunil-surface-raised` with a 16px quiet zone around the QR (a QR on `#030712` with no quiet zone
does not scan). Manual key in `--sunil-type-body` with a copy button and 4-character grouping.
A verify field follows, then recovery codes are displayed once with `DOWNLOAD` and `COPY` and a
mandatory "I have saved these codes" checkbox before the flow can close.
**The secret and the recovery codes are never re-displayed** (FR-042: write-only semantics; the UI
offers only "replace" or "rotate").

---

## 10. System Health (`/system-health`)

Real data, real refresh, no fabrication. Source: `GET /api/system-health` (FR-091).

### 10.1 Composition

1. **Overall banner** — 72px, lamp + status word + "Last checked <relative time>" + `REFRESH`.
2. **Dependency grid** — `repeat(auto-fill, minmax(280px, 1fr))`, 16px gap. One card per
   dependency: `DATABASE`, `REDIS`, `PGVECTOR EXTENSION`, `API`, `WORKER`, `SCHEDULER`.
   Card: name (`--sunil-type-eyebrow`), lamp + state, latency in ms (`tabular-nums`), and a
   one-line detail. **No version strings, no connection strings, no host names** — FR-091 forbids
   exposing detail that aids an attacker, and that constraint is a UI constraint too.
3. **Queue panel** (FR-085) — a 5-column figure row: `WAITING`, `ACTIVE`, `COMPLETED`, `FAILED`,
   `DELAYED`, using the prototype's `.stat` tile form (`--sunil-type-display-sm` value,
   `--sunil-type-micro` label). Below it, the repeatable job keys as a plain list.
   **`FAILED` renders in `--sunil-status-danger` only when > 0**; a red zero is a false alarm.
4. **LLM providers panel** (FR-065) — one row per configured provider. Any provider without a
   credential shows `--sunil-lamp-unknown` and the literal words **`NOT CONFIGURED · UNVERIFIED`**.
   A persistent footnote: *"Provider adapters have not been verified against live endpoints in
   Phase 1."* Never `ONLINE`, never `HEALTHY`, never a green lamp, under any circumstance.

### 10.2 Refresh behaviour

- Auto-refresh every 15s, paused when `document.hidden`, with a visible toggle (`AUTO-REFRESH ON/OFF`).
- **Refresh never moves focus and never reorders cards.** In-place value updates only.
- Under `prefers-reduced-motion`, auto-refresh defaults to **off** with a manual `REFRESH` button —
  content that changes under you without warning is a motion problem as much as an animation is.
- Each refresh updates a `.sr-only` timestamp; only a *change of status* is announced to
  `#live-polite`.

### 10.3 Four states

| State | Presentation |
|---|---|
| **Empty** | Genuinely unreachable for the dependency grid (the set is fixed). For the queue panel: all-zero counts with the caption "No jobs have run yet." — an empty state, not a skeleton. For repeatable keys: "No repeatable jobs registered." |
| **Loading** | First load only: 6 skeleton cards at the real card dimensions (so nothing shifts when data lands), `aria-busy="true"`, `.sr-only` "Loading system health". Subsequent refreshes show a 2px indeterminate progress bar under the banner and **never** re-skeleton |
| **Success** | Data rendered; banner lamp reflects the worst dependency state |
| **Error** | Whole-page alert card: "Could not reach the health endpoint." + the HTTP status category (not the body) + `RETRY`. The dependency grid renders in an **unknown** state (`--sunil-lamp-unknown`, `NO SIGNAL`) rather than disappearing — a vanished card reads as "fine", which is the opposite of the truth. Auto-refresh backs off: 15s → 30s → 60s, capped |

---

## 11. Accessibility specification (NFR-016, WCAG 2.1 AA)

### 11.1 Keyboard order

Global order on every authenticated page:

1. Skip to main content
2. Skip to navigation
3. Drawer toggle *(xs/sm only)*
4. Brand / home link
5. Primary nav — **enabled items only**, in visual order
6. Sidebar footer: user menu, sign out
7. Header: system status pill, user menu
8. `main` content, in DOM order
9. Any in-page footer

DOM order **is** the visual order at every breakpoint. No `tabindex` greater than 0 anywhere. No
`order` / `flex-direction: row-reverse` / grid placement that separates the two, because that
divergence is invisible to the author and fatal to the user.

Auth pages: skip links → wordmark (not focusable) → first field → … → submit → footer links.

### 11.2 Focus

- `:focus-visible` only — no focus ring on mouse click, always on keyboard.
- `outline: 2px solid var(--sunil-focus-color); outline-offset: 2px`. Measured **13.36:1** against
  the panel and **10.89:1** against the active nav tint, comfortably over the 3:1 required by
  SC 1.4.11 for a focus indicator.
- **`outline: none` is permitted in exactly one place**: `<main tabindex="-1">` as a skip-link
  target. Anywhere else it is a review rejection.
- Focus is never trapped except in the mobile drawer and modal dialogs, and both restore focus to
  their trigger on close.
- Focus is moved deliberately in exactly four situations: skip-link activation, drawer open/close,
  an error alert appearing, and a route change (to `<main>`, which is then announced by name).

### 11.3 Forms

- Every input has a `<label for>`. Placeholders are never the label and never the only hint.
- Required fields: `required` + `aria-required="true"`, and the word "Required" in the label —
  an asterisk alone is not an accessible convention.
- Errors: `aria-invalid="true"`, `aria-describedby` → the error element, error text adjacent and in
  words. Border colour is corroboration, never the message (SC 1.4.1, SC 3.3.1).
- Error summary at the top of the form when more than one field fails, each entry a link to its field.
- `autocomplete` on every field with a defined token (SC 1.3.5).

### 11.4 Images, icons and decoration

- All icons are `aria-hidden="true"` and accompanied by text. There are **no icon-only controls**
  in Phase 1 except the drawer toggle and the password show/hide, both of which carry
  `aria-label`.
- The vignette and scanline layers are `aria-hidden="true"` and `pointer-events: none`.

### 11.5 Screen-reader treatment of the animated canvas

Specified in full in `SUNIL_PRESENCE_SPEC.md` §8.3. The shell's obligations:

- The `<canvas>` is `aria-hidden="true"` and outside the tab order (NFR-016: decorative).
- Its state is conveyed **twice** non-visually: the visible caption in §8.3 of this document, and
  one polite announcement per *changed* state through the shell's `#live-polite` region.
- The shell owns that region. `<SunilPresence>` must be mounted with `announce={false}` where the
  page already announces the same state, so one state change is never spoken twice.

### 11.6 Reduced motion

`prefers-reduced-motion: reduce` produces:

| Element | Behaviour |
|---|---|
| All CSS transitions/animations | Collapsed to 0.01ms by the global token override (`DESIGN_TOKENS.md` §3.3) |
| `<SunilPresence />` | Static single frame; no `requestAnimationFrame` loop at all (`SUNIL_PRESENCE_SPEC.md` §8) |
| Drawer | Appears/disappears without sliding |
| Skeleton shimmer | Static block, no travelling sheen |
| System Health auto-refresh | **Off by default**, manual refresh button |
| Header clock | Still ticks — it is information, not decoration |
| Scanlines | Retained (static), with a manual off switch in Settings → Appearance |

The Settings → Appearance "Motion" control **overrides** the media query in both directions, and
its default is "Follow system".

### 11.7 Target sizes and zoom

- Minimum interactive target **44×44px** on touch breakpoints (xs, sm). Where a control is visually
  smaller (the 8px lamp is not interactive; the password toggle is 40px), extend the hit area with
  padding or a pseudo-element rather than growing the visual.
- The layout must survive **200% browser zoom** at 1280px without horizontal scroll (SC 1.4.10:
  reflow at 320px equivalent). Consequence: the sidebar must collapse to the drawer based on
  viewport width in CSS pixels, which zoom already reduces — so no extra work if breakpoints are
  used and no `px`-locked outer container is introduced.
- **Text must survive `text-spacing` overrides** (SC 1.4.12): no fixed-height text containers. The
  40px nav item is a `min-height`, not a `height`.

### 11.8 Security constraints that are also UI constraints

- **No `innerHTML`, no `dangerouslySetInnerHTML`** anywhere (FR-031). The prototype builds its
  entire HUD with `innerHTML` — that pattern does not cross over. All rendering is via the
  framework's escaped interpolation.
- **No inline `<style>` or `<script>`** in rendered output; a strict CSP is in force. Token
  variables live in a stylesheet, not in a `style` attribute.
- **No secret, token or API key ever reaches a component prop, a data attribute, a URL, or
  `localStorage`** (FR-042, FR-105). Secret fields are write-only: after saving, the UI shows a
  masked fingerprint and offers only "Replace" or "Rotate", and never repopulates the input.
- Session state lives in the `httpOnly` cookie. The client keeps **no** copy of anything
  authentication-related in JavaScript-readable storage.

---

## 12. Deviation register (shell)

| Prototype behaviour | Phase 1 shell | Reason |
|---|---|---|
| Single `max-width:960px` breakpoint | Six-step mobile-first scale | A 22-item nav plus tables needs an intermediate rail; FR-101 names three specific widths to verify |
| `innerHTML` templating | Framework rendering | FR-031; `CURRENT_ARCHITECTURE.md` names this as the prototype's specific hazard |
| Hard-coded `Australia/Melbourne` | Resolved, configurable zone defaulting to `Australia/Hobart` | A-10; §6 |
| Hard-coded `MELBOURNE · AEST` label | Derived city + `timeZoneName:'short'` | Hobart observes AEDT |
| Metric tiles, content queue, task list, connector lamps | Removed; replaced with live platform status and an explicit "not yet available" panel | A-09, NFR-019 |
| "Brief Me" button, `speechSynthesis`, `sunil_brief.mp3` | Not built | Voice is Phase 3 (§1.3) |
| Greeting asserts "All systems are operational" | Greeting is name + time of day only | Phase 1 cannot assert it; the status panel proves it instead |
| Translucent panel everywhere | Translucent by default; **opaque** for the header, auth card, and anything over the canvas | Contrast on an animated backdrop is unmeasurable (`DESIGN_TOKENS.md` §5.4.3) |
| `.stat` bottom bar | Reused, but only on System Health for queue counts | It is a good component with no Phase 1 dashboard data to hold |

---

## 13. Component state matrix (the four-state contract)

Every component in Phase 1, with all four states. **A component is not accepted without all four**,
even where a state is "unreachable" — in that case the row states *why*, which is itself the design
decision.

| Component | Empty | Loading | Success | Error |
|---|---|---|---|---|
| Sign-in form | Blank fields, submit enabled, focus on email | Spinner + `AUTHENTICATING`, fields `readonly`, 10s watchdog | Navigate away; polite announcement | Generic alert, focus moved, password cleared |
| MFA challenge | Empty input focused, refresh hint | `VERIFYING`, input `readonly` | Navigate to shell | "Code not valid", input cleared + re-focused, `aria-invalid` |
| Invitation acceptance | Password + confirm + live policy list | "Checking invitation…" before any form renders | Confirmation card + `SIGN IN`; no auto-redirect | Generic "not valid" card, no form |
| Nav sidebar | Unreachable — the item list is static | Unreachable — no fetch | 4 enabled, 18 badged | If permissions fail to load: render the 4 Phase 1 items only and announce "Navigation limited" (never render everything as a fallback) |
| System status pill | Unreachable | `CHECKING`, unknown lamp | Lamp + word | `NO SIGNAL`, off lamp — never hidden |
| Header clock | Unreachable | `--:--:--` for the first tick, matching the prototype's initial markup | Ticking time + derived zone label | If the zone is invalid: fall back to `DEFAULT_TIMEZONE`, show it, and log — never render a blank clock |
| Dashboard phase banner | Static | Static | Static | Static — it has no data path, by design |
| Platform status panel | Unreachable (fixed row set) | 6 skeleton rows at final dimensions | Lamp rows with states | All rows `NO SIGNAL` + panel-level retry |
| "Not yet available" panel | Static | Static | Static | Static |
| "Where to go next" cards | Static | Static | Static | Static |
| `<SunilPresence />` | N/A | Renders immediately at `idle`; no loading state | idle / thinking / speaking | Canvas unsupported or context lost → static SVG fallback + caption (`SUNIL_PRESENCE_SPEC.md` §9) |
| Settings section | Recovery codes: "No recovery codes generated." | Skeleton labels + fields, `aria-busy` | Inline "Saved" lamp, values retained | Section alert, values retained, `RETRY` |
| Time zone select | Search with no matches: "No time zones match '<q>'." | Skeleton select | Live preview of current time | "Could not load time zones" + free-text IANA entry as the fallback path |
| Active sessions table | Unreachable (current session always present) | 3 skeleton rows | Rows + "current" marker | "Could not load sessions" + retry; **the revoke button is hidden while unknown**, never shown against stale data |
| MFA enrolment | Not enrolled: explainer + `ENROL` | "Generating secret…" | QR + manual key + verify field, shown once | "Could not start enrolment" — and no partial secret displayed |
| Recovery codes | "No recovery codes generated." | "Generating…" | 10 codes, copy/download, confirm checkbox | "Could not generate codes"; previous codes remain valid and this is stated |
| Dependency card | Unreachable (fixed set) | Skeleton at final dimensions | Lamp + state + latency | Unknown lamp + `NO SIGNAL` |
| Queue panel | All zeros + "No jobs have run yet." | Skeleton figures | Five counts + repeatable keys | "Queue status unavailable" inside the panel; the rest of the page still renders |
| LLM providers panel | "No providers configured." | Skeleton rows | `NOT CONFIGURED · UNVERIFIED` rows + footnote | "Could not load providers" |
| Button (all variants) | N/A | `aria-busy`, spinner replaces the leading glyph, label changes to the present participle, width **frozen** to prevent layout shift | Returns to rest; the *page* signals success, not the button | Returns to rest; the error appears in the alert region, never inside the button |
| Field (all types) | Placeholder = format example only, never the label | `readonly` + a 16px trailing spinner | Border returns to `--sunil-border-interactive` | `aria-invalid`, `--sunil-field-border-error`, message below via `aria-describedby` |
| Panel (generic) | Centred: 24px muted glyph, one-sentence explanation, optional single action. Minimum 120px tall so the layout does not jump when content arrives | Skeleton matching the final content shape, same height | Content | Inline alert inside the panel; the panel keeps its frame and title |

**Empty-state copy rules.** Say what is not there and why, in one sentence, in the product's voice
(terse, technical, no exclamation marks, no apology). Offer the next action only if one genuinely
exists. Never "Nothing here yet!" — in Phase 1, "yet" is doing load-bearing work and the phase
badge already carries it.

---

## 14. Handover checklist for the Frontend Engineer

- [ ] Every value comes from a token; a `grep` for `#`, `rgb(`, `px` outside the token file and
      layout primitives returns nothing unexpected.
- [ ] All 22 nav destinations render; exactly 4 are links; 18 are non-focusable badged spans; zero
      `href="#"`.
- [ ] The shell is verified at 1920px, 1280px and 390px: no horizontal scroll, no overlap (FR-101).
- [ ] Keyboard-only pass: sign-in → MFA → shell → every enabled nav item → settings save → sign out,
      with a visible focus ring at every stop and no trap outside the drawer.
- [ ] `toLocaleTimeString` / `toLocaleDateString` never appear without an explicit `timeZone`.
- [ ] The header clock renders `AEDT` and an 11-hour offset with the setting at `Australia/Hobart`
      on a DST date.
- [ ] No `innerHTML`, no `dangerouslySetInnerHTML`, no inline `style`/`script` (FR-031).
- [ ] Every component in §13 demonstrably reaches all four states (storybook, fixture or dev route).
- [ ] Automated a11y scan passes on `/sign-in`, `/sign-in/mfa`, `/invite/[token]`, `/`, `/settings`,
      `/system-health` (BL-806).
- [ ] Nothing on any screen states or implies that a Phase 2–7 capability exists (NFR-019).

---

## 15. Open items for the Delivery Manager

| # | Item | Recommendation |
|---|---|---|
| S-1 | "Forgot password?" is omitted from sign-in because no recovery path or mail transport exists (A-03). | Confirm with the owner. The alternative — a link that explains it is unavailable — is specified in §7.1 and can be enabled with one flag. |
| S-2 | The dashboard deliberately does not reproduce the prototype's populated look. The owner's first sight of "his" dashboard will be mostly empty. | Set the expectation at Gate 1 rather than at demo. §8 explains the reasoning; the phase banner makes it self-explanatory on screen. |
| S-3 | Disabled nav items are not focusable. Some reviewers expect everything visible to be reachable by Tab. | This is deliberate and argued in §5.4. If challenged, the fallback is `tabindex="0"` + `aria-disabled="true"` + `role="link"` — worse, because it adds 18 dead tab stops. |
| S-4 | This spec must be reviewed by someone other than its author before BL-502 begins. | Role boundary: I do not approve my own work. Route to the QA engineer (state coverage, a11y) and the Frontend Engineer (feasibility). |
