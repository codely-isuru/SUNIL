# `<SunilPresence />` — Component Specification (Phase 1)

_Owner: UI/UX Designer (Minions delivery team)_
_Status: **Developer-ready.** Blocks BL-503._
_Covers: FR-102, NFR-007, NFR-016_
_Source of truth for the animation: `prototype/sunil-command-centre.html`, lines 237–339 (read-only, A-15)_
_Depends on: `DESIGN_TOKENS.md`_

> This component is the product's identity. A "close enough" port will look wrong in a way nobody
> can articulate but everybody notices. §3 is therefore a line-by-line transcription of the
> prototype's maths with the constants named, so the port can be verified by comparison rather
> than by taste. §4 is the only place where new behaviour is introduced, and it is marked as such.

---

## 1. What it is

A `<canvas>` rendering a rotating fibonacci point-sphere inside three dashed HUD arcs and a tilted
elliptical orbital ring, with a radial core glow. It is SUNIL's presence indicator: the visual
proxy for whether the assistant is idle, working, or speaking.

**In Phase 1 nothing drives it.** There is no chat, no orchestrator and no voice (§1.3 exclusions),
so it renders `idle` on the dashboard and the auth pages. The three states must still be built and
prop-driven (FR-102), because the alternative — retrofitting states in Phase 2 — means re-tuning
the animation against a moving target.

**It is decorative.** Everything it communicates must also be available as text (§8.3). That is
not a concession; it is the reason a screen-reader user can use this product at all.

---

## 2. Public API

```ts
export type PresenceState = 'idle' | 'thinking' | 'speaking';
export type PresenceQuality = 'auto' | 'high' | 'medium' | 'low';

export interface SunilPresenceProps {
  /** Visual state. Prop-driven only — the component owns no state machine and
   *  starts no timers tied to real events (FR-102). Default: 'idle'. */
  state?: PresenceState;

  /** 'sm' 200px | 'md' 320px | 'lg' 440px | number = CSS px (square).
   *  Maps to --sunil-presence-size-*. Default: 'md'. */
  size?: 'sm' | 'md' | 'lg' | number;

  /** 0..1 speaking amplitude, for future voice output. Ignored unless
   *  state === 'speaking'. Undefined → the prototype's constant pulse. */
  level?: number;

  /** Point-count / effect tier. 'auto' picks from size and DPR. Default: 'auto'. */
  quality?: PresenceQuality;

  /** Freezes the loop without unmounting (e.g. the host tab is inactive,
   *  or a modal is over it). Default: false. */
  paused?: boolean;

  /** Emit state changes to the component's own polite live region.
   *  Set false when the host page already announces the same state
   *  (PORTAL_SHELL_SPEC.md §11.5). Default: true. */
  announce?: boolean;

  /** Overrides the accessible status sentence. Default: see §8.3. */
  label?: string;

  className?: string;

  /** Test/dev instrumentation only. Called once per rendered frame.
   *  MUST be tree-shaken or no-op in production builds. */
  onFrame?: (info: { frame: number; t: number; fps: number }) => void;
}
```

**Nothing else.** No `colors` prop (colours come from tokens, §7.4), no `speed` prop (speed is a
function of `state`), no `onClick` (it is not a control). Every prop added here is a prop that has
to keep working in Phase 2.

---

## 3. The animation, transcribed

All constants below are taken verbatim from the prototype. Where a name is given it is new; the
value is not.

### 3.1 Geometry setup (once per mount, and on any size change)

```
DPR   = min(window.devicePixelRatio || 1, 2)          // prototype: Math.min(dpr, 2)
W, H  = the element's CSS pixel box (square)
canvas.width  = round(W * DPR)
canvas.height = round(H * DPR)
ctx.setTransform(DPR, 0, 0, DPR, 0, 0)                // must be re-applied after every resize:
                                                      // assigning canvas.width resets the context
CX = W / 2
CY = H / 2 - OPTICAL_LIFT                             // prototype: H/2 - 14
R  = min(W, H) * 0.21                                 // SPHERE_RADIUS_RATIO
```

