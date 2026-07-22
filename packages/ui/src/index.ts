/**
 * `@sunil/ui` — the SUNIL design system: tokens, shared components and `<SunilPresence />`.
 *
 * DAG position: `ui → core`, restricted to the `@sunil/core/types` and `@sunil/core/tokens`
 * subpaths. A dependency-cruiser rule enforces it: design tokens must not drag server schemas
 * (or Zod) into the client bundle. Importing the `@sunil/core` ROOT from this package is a
 * `lint:deps` failure — that is intentional, not a bug to route around.
 *
 * Stylesheets are exported as subpath entries because tsc does not emit CSS:
 *   `import "@sunil/ui/styles.css"`  → tokens + base + components, in that order
 *   `import "@sunil/ui/tokens.css"`  → tokens only
 *
 * Constraints honoured throughout: no data fetching, no API knowledge, no
 * `dangerouslySetInnerHTML` (FR-031 — the ESLint fence makes it an error), and no colour
 * literal outside `tokens/`.
 */
import type { PresenceState } from "@sunil/core/tokens";

export const PACKAGE_NAME = "@sunil/ui" as const;

/** Re-exported so `apps/web` gets the presence vocabulary from the component package. */
export type { PresenceState };

export const PRESENCE_STATES: readonly PresenceState[] = ["idle", "thinking", "speaking"];

/* ---- tokens ---- */
export * from "./tokens/tokens.js";
export * from "./tokens/css-contract.js";

/* ---- presence ---- */
export { SunilPresence } from "./presence/SunilPresence.js";
export type { SunilPresenceProps } from "./presence/SunilPresence.js";
export { PresenceFallback } from "./presence/PresenceFallback.js";
export { createPresenceController, tierForSize, pointCountForTier } from "./presence/engine.js";
export { mountPresence } from "./presence/mount.js";
export type { MountPresenceOptions } from "./presence/mount.js";
export type {
  PresenceCanvas,
  PresenceContext,
  PresenceController,
  PresenceControllerOptions,
  PresenceDiagnostics,
  PresenceFrameInfo,
  PresenceGradient,
  PresenceQuality,
  PresenceQualityTier,
} from "./presence/engine.js";
export {
  browserPresenceEnv,
  fallbackPresenceColors,
  parseRgb,
} from "./presence/env.js";
export type {
  PresenceBox,
  PresenceColors,
  PresenceEnv,
  PresenceMediaQuery,
  PresenceSubscription,
  Rgb,
} from "./presence/env.js";
export {
  ANNOUNCE_DEBOUNCE_MS,
  ARCS,
  MAX_DELTA_SECONDS,
  PRESENCE_CAPTIONS,
  PRESENCE_STATUS_SENTENCES,
  REDUCED_MOTION_T,
  STATE_PARAMS,
} from "./presence/constants.js";

/* ---- motion ---- */
export {
  MotionPreferenceProvider,
  useMotionPreference,
  useResolvedReducedMotion,
} from "./motion/MotionPreference.js";
export type { MotionPreference } from "./motion/MotionPreference.js";

/* ---- components ---- */
export { Panel } from "./components/Panel.js";
export { Button } from "./components/Button.js";
export type { ButtonProps, ButtonVariant } from "./components/Button.js";
export { Field } from "./components/Field.js";
export type { FieldProps } from "./components/Field.js";
export {
  Alert,
  Badge,
  EmptyState,
  Lamp,
  Skeleton,
  Spinner,
  SrOnly,
  StatTile,
} from "./components/primitives.js";
export type { LampState } from "./components/primitives.js";

/* ---- navigation ---- */
export { PrimaryNav } from "./nav/PrimaryNav.js";
export type { PrimaryNavProps } from "./nav/PrimaryNav.js";
export { NavIcon } from "./nav/icons.js";
export type { IconName } from "./nav/icons.js";
export {
  NAV_DESTINATION_COUNT,
  NAV_GROUPS,
  PHASE_1_ROUTES,
  limitedGroups,
  visibleGroups,
} from "./nav/destinations.js";
export type { NavDestination, NavGroup } from "./nav/destinations.js";

/* ---- time ---- */
export {
  DEFAULT_LOCALE,
  DEFAULT_TIMEZONE,
  detectDeviceTimeZone,
  formatClockTime,
  formatDateStamp,
  formatMinuteGranularity,
  formatRelativeTime,
  isValidTimeZone,
  isoWithOffset,
  resolveTimeZone,
  zoneAbbreviation,
  zoneCity,
  zoneHour,
  zoneLabel,
} from "./time/timezone.js";
export type { TimeFormatOptions, TimeZoneSources } from "./time/timezone.js";
