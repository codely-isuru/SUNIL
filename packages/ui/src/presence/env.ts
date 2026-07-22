/**
 * The seam that makes `<SunilPresence />` testable.
 *
 * SUNIL_PRESENCE_SPEC.md §5.3 requires the cleanup test to fake `requestAnimationFrame` and
 * `performance.now` rather than use real timers, and §9.2 forbids touching `window`,
 * `document` or `performance` outside an effect. Both fall out of one decision: the animation
 * controller never reaches for a global. Everything ambient arrives through `PresenceEnv`.
 *
 * `browserPresenceEnv()` is the production implementation. Tests pass a fake and can therefore
 * assert exactly what the spec asks: that no frame is scheduled under reduced motion, and that
 * after unmount nothing runs and every observer was disconnected.
 */
import { PRESENCE_COLOR_FALLBACKS, PRESENCE_COLOR_VARS } from "../tokens/tokens.js";
import type { PresenceColorRole } from "../tokens/tokens.js";

/** Anything created on mount that must be released on unmount (§5.2). */
export interface PresenceSubscription {
  dispose(): void;
}

export interface PresenceMediaQuery {
  readonly matches: boolean;
  subscribe(onChange: (matches: boolean) => void): PresenceSubscription;
}

/** Resolved presence colours as `{r,g,b}` triples (§7.4 — parsed once, cached). */
export interface Rgb {
  readonly r: number;
  readonly g: number;
  readonly b: number;
}

export type PresenceColors = Readonly<Record<PresenceColorRole, Rgb>>;

/** The measured CSS-pixel box of the host element. */
export interface PresenceBox {
  readonly width: number;
  readonly height: number;
}

export interface PresenceEnv {
  requestAnimationFrame(callback: (timestampMs: number) => void): number;
  cancelAnimationFrame(handle: number): void;
  /** Monotonic clock in milliseconds. */
  now(): number;
  /** Capped at 2 by the caller; this returns the raw value (§7.2). */
  devicePixelRatio(): number;
  /** `null` when the environment has no `matchMedia` (server, old engine). */
  matchMedia(query: string): PresenceMediaQuery | null;
  /** `document.hidden` (§5.4 condition 2). */
  isDocumentHidden(): boolean;
  onVisibilityChange(callback: () => void): PresenceSubscription;
  /** ResizeObserver on the host element — never `window.addEventListener('resize')` (§5.2). */
  observeResize(callback: () => void): PresenceSubscription;
  /** IntersectionObserver, threshold 0 (§5.4 condition 3). */
  observeIntersection(callback: (isIntersecting: boolean) => void): PresenceSubscription;
  /** MutationObserver on the document element's `data-theme` (§7.4). */
  observeTheme(callback: () => void): PresenceSubscription;
  /** `contextlost` / `contextrestored` on the canvas (§9). */
  observeContextLoss(callback: (lost: boolean) => void): PresenceSubscription;
  /** Reads `--sunil-presence-*` from the host's computed style; never called in the loop. */
  readColors(): PresenceColors;
  /** The host element's CSS-pixel box. */
  measure(): PresenceBox;
}

const NOOP_SUBSCRIPTION: PresenceSubscription = { dispose() {} };

/**
 * Parse `#rgb`, `#rrggbb` or `rgb()/rgba()` into a triple. Alpha is deliberately discarded:
 * the presence colours are used as bases for computed alphas inside the draw loop, and a token
 * that carried its own alpha would make those computations meaningless.
 */
export function parseRgb(value: string, fallback: Rgb): Rgb {
  const v = value.trim().toLowerCase();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/.exec(v);
  if (hex?.[1] !== undefined) {
    const d = hex[1];
    const full =
      d.length === 3
        ? `${d[0] ?? "0"}${d[0] ?? "0"}${d[1] ?? "0"}${d[1] ?? "0"}${d[2] ?? "0"}${d[2] ?? "0"}`
        : d;
    return {
      r: Number.parseInt(full.slice(0, 2), 16),
      g: Number.parseInt(full.slice(2, 4), 16),
      b: Number.parseInt(full.slice(4, 6), 16),
    };
  }
  const fn = /^rgba?\(([^)]+)\)$/.exec(v);
  if (fn?.[1] !== undefined) {
    const parts = fn[1]
      .split(/[\s,/]+/)
      .filter((p) => p !== "")
      .map((p) => Number.parseFloat(p));
    const [r, g, b] = parts;
    if (r !== undefined && g !== undefined && b !== undefined && Number.isFinite(r)) {
      return { r, g, b };
    }
  }
  return fallback;
}