`OPTICAL_LIFT` is `14` in the prototype, tuned against a full viewport. Generalise to
`min(14, H * 0.045)` so it holds at 200px as well as 440px; at `md` (320px) the two agree exactly.
Never centre the sphere geometrically — the arcs and the orbital ring extend further below than
above, and the lift is what makes the composition sit right.

**Extent check:** the outermost arc is `2.02 R = 0.424 × min(W,H)`, so the full composition spans
`0.848 × min(W,H)` and always fits its box with ~7.6% margin on each side. Do not add padding.

### 3.2 The point sphere (built once, never rebuilt)

```
N  = 680                                              // POINT_COUNT (quality 'high')
GA = π × (3 − √5)                                     // golden angle ≈ 2.39996323
for i in 0 … N−1:
    y  = 1 − (i / (N − 1)) × 2                        // 1 → −1
    r  = sqrt(1 − y²)
    th = GA × i
    point = { x: cos(th) × r,  y,  z: sin(th) × r,  tw: random() × 2π }
```

`tw` is a per-point twinkle phase offset. **It is seeded once at construction and never
regenerated** — regenerating it on a resize or a state change makes the whole sphere flicker.

> For deterministic visual tests, the port must accept an injectable RNG (or a fixed seed in test
> builds). `Math.random()` in a render path is untestable, and this is the only randomness in the
> component.

### 3.3 Per-frame maths

```
t    += dt                                            // see §5.1 — NOT the prototype's fixed 0.016
rot   = t × ROT_SPEED                                 // idle: 0.28
pulse = 1 + PULSE_AMP × sin(t × PULSE_FREQ)           // idle: 1 + 0.015·sin(1.4t)
                                                      // speaking: 1 + 0.10·sin(9t)
cosR = cos(rot), sinR = sin(rot)
TILT = 0.42 rad, cosT = cos(TILT), sinT = sin(TILT)   // fixed axis tilt
```

**Draw order is load-bearing. It is: glow → arcs → points → orbital ring.** The ring is drawn last
so its marker sits over the sphere.

**1 — Core glow**

```
g = radialGradient(CX, CY, 0, CX, CY, R × 2.1)
g.stop(0, presenceGlow @ GLOW_ALPHA)                  // idle 0.12, speaking 0.20
g.stop(1, presenceGlow @ 0)
fillRect(CX − R×2.2, CY − R×2.2, R×4.4, R×4.4)
```

**2 — Three dashed HUD arcs** (`ctx.save()` / `translate(CX,CY)` / `rotate(t × spd)` / `restore()`,
`setLineDash([])` after the group):

| # | Radius | Line width | Dash | Speed | Alpha |
|---|---|---|---|---|---|
| 1 | `R × 1.55` | 1.4 | `[3, 9]` | `+0.22` | 0.50 |
| 2 | `R × 1.78` | 1.0 | `[16, 10]` | `−0.13` | 0.35 |
| 3 | `R × 2.02` | 0.8 | `[2, 5]` | `+0.07` | 0.25 |

The middle arc counter-rotates. That single negative sign is most of the reason the composition
reads as instrumentation rather than as a spinner. Do not "tidy" it.

**3 — Point projection, per point**

```
x1 =  p.x × cosR + p.z × sinR
z1 = −p.x × sinR + p.z × cosR
y1 =  p.y
y2 =  y1 × cosT − z1 × sinT                           // apply the tilt
z2 =  y1 × sinT + z1 × cosT
persp = 1 / (1 − z2 × 0.28)                           // PERSPECTIVE_STRENGTH
sx = CX + x1 × R × pulse × persp
sy = CY + y2 × R × pulse × persp
```

