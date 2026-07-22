/**
 * The mount/unmount wiring, extracted so it can be tested without a DOM.
 *
 * `<SunilPresence />`'s effect is exactly `return mountPresence({...})`. That means the cleanup
 * asserted by `presence-render.test.tsx` is the same function React will call on unmount —
 * not a re-implementation of it. FR-102 asks for the absence of a leak to be *verifiable by
 * test*; this is the seam that makes the verification cover the real code path rather than a
 * lookalike.
 */
import { createPresenceController } from "./engine.js";
import type { PresenceController, PresenceControllerOptions } from "./engine.js";

export interface MountPresenceOptions extends PresenceControllerOptions {
  /** Receives the controller so the caller can drive it while mounted. */
  onController?: (controller: PresenceController) => void;
}

export function mountPresence(options: MountPresenceOptions): () => void {
  const controller = createPresenceController(options);
  options.onController?.(controller);
  return () => {
    controller.dispose();
  };
}
