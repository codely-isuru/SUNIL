"use client";

import type { ReactNode } from "react";

export interface ChatShellProps {
  topBar: ReactNode;
  /** The message list area — flex-1, scrollable (M1_CHAT_SPEC.md §2). */
  children: ReactNode;
  composer: ReactNode;
}

/**
 * Page-level layout only: `TopBar` + `MessageList` (flex-1, scrollable) +
 * `Composer` (fixed to the bottom of this shell). No nav in M1. `h-dvh`
 * (Tailwind 3.4) rather than `h-screen` so mobile browser chrome
 * (address bar / keyboard) doesn't clip the composer (§1.2).
 */
export function ChatShell({ topBar, children, composer }: ChatShellProps) {
  return (
    <div className="flex h-dvh flex-col bg-canvas">
      {topBar}
      <div className="flex flex-1 flex-col overflow-hidden">{children}</div>
      {composer}
    </div>
  );
}