Sort ascending by `z2` (painter's algorithm, back to front), then per point:

```
front = (z2 + 1) / 2                                  // 0 (back) → 1 (front)
tw    = 0.75 + 0.25 × sin(t × TWINKLE_FREQ + p.tw)    // TWINKLE_FREQ idle 2.0
alpha = (0.10 + front × 0.75) × tw                    // 0.075 … 0.85
size  = 0.7 + front × 1.5                             // 0.7 … 2.2 CSS px
fill  = presencePoint @ alpha                         // #67E8F9 in the dark theme
if (front > 0.82) { shadowColor = presenceArc; shadowBlur = 7 }
```

**4 — Orbital ring**

```
save(); translate(CX, CY); rotate(−0.30)              // ORBIT_TILT
ellipse(0, 0, R × 1.34, R × 0.44, 0, 0, 2π)
stroke = presenceArc @ 0.4, lineWidth 1
oa = t × ORBIT_SPEED                                  // idle 0.9
marker at (cos(oa) × R×1.34, sin(oa) × R×0.44)
fill = presenceMarker (#A5F3FC), radius 3.4
shadowColor = presenceArc, shadowBlur 14
restore()
```

### 3.4 Constants table (for the port's `constants.ts`)

| Name | Value | Source |
|---|---|---|
| `POINT_COUNT` | 680 | `const N = 680` |
| `GOLDEN_ANGLE` | `π(3−√5)` | `Math.PI*(3-Math.sqrt(5))` |
| `SPHERE_RADIUS_RATIO` | 0.21 | `R = Math.min(W,H)*0.21` |
| `OPTICAL_LIFT` | 14 (generalised, §3.1) | `CY = H/2 - 14` |
| `AXIS_TILT` | 0.42 rad | `const TILT = 0.42` |
| `PERSPECTIVE_STRENGTH` | 0.28 | `1/(1 - z2*0.28)` |
| `POINT_ALPHA_BASE` / `_RANGE` | 0.10 / 0.75 | `(0.10 + front*0.75)` |
| `POINT_SIZE_BASE` / `_RANGE` | 0.7 / 1.5 | `0.7 + front*1.5` |
| `TWINKLE_BASE` / `_RANGE` | 0.75 / 0.25 | `0.75 + 0.25*sin(...)` |
| `FRONT_GLOW_THRESHOLD` | 0.82 | `if (front > .82)` |
| `POINT_SHADOW_BLUR` | 7 | `ctx.shadowBlur = 7` |
| `GLOW_RADIUS_RATIO` | 2.1 | `createRadialGradient(...,R*2.1)` |
| `ORBIT_RX` / `ORBIT_RY` | 1.34 R / 0.44 R | `ctx.ellipse(0,0,R*1.34,R*0.44,...)` |
| `ORBIT_TILT` | −0.30 rad | `ctx.rotate(-0.30)` |
| `ORBIT_ALPHA` | 0.4 | `rgba(34,211,238,.4)` |
| `MARKER_RADIUS` | 3.4 | `ctx.arc(mx,my,3.4,...)` |
| `MARKER_SHADOW_BLUR` | 14 | `ctx.shadowBlur = 14` |

---

## 4. The three states

Only `speaking` exists in the prototype (driven by a boolean). `idle` is the prototype's default.
**`thinking` is introduced by this specification** — FR-102 requires it and there is no source
value to extract.

| Parameter | `idle` (extracted) | `thinking` (**introduced**) | `speaking` (extracted) |
|---|---|---|---|
| `ROT_SPEED` | 0.28 | **0.62** | 0.28 |
| `PULSE_AMP` | 0.015 | **0.035** | 0.10 |
| `PULSE_FREQ` | 1.4 | **3.2** | 9.0 |
| `GLOW_ALPHA` | 0.12 | **0.16** | 0.20 |
| `TWINKLE_FREQ` | 2.0 | **3.6** | 2.0 |
| Arc speed multiplier | 1.0 | **2.4** | 1.0 |
| Arc alpha delta | 0 | **+0.08** (capped at 0.60) | 0 |
| `ORBIT_SPEED` | 0.9 | **1.8** | 0.9 |
| Second orbital marker | no | **yes**, trailing by 0.6 rad at 60% alpha and radius 2.2 | no |

**Design intent, so the three read as different things and not as three speeds:**

- **idle** — barely alive. A 1.5% breath every 4.5 seconds. If you notice it, it is too strong.
- **thinking** — *searching*. Everything rotates faster and the arcs scan; the sphere itself
  barely swells. The energy is in the instrumentation, not the core. Twin orbital markers imply
  work in flight.
- **speaking** — *emitting*. The core throbs at 10% amplitude, 9 rad/s; rotation stays at idle
  speed. The energy is in the core, not the instrumentation. This inversion is what makes the two
  active states distinguishable at a glance rather than by stopwatch.

### 4.1 State transitions

Parameters **interpolate**; they never jump. On a state change, cross-fade every numeric parameter
in the table over **400ms** with `--sunil-ease-standard` (`cubic-bezier(0.2,0,0,1)`), implemented
in the animation loop, not in CSS.

`t` itself is **never reset** on a state change — resetting it teleports the rotation and every
twinkle phase, which is instantly visible.

### 4.2 `level` modulation (speaking only)

When `state === 'speaking'` and `level` is a number in `[0,1]`:
`PULSE_AMP = 0.04 + 0.08 × clamp(level, 0, 1)`, smoothed with a one-pole filter
(`smoothed += (target − smoothed) × 0.15` per frame) so audio jitter does not strobe the sphere.
When `level` is undefined, `PULSE_AMP` is the prototype's constant `0.10`.

This prop exists now and does nothing in Phase 1. It is specified because Phase 3 voice output
will need it, and the alternative is a breaking API change to the product's signature component.

---

## 5. Loop, lifecycle and cleanup

### 5.1 The frame-timing defect in the prototype — fix it during the port

```js
let t = 0;
function frame(){ t += 0.016; /* … */ requestAnimationFrame(frame); }
```

`t` advances by a fixed 0.016 **per frame**, not per elapsed second. On the 60 Hz display it was
written for, that is right. On a 144 Hz laptop the entire animation runs **2.4× too fast**; on a
120 Hz phone, 2×; on a loaded machine dropping to 30 fps, half speed. This is a genuine defect
inherited from the source, and it must not be ported.

```
// required
const now = performance.now();
const dt  = Math.min((now - last) / 1000, 0.05);   // clamp: a backgrounded tab must not
last = now;                                        // teleport the sphere on return
t += dt;
```

The `0.05` clamp (50ms ≈ 3 frames at 60fps) is the difference between "resumed smoothly" and "the
sphere spun 400 degrees when I switched tabs back".

### 5.2 Mandatory cleanup (FR-102: "verifiable by test")

Every one of these is created on mount and **must** be released on unmount:

| Resource | Created | Released with |
|---|---|---|
| Animation frame | `requestAnimationFrame` | `cancelAnimationFrame(id)`; guard with a `disposed` flag so an in-flight callback cannot re-queue |
| Size observation | `ResizeObserver` on the host element | `observer.disconnect()` |
| Visibility | `document.addEventListener('visibilitychange')` | `removeEventListener` |
| Viewport | `IntersectionObserver` (§6.2) | `observer.disconnect()` |
| Reduced motion | `matchMedia('(prefers-reduced-motion: reduce)')` listener | `removeEventListener('change')` |
| Theme | `MutationObserver` on `data-theme` (§7.4) | `observer.disconnect()` |
| Context loss | `webglcontextlost`-equivalent: `contextlost` / `contextrestored` on the canvas | `removeEventListener` |

**Use `ResizeObserver`, not `window.addEventListener('resize')`.** The prototype listens to the
window because it *is* the window. A component inside a resizable shell (sidebar collapse, drawer
open, split pane) changes size without any window event, and a window listener also leaks a global
subscription per instance.

**The `disposed` guard matters more than the `cancelAnimationFrame`.** A frame callback already
scheduled will still run once after cancellation in some engines; without the guard it re-queues
and the loop never dies. That is the exact leak FR-102 asks to be proven absent.

### 5.3 The cleanup test

```
mount → advance 5 animation frames → assert onFrame called 5 times
unmount → advance 20 animation frames → assert onFrame call count unchanged
        → assert cancelAnimationFrame was called with the last returned id
        → assert every observer's disconnect() was called
```

Fake `requestAnimationFrame`/`performance.now` in the test; do not use real timers.

### 5.4 Pause conditions

The loop **must not run** when any of these hold. Each is checked before scheduling the next frame,
not inside it.

1. `paused === true`
2. `document.hidden === true`
3. The element is not intersecting the viewport (`IntersectionObserver`, threshold 0)
4. `prefers-reduced-motion: reduce` (§8) — the loop never starts at all
5. The element's box is `0 × 0` (a collapsed parent) — render nothing rather than dividing by zero

On resume, reset `last = performance.now()` **before** the first frame so `dt` is not the length of
the pause.

---

## 6. Performance

### 6.1 Budget

| Metric | Target | Ceiling | Source |
|---|---|---|---|
| Frame rate | 60 fps | **≥30 fps** | NFR-007 |
| Main-thread time per frame | ≤3.5 ms | 6 ms | Derived: one component at 'md' must leave headroom for the shell |
| CPU | must not pin a core | — | NFR-007 |
| Allocations per frame | **0** in steady state | — | See §6.3 |
| Canvas backing store | ≤ `880 × 880` | — | 440px 'lg' × DPR 2 |

Measured and recorded in the phase report on the reference machine (NFR-007), with the machine
spec stated (R-11).

### 6.2 Quality tiers

`quality: 'auto'` selects from the rendered CSS size:

| Tier | Condition | `POINT_COUNT` | Front glow | Arcs |
|---|---|---|---|---|
| `high` | ≥ 320px | **680** | on | 3 |
| `medium` | 240–319px | **420** | on | 3 |
| `low` | < 240px, or a sustained fps < 45 over 60 frames | **260** | **off** | 2 (drop arc 3) |

Below `high`, regenerate the point array with the new `N` (the fibonacci distribution is a function
of `N`; you cannot simply slice it). Regenerate on the resize path only, never per frame, and
preserve the twinkle phases by index where they exist.

The automatic downgrade to `low` is **one-way within a mount**. An oscillating quality tier is more
distracting than a low frame rate.

### 6.3 Required optimisations over the prototype's loop

The prototype allocates a fresh `drawn` array of 680 object literals every frame — at 60 fps that
is ~41,000 objects per second per instance, all garbage. It also sets and clears `shadowBlur`
around every one of the ~122 front-facing points, which is ~244 context state changes per frame.

| Issue | Required approach |
|---|---|
| Per-frame allocation | Pre-allocate typed arrays (`Float32Array` for `sx`, `sy`, `z`, and a `Uint16Array` of indices) at construction; write into them each frame |
| Sorting 680 objects | Sort the **index** array by `z`, not the objects. Better: because `z` changes smoothly, an insertion sort over the previous frame's order is near-O(n) — the array is almost sorted every frame |
| `shadowBlur` thrash | **Two passes.** Pass 1: all points with `front ≤ 0.82`, shadow off. Pass 2: set `shadowColor`/`shadowBlur` once, draw the rest, reset once. Two state changes per frame instead of ~244 |
| `fillStyle` string building | `rgba(...)` template strings are built 680× per frame. Quantise alpha to 64 steps and look the string up from a pre-built table |
| Gradient recreation | `createRadialGradient` is rebuilt every frame for the core glow. Rebuild it only when `R`, the glow alpha or the theme changes |

These are behaviour-preserving. If any of them changes the look, it has been implemented wrongly.

### 6.4 Multiple instances

Phase 1 renders at most one instance per page. The component must nonetheless survive two mounts
(auth card + background, say) without a shared-module global. If more than two are ever mounted,
the shell should share a single loop — **out of scope for Phase 1**, noted so nobody builds a
global registry now for a problem that does not exist yet.

---

## 7. Canvas sizing, DPR and theming

### 7.1 Element

```html
<div class="presence" style="width:320px; height:320px">
  <canvas aria-hidden="true"></canvas>
  <!-- accessible equivalent: §8.3 -->
</div>
```

- The wrapper owns the size (from `--sunil-presence-size-*` or the numeric `size` prop). The canvas
  is `display:block; width:100%; height:100%`.
- **Always square.** A non-square box would make `R = min(W,H) × 0.21` leave dead space; the shell
  never gives it one.
- The canvas element must carry no `width`/`height` HTML attributes in the markup — they are set
  in JS from the measured box, and a stale attribute causes a one-frame wrong-size flash.

### 7.2 DPR handling

```
DPR = min(window.devicePixelRatio || 1, 2)
```

Capped at 2 deliberately: a 3× phone at 'lg' would allocate a 1320² backing store for a decoration.
The cap is the prototype's own (`Math.min(window.devicePixelRatio||1, 2)`) and is retained.

**DPR can change at runtime** (dragging a window between monitors). Watch it with
`matchMedia('(resolution: ' + DPR + 'dppx)')` and re-run the resize path on change. The prototype
does not do this; on a two-monitor Windows dev machine it is immediately visible as a blurry
sphere, and the reference platform is Windows 11 (NFR-017).

**Resize path, in order:** measure box → if unchanged, return → set `canvas.width/height` →
`ctx.setTransform(DPR,0,0,DPR,0,0)` → recompute `CX`, `CY`, `R` → rebuild the glow gradient →
if the quality tier changed, rebuild the point array. Debounce to one execution per animation frame;
`ResizeObserver` can fire many times during a drag.

### 7.3 Sizes

| `size` | CSS px | Token | Used by |
|---|---|---|---|
| `sm` | 200 | `--sunil-presence-size-sm` | Reserved (Phase 2 chat header) |
| `md` | 320 | `--sunil-presence-size-md` | Dashboard (`PORTAL_SHELL_SPEC.md` §8.3) |
| `lg` | 440 | `--sunil-presence-size-lg` | Auth pages background |

Below `md` breakpoint, the shell passes `size={Math.min(280, viewportWidth - 64)}`.

### 7.4 Colours come from tokens, not from literals

The prototype hard-codes `rgba(34,211,238,…)`, `rgba(103,232,249,…)` and `#a5f3fc` inside the draw
loop. The port must read them:

```
on mount, and on any [data-theme] change:
  const cs = getComputedStyle(hostElement);
  point  = cs.getPropertyValue('--sunil-presence-point').trim();   // #67E8F9
  arc    = cs.getPropertyValue('--sunil-presence-arc').trim();     // #22D3EE
  marker = cs.getPropertyValue('--sunil-presence-marker').trim();  // #A5F3FC
  glow   = cs.getPropertyValue('--sunil-presence-glow').trim();    // #22D3EE
  → parse each once to {r,g,b}; cache; rebuild the alpha string table and the gradient
```

`getComputedStyle` is a layout read and must **never** be called inside the frame loop. Read on
mount, on theme change (`MutationObserver` on `document.documentElement`'s `data-theme`
attribute), and on resize. Fall back to the `tokens.ts` values if a variable resolves empty.

This is what makes a future light theme work on the canvas without touching this component
(`DESIGN_TOKENS.md` §8.6).

---

## 8. `prefers-reduced-motion` — required behaviour

**Not optional, not a reduced frame rate, not a slower rotation.** A rotating, pulsing, twinkling
object is exactly the class of animation the preference exists to suppress. Vestibular triggers do
not care that the motion is subtle.

### 8.1 What happens

| | Normal | `prefers-reduced-motion: reduce` |
|---|---|---|
| Animation loop | Runs | **Never starts.** No `requestAnimationFrame` is ever scheduled |
| Rendering | 60 fps | **One frame**, drawn at a fixed `t = 1.9` |
| State change | 400ms parameter cross-fade | **Instant redraw** of the single frame with the new state's parameters |
| Core glow | `GLOW_ALPHA` per state | Same per-state alpha — a static brightness difference is how state reads |
| Second orbital marker (`thinking`) | Animated | Drawn statically at its offset |
| Resize | Re-render each frame | Single redraw |
| CPU | Continuous | Zero after the first paint |

`t = 1.9` is chosen, not arbitrary: at that value the sphere's rotation shows a full point field,
the three arcs' dash phases are visibly offset from one another, and the orbital marker sits at
roughly the 4-o'clock position, clear of the sphere's silhouette. **Use exactly this value** so the
static composition is identical for every user and reviewable as a fixed image.

### 8.2 Reacting to the preference changing at runtime

Listen to `matchMedia('(prefers-reduced-motion: reduce)')`'s `change` event. Turning the preference
**on** must cancel the running loop within one frame. Turning it **off** starts the loop with
`t` continuing from `1.9` and `last = performance.now()`. A user toggling the OS setting must not
have to reload.

The Settings → Appearance "Motion" control (`PORTAL_SHELL_SPEC.md` §9) overrides the media query in
both directions; the component receives the resolved decision from a context provider rather than
reading `matchMedia` directly when that provider is present.

### 8.3 The accessible non-visual equivalent (NFR-016)

The canvas conveys state. A screen-reader user must receive that state. Both halves are required:

```html
<div class="presence">
  <canvas aria-hidden="true"></canvas>

  <!-- always rendered, always present in the accessibility tree -->
  <p class="sr-only" id="presence-status">SUNIL is idle.</p>

  <!-- announcement channel; only present when announce !== false -->
  <div role="status" aria-live="polite" aria-atomic="true" class="sr-only"></div>
</div>
```

| Requirement | Rule |
|---|---|
| Canvas | `aria-hidden="true"`, no `tabindex`, no `role`, no `aria-label`. It is decoration |
| Static description | A `.sr-only` sentence, **always in the DOM**, so a user browsing the page discovers the state without having to be present for a change |
| Change announcement | One polite announcement per *state change*, `aria-atomic="true"`. Never on mount — announcing "SUNIL is idle" the moment a page loads is noise |
| Debounce | 500ms. Rapid `thinking → speaking → thinking` flapping announces once, on settle |
| Duplication guard | When `announce={false}` the live region is not rendered at all and the host page owns the announcement (`PORTAL_SHELL_SPEC.md` §11.5). One state change is never spoken twice |
| Visible equivalent | The shell also renders a **visible** caption (`STATE · IDLE`) beneath the canvas. Sighted users who cannot interpret the animation get the same information |

**Status sentences** (overridable via `label`):

| State | Sentence |
|---|---|
| `idle` | "SUNIL is idle." |
| `thinking` | "SUNIL is working." |
| `speaking` | "SUNIL is speaking." |

Plain language, present tense, no jargon. "Working" rather than "thinking" because the user cares
what the system is doing, not what it is called internally.

`.sr-only` is the standard clip pattern — `position:absolute; width:1px; height:1px;
padding:0; margin:-1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; border:0`.
Never `display:none` and never `visibility:hidden`; both remove it from the accessibility tree.

---

## 9. Failure and fallback (the fourth state)

The four-state contract applies to this component too. `empty` and `loading` are genuinely
unreachable — it has no data and renders on its first frame — and that is the design decision, not
an omission. `success` is the three states in §4. `error` is real and must be built:

| Failure | Behaviour |
|---|---|
| `getContext('2d')` returns null | Render the static SVG fallback (§9.1). Log once. Never throw |
| `contextlost` event | Cancel the loop, render the SVG fallback immediately, listen for `contextrestored`; on restore, re-run the full resize path and restart |
| Host box is `0 × 0` | Render nothing, keep the observers alive, start on the first non-zero measurement |
| A CSS variable resolves empty | Fall back to the `tokens.ts` value for that token; never draw with `undefined` (which paints black and looks like a crash) |
| An exception inside the frame loop | Catch at the loop boundary, cancel the loop, switch to the SVG fallback, report once. **A decorative component must never take a page down** — and the pages it sits on are the sign-in page and the dashboard |

### 9.1 Static SVG fallback

A single inline `<svg>`: the sphere silhouette as ~120 static dots at the same fibonacci
projection (pre-computed at build time, not at runtime), the three arcs as dashed circles, the
orbital ellipse and its marker. Same tokens, same proportions, `aria-hidden="true"`. The `.sr-only`
status sentence and visible caption are unaffected — **the state is still communicated when the
graphics fail**, which is the whole point of §8.3.

This is also the asset used by the reduced-motion path if drawing a single canvas frame proves
awkward in a server-rendered context; the canvas single-frame render is preferred because it is
guaranteed identical to the animated version.

### 9.2 Server rendering

The component must render its wrapper, the `.sr-only` status and the visible caption on the server,
and mount the canvas on the client only. No `window`, `document` or `performance` access outside an
effect. First paint must show the wrapper at its final size so nothing shifts when the canvas
appears (this contributes to the CLS budget in `DESIGN_TOKENS.md` §7.3).

---

## 10. Acceptance criteria

Traced to FR-102 and NFR-016.

- [ ] `<SunilPresence state="idle" />` mounts and animates the point sphere, three HUD arcs and the
      orbital ring with **zero console errors or warnings**.
- [ ] Side by side with `prototype/sunil-command-centre.html` at the same size and a 60 Hz display,
      the idle animation is visually indistinguishable — same rotation rate, same twinkle, same
      arc dash pattern and directions, same marker orbit.
- [ ] `state` changes to `thinking` and to `speaking` are visibly distinct from each other and from
      `idle`, driven purely by the prop, with no internal timers tied to real events.
- [ ] `t` advances with elapsed time: the animation runs at the same visual speed at 60 Hz, 120 Hz
      and 144 Hz. (Verify by forcing `dt`.)
- [ ] On unmount, the loop stops and every observer disconnects — proven by the §5.3 test.
- [ ] Resizing the host element re-scales the canvas to DPR with no distortion, no blur, and no
      stretched sphere. Verified by resizing the sidebar, not just the window.
- [ ] With `prefers-reduced-motion: reduce`, **no `requestAnimationFrame` is ever called** and a
      single static frame is drawn. Verified by spying on `requestAnimationFrame`.
- [ ] The canvas is `aria-hidden`, is not in the tab order, and the state is available as text in
      the accessibility tree at all times.
- [ ] A state change produces exactly one polite announcement; mounting produces none;
      `announce={false}` produces none.
- [ ] ≥30 fps sustained at `size="lg"` on the reference machine without pinning a CPU core
      (NFR-007), with the measurement and the machine spec recorded in the phase report.
- [ ] Zero steady-state allocations per frame (verified in a memory profile: a flat sawtooth-free
      heap over 30 seconds).
- [ ] No colour literal appears in the component; all four colours resolve from tokens and follow a
      `data-theme` change.

---

## 11. Open items for the Delivery Manager

| # | Item | Recommendation |
|---|---|---|
| P-1 | `thinking` is designed, not extracted — there is no prototype reference for it. | Show the owner the §4 intent paragraph. It is the one part of SUNIL's visual identity being invented rather than inherited, and the owner should see it before it becomes canon. |
| P-2 | The prototype's fixed `t += 0.016` is a real defect that will make the animation run 2.4× fast on high-refresh displays. | Fix during the port (§5.1). Record it alongside the Melbourne timezone defect as a second inherited prototype bug found during design. |
| P-3 | `level` is specified but unused in Phase 1. | Keep it. It costs one optional prop now and prevents a breaking change to the signature component in Phase 3. |
| P-4 | This spec must be reviewed by someone other than its author before BL-503 begins. | Role boundary. Route to the Frontend Engineer for portability and to QA for the cleanup and reduced-motion assertions. |
