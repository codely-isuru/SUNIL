"use client";

/**
 * The dashboard presence block — PORTAL_SHELL_SPEC.md §8.3.
 *
 * Three deliberate details:
 *   - `announce={false}`: the shell owns `#live-polite`, so one state change is never spoken
 *     twice (§11.5). The canvas still carries its always-present `.sr-only` sentence.
 *   - the VISIBLE caption (`STATE · IDLE`) is the sighted equivalent of that sentence. A user
 *     who cannot interpret an animation gets the same information as one who cannot see it.
 *   - the greeting sits on `--sunil-surface-scrim`, which is mandatory for text over the
 *     canvas (DESIGN_TOKENS.md §5.4.3), and it is generated from the CLOCK and the display
 *     name only. It is not an assistant output and must not be styled as one. The prototype's
 *     "All systems are operational." clause is removed: Phase 1 cannot assert that, and the
 *     platform-status panel says it properly, with real data.
 */
import { useEffect, useState } from "react";
import type { JSX } from "react";
import { PRESENCE_CAPTIONS, SunilPresence, zoneHour } from "@sunil/ui";
import { useTimeZone } from "../lib/time/TimeZoneProvider";
import { useSession } from "../lib/session/SessionProvider";

function greetingFor(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export function PresenceBlock(): JSX.Element {
  const { timeZone } = useTimeZone();
  const { displayName } = useSession();
  const [hour, setHour] = useState<number | null>(null);

  // Computed after mount: the server and the client must agree on first paint, and a
  // time-of-day greeting rendered on the server would be the server's idea of "now".
  useEffect(() => {
    setHour(zoneHour(new Date(), timeZone));
  }, [timeZone]);

  return (
    <div className="sunil-presence-block">
      <SunilPresence state="idle" size="md" announce={false} />
      <p className="sunil-type-micro sunil-fg-muted">{PRESENCE_CAPTIONS.idle}</p>
      <p className="sunil-greeting sunil-type-body-sm">
        {hour === null ? `Hello, ${displayName}.` : `${greetingFor(hour)}, ${displayName}.`}
      </p>
    </div>
  );
}
