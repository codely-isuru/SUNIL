import type { SVGProps } from "react";

/**
 * The icon set, inlined as SVG paths (spec §12.3 names the Lucide glyph for
 * every status; the mockups carry the exact paths). Inline rather than a
 * dependency: seven views need ~18 glyphs, and an icon font/emoji is banned.
 *
 * Every icon is decorative here — `aria-hidden` is set on the `<svg>` and the
 * meaning is always carried by the adjacent uppercase text label (§12.3).
 */

export type IconName =
  | "dashboard"
  | "chat"
  | "shield-check"
  | "activity"
  | "list-checks"
  | "folder"
  | "file-search"
  | "settings"
  | "log-out"
  | "clock"
  | "check"
  | "check-check"
  | "x"
  | "ban"
  | "loader"
  | "pause"
  | "alert-triangle"
  | "info"
  | "refresh"
  | "chevron-right"
  | "copy"
  | "eye-off"
  | "shield"
  | "rows"
  | "arrow-left";

const PATHS: Record<IconName, React.ReactNode> = {
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="9" rx="1" />
      <rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
    </>
  ),
  chat: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
  "shield-check": (
    <>
      <path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V6l8-3 8 3z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  activity: <path d="M22 12h-4l-3 9L9 3l-3 9H2" />,
  "list-checks": (
    <>
      <path d="m3 17 2 2 4-4" />
      <path d="m3 7 2 2 4-4" />
      <path d="M13 6h8M13 12h8M13 18h8" />
    </>
  ),
  folder: <path d="M4 20V7a2 2 0 0 1 2-2h3l2 2h7a2 2 0 0 1 2 2v11z" />,
  "file-search": (
    <>
      <path d="M14 3v5h5" />
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <circle cx="11.5" cy="14.5" r="2.5" />
      <path d="m16 19-2.2-2.2" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M4 12h2M18 12h2M12 4v2M12 18v2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M17.7 6.3l-1.4 1.4M7.7 16.3l-1.4 1.4" />
    </>
  ),
  "log-out": (
    <>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="m16 17 5-5-5-5" />
      <path d="M21 12H9" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  check: <path d="m20 6-11 11-5-5" />,
  "check-check": (
    <>
      <path d="m18 6-8.5 8.5L6 11" />
      <path d="m22 10-7.5 7.5L13 16" />
    </>
  ),
  x: <path d="M18 6 6 18M6 6l12 12" />,
  ban: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m5.6 5.6 12.8 12.8" />
    </>
  ),
  loader: <path d="M21 12a9 9 0 1 1-3-6.7" />,
  pause: <path d="M10 4v16M14 4v16" />,
  "alert-triangle": (
    <>
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
      <path d="M12 9v4M12 17h.01" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 16v-5M12 8h.01" />
    </>
  ),
  refresh: (
    <>
      <path d="M21 12a9 9 0 1 1-3-6.7" />
      <path d="M21 3v6h-6" />
    </>
  ),
  "chevron-right": <path d="m9 18 6-6-6-6" />,
  copy: (
    <>
      <rect x="9" y="9" width="12" height="12" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </>
  ),
  "eye-off": (
    <>
      <path d="M9.9 4.2A10 10 0 0 1 12 4c7 0 10 8 10 8a18 18 0 0 1-2.4 3.5M6.6 6.6A18 18 0 0 0 2 12s3 8 10 8a10 10 0 0 0 5.4-1.6" />
      <path d="m2 2 20 20" />
    </>
  ),
  shield: (
    <>
      <path d="M12 2 3 6v6c0 5 3.8 8.9 9 10 5.2-1.1 9-5 9-10V6z" />
      <path d="M12 8v4M12 16h.01" />
    </>
  ),
  rows: <path d="M4 7h16M4 12h16M4 17h10" />,
  "arrow-left": (
    <>
      <path d="M19 12H5" />
      <path d="m12 19-7-7 7-7" />
    </>
  ),
};

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "children"> {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 16, className, ...rest }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      className={`shrink-0 ${className ?? ""}`}
      style={{
        stroke: "currentColor",
        fill: "none",
        strokeWidth: 1.75,
        strokeLinecap: "round",
        strokeLinejoin: "round",
      }}
      {...rest}
    >
      {PATHS[name]}
    </svg>
  );
}
