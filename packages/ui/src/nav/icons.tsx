/**
 * Navigation glyphs — 18×18, `currentColor`, `aria-hidden` (PORTAL_SHELL_SPEC.md §5.3, §11.4).
 *
 * Line-art built from a 24-unit grid, drawn with stroke rather than fill so a single icon
 * inherits the nav item's rest / hover / active / disabled colour without a second asset.
 * Every icon is decorative: it is always accompanied by its text label, and there are no
 * icon-only controls in Phase 1 except the drawer toggle and the password reveal (§11.4).
 */
import type { JSX } from "react";

export type IconName =
  | "dashboard"
  | "chat"
  | "brief"
  | "tasks"
  | "calendar"
  | "mail"
  | "support"
  | "board"
  | "teams"
  | "agents"
  | "aiTeams"
  | "workflows"
  | "memory"
  | "approvals"
  | "bell"
  | "logs"
  | "integrations"
  | "providers"
  | "routing"
  | "usage"
  | "settings"
  | "health"
  | "menu";

const PATHS: Readonly<Record<IconName, string>> = {
  dashboard: "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z",
  chat: "M4 5h16v11H9l-5 4z",
  brief: "M6 3h12v18H6zM9 8h6M9 12h6M9 16h4",
  tasks: "M4 6h3v3H4zM4 15h3v3H4zM10 7.5h10M10 16.5h10",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
  mail: "M3 6h18v12H3zM3 6l9 7 9-7",
  support: "M12 3a9 9 0 100 18 9 9 0 000-18zM9.5 9.5a2.5 2.5 0 113.5 2.3V14M12 17.5v.01",
  board: "M4 4h16v16H4zM9 4v16M15 4v16",
  teams: "M8 11a3 3 0 100-6 3 3 0 000 6zM2 20a6 6 0 0112 0M17 8a2.5 2.5 0 100 5 2.5 2.5 0 000-5zM15 20a5 5 0 017-4.6",
  agents: "M12 3v3M7 6h10v6a5 5 0 01-10 0zM9.5 17.5V21M14.5 17.5V21M9 10h.01M15 10h.01",
  aiTeams: "M7 8a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM17 8a2.5 2.5 0 100-5 2.5 2.5 0 000-5zM12 21a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM7 8v4h10V8M12 12v4",
  workflows: "M4 5h6v5H4zM14 14h6v5h-6zM7 10v6h7",
  memory: "M7 7h10v10H7zM4 10h3M4 14h3M17 10h3M17 14h3M10 4v3M14 4v3M10 17v3M14 17v3",
  approvals: "M4 12l5 5 11-11",
  bell: "M6 17V11a6 6 0 1112 0v6l2 3H4zM10 21h4",
  logs: "M4 5h16v14H4zM7 9h10M7 12h10M7 15h6",
  integrations: "M10 4h4v5h-4zM3 15h6v5H3zM15 15h6v5h-6zM12 9v3M6 15v-3h12v3",
  providers: "M5 6h14v4H5zM5 14h14v4H5zM8 8h.01M8 16h.01",
  routing: "M4 6h5l6 12h5M4 18h5M15 6h5",
  usage: "M4 20V10M10 20V4M16 20v-8M22 20H2",
  settings: "M12 9a3 3 0 100 6 3 3 0 000-6zM12 2l1.6 2.6 3-.5.6 3 2.6 1.6-1.4 2.7 1.4 2.7-2.6 1.6-.6 3-3-.5L12 22l-1.6-2.6-3 .5-.6-3L4.2 15l1.4-2.7L4.2 9.6l2.6-1.6.6-3 3 .5z",
  health: "M3 12h4l2-5 3 10 2.5-5H21",
  menu: "M4 7h16M4 12h16M4 17h16",
};

export function NavIcon({ name }: { name: IconName }): JSX.Element {
  return (
    <svg
      className="sunil-nav__icon"
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
