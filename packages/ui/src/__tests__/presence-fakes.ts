/**
 * Test doubles for `<SunilPresence />`'s environment.
 *
 * SUNIL_PRESENCE_SPEC.md §5.3: "Fake `requestAnimationFrame`/`performance.now` in the test;
 * do not use real timers." These fakes are the reason the controller takes a `PresenceEnv`
 * instead of reaching for globals — the cleanup assertions in FR-102 are then exact rather
 * than "wait a bit and hope".
 */
import type {
  PresenceColors,
  PresenceEnv,
  PresenceMediaQuery,
  PresenceSubscription,
} from "../presence/env.js";
import { fallbackPresenceColors } from "../presence/env.js";
import type { PresenceCanvas, PresenceContext, PresenceGradient } from "../presence/engine.js";

export interface FakeSubscription extends PresenceSubscription {
  disposed: boolean;
  readonly kind: string;
}

export class FakeEnv implements PresenceEnv {
  /** Callbacks the controller has scheduled but that have not run yet. */
  private queue: Array<{ handle: number; callback: (t: number) => void }> = [];
  private nextHandle = 1;
  private clock = 0;

  readonly rafCalls: number[] = [];
  readonly cancelCalls: number[] = [];
  readonly subscriptions: FakeSubscription[] = [];

  box = { width: 320, height: 320 };
  dpr = 2;
  hidden = false;
  reducedMotion = false;

  private motionListeners: Array<(matches: boolean) => void> = [];
  intersectionCallback: ((visible: boolean) => void) | null = null;
  resizeCallback: (() => void) | null = null;
  visibilityCallback: (() => void) | null = null;
  themeCallback: (() => void) | null = null;
  contextLossCallback: ((lost: boolean) => void) | null = null;

  track(kind: string, dispose: () => void): FakeSubscription {
    const subscription: FakeSubscription = {
      kind,
      disposed: false,
      dispose: () => {
        subscription.disposed = true;
        dispose();
      },
    };
    this.subscriptions.push(subscription);
    return subscription;
  }

  requestAnimationFrame(callback: (t: number) => void): number {
    const handle = this.nextHandle;
    this.nextHandle += 1;
    this.rafCalls.push(handle);
    this.queue.push({ handle, callback });
    return handle;
  }

  cancelAnimationFrame(handle: number): void {
    this.cancelCalls.push(handle);
    this.queue = this.queue.filter((entry) => entry.handle !== handle);
  }

  now(): number {
    return this.clock;
  }

  devicePixelRatio(): number {
    return this.dpr;
  }

  matchMedia(): PresenceMediaQuery | null {
    return new FakeMediaQuery(this);
  }

  /** Used by `FakeMediaQuery`; the listener list lives on the env so tests can fire it. */
  addMotionListener(onChange: (matches: boolean) => void): PresenceSubscription {
    this.motionListeners.push(onChange);
    return this.track("matchMedia", () => {
      this.motionListeners = this.motionListeners.filter((l) => l !== onChange);
    });
  }

  isDocumentHidden(): boolean {
    return this.hidden;
  }

  onVisibilityChange(callback: () => void): PresenceSubscription {
    this.visibilityCallback = callback;
    return this.track("visibilitychange", () => {
      this.visibilityCallback = null;
    });
  }

  observeResize(callback: () => void): PresenceSubscription {
    this.resizeCallback = callback;
    return this.track("ResizeObserver", () => {
      this.resizeCallback = null;
    });
  }

  observeIntersection(callback: (visible: boolean) => void): PresenceSubscription {
    this.intersectionCallback = callback;
    return this.track("IntersectionObserver", () => {
      this.intersectionCallback = null;
    });
  }

  observeTheme(callback: () => void): PresenceSubscription {
    this.themeCallback = callback;
    return this.track("MutationObserver", () => {
      this.themeCallback = null;
    });
  }

  observeContextLoss(callback: (lost: boolean) => void): PresenceSubscription {
    this.contextLossCallback = callback;
    return this.track("contextlost", () => {
      this.contextLossCallback = null;
    });
  }

  readColors(): PresenceColors {
    return fallbackPresenceColors();
  }

  measure(): { width: number; height: number } {
    return this.box;
  }

  /* ---- test controls ---- */

  /** Advance the clock and run every currently queued frame callback, `count` times. */
  advanceFrames(count: number, msPerFrame = 16): void {
    for (let i = 0; i < count; i += 1) {
      this.clock += msPerFrame;
      const pending = this.queue;
      this.queue = [];
      for (const entry of pending) entry.callback(this.clock);
    }
  }

  /** Advance the clock without running anything (a backgrounded tab). */
  advanceClock(ms: number): void {
    this.clock += ms;
  }

  setReducedMotion(value: boolean): void {
    this.reducedMotion = value;
    for (const listener of this.motionListeners) listener(value);
  }

  get pendingFrames(): number {
    return this.queue.length;
  }

  get lastHandle(): number {
    return this.nextHandle - 1;
  }
}

/** A live view of the env's reduced-motion flag, so toggling it mid-test is observable. */
class FakeMediaQuery implements PresenceMediaQuery {
  constructor(private readonly env: FakeEnv) {}

  get matches(): boolean {
    return this.env.reducedMotion;
  }

  subscribe(onChange: (matches: boolean) => void): PresenceSubscription {
    return this.env.addMotionListener(onChange);
  }
}

export interface RecordingCanvas extends PresenceCanvas {
  readonly ops: string[];
  readonly context: PresenceContext | null;
}

/** A canvas whose 2D context records the calls the draw loop makes. */
export function createRecordingCanvas(options: { contextAvailable?: boolean } = {}): RecordingCanvas {
  const ops: string[] = [];
  const gradient: PresenceGradient = {
    addColorStop() {
      ops.push("addColorStop");
    },
  };

  const context: PresenceContext = {
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 0,
    shadowColor: "",
    shadowBlur: 0,
    setTransform: () => ops.push("setTransform"),
    clearRect: () => ops.push("clearRect"),
    fillRect: () => ops.push("fillRect"),
    createRadialGradient: () => {
      ops.push("createRadialGradient");
      return gradient;
    },
    save: () => ops.push("save"),
    restore: () => ops.push("restore"),
    translate: () => ops.push("translate"),
    rotate: () => ops.push("rotate"),
    beginPath: () => ops.push("beginPath"),
    setLineDash: () => ops.push("setLineDash"),
    arc: () => ops.push("arc"),
    ellipse: () => ops.push("ellipse"),
    stroke: () => ops.push("stroke"),
    fill: () => ops.push("fill"),
  };

  const available = options.contextAvailable ?? true;
  return {
    width: 0,
    height: 0,
    ops,
    context: available ? context : null,
    getContext: () => (available ? context : null),
  };
}