/** The typed fallbacks from `tokens.ts`, parsed. Used when a CSS variable resolves empty (§9). */
export function fallbackPresenceColors(): PresenceColors {
  const black: Rgb = { r: 0, g: 0, b: 0 };
  return {
    point: parseRgb(PRESENCE_COLOR_FALLBACKS.point, black),
    arc: parseRgb(PRESENCE_COLOR_FALLBACKS.arc, black),
    marker: parseRgb(PRESENCE_COLOR_FALLBACKS.marker, black),
    glow: parseRgb(PRESENCE_COLOR_FALLBACKS.glow, black),
  };
}

/**
 * The production environment. Constructed inside a `useEffect`, so no global is touched during
 * server rendering (§9.2).
 */
export function browserPresenceEnv(host: HTMLElement, canvas: HTMLCanvasElement): PresenceEnv {
  const doc = host.ownerDocument;
  const win = doc.defaultView ?? globalThis.window;

  return {
    requestAnimationFrame: (callback) => win.requestAnimationFrame(callback),
    cancelAnimationFrame: (handle) => {
      win.cancelAnimationFrame(handle);
    },
    now: () => win.performance.now(),
    devicePixelRatio: () => win.devicePixelRatio || 1,
    matchMedia: (query) => {
      if (typeof win.matchMedia !== "function") return null;
      const mql = win.matchMedia(query);
      return {
        get matches() {
          return mql.matches;
        },
        subscribe(onChange) {
          const handler = (event: MediaQueryListEvent): void => {
            onChange(event.matches);
          };
          mql.addEventListener("change", handler);
          return {
            dispose: () => {
              mql.removeEventListener("change", handler);
            },
          };
        },
      };
    },
    isDocumentHidden: () => doc.hidden,
    onVisibilityChange: (callback) => {
      doc.addEventListener("visibilitychange", callback);
      return {
        dispose: () => {
          doc.removeEventListener("visibilitychange", callback);
        },
      };
    },
    observeResize: (callback) => {
      if (typeof win.ResizeObserver !== "function") return NOOP_SUBSCRIPTION;
      const observer = new win.ResizeObserver(() => {
        callback();
      });
      observer.observe(host);
      return {
        dispose: () => {
          observer.disconnect();
        },
      };
    },
    observeIntersection: (callback) => {
      if (typeof win.IntersectionObserver !== "function") return NOOP_SUBSCRIPTION;
      const observer = new win.IntersectionObserver(
        (entries) => {
          const entry = entries[entries.length - 1];
          if (entry) callback(entry.isIntersecting);
        },
        { threshold: 0 },
      );
      observer.observe(host);
      return {
        dispose: () => {
          observer.disconnect();
        },
      };
    },
    observeTheme: (callback) => {
      if (typeof win.MutationObserver !== "function") return NOOP_SUBSCRIPTION;
      const observer = new win.MutationObserver(() => {
        callback();
      });
      observer.observe(doc.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"],
      });
      return {
        dispose: () => {
          observer.disconnect();
        },
      };
    },
    observeContextLoss: (callback) => {
      const onLost = (event: Event): void => {
        event.preventDefault();
        callback(true);
      };
      const onRestored = (): void => {
        callback(false);
      };
      canvas.addEventListener("contextlost", onLost);
      canvas.addEventListener("contextrestored", onRestored);
      return {
        dispose: () => {
          canvas.removeEventListener("contextlost", onLost);
          canvas.removeEventListener("contextrestored", onRestored);
        },
      };
    },
    readColors: () => {
      const fallbacks = fallbackPresenceColors();
      const computed = win.getComputedStyle(host);
      const roles = Object.keys(PRESENCE_COLOR_VARS) as PresenceColorRole[];
      const resolved: Record<string, Rgb> = {};
      for (const role of roles) {
        const raw = computed.getPropertyValue(PRESENCE_COLOR_VARS[role]).trim();
        resolved[role] = raw === "" ? fallbacks[role] : parseRgb(raw, fallbacks[role]);
      }
      return resolved as unknown as PresenceColors;
    },
    measure: () => ({ width: host.clientWidth, height: host.clientHeight }),
  };
}
