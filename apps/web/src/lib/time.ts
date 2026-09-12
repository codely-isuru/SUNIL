/**
 * Time rendering rules, in one place.
 *
 * Amendment A §A.6 rule 2 is normative: timestamps show **relative and
 * absolute together, at rest** — never absolute behind hover. §6.5 governs the
 * two countdowns (decision TTL and the post-approval consume grace) and their
 * `warning` (<12h) / `danger` (<1h) thresholds.
 */

export type UrgencyLevel = "normal" | "warning" | "danger" | "expired";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** `18 min ago`, `1h 4m ago`, `2d 22h ago`. */
export function relativeFromNow(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "—";
  const diff = now - then;
  const ago = diff >= 0;
  const abs = Math.abs(diff);

  let text: string;
  if (abs < MINUTE) text = "just now";
  else if (abs < HOUR) text = `${Math.floor(abs / MINUTE)} min`;
  else if (abs < DAY) {
    const h = Math.floor(abs / HOUR);
    const m = Math.floor((abs % HOUR) / MINUTE);
    text = m > 0 ? `${h}h ${m}m` : `${h}h`;
  } else {
    const d = Math.floor(abs / DAY);
    const h = Math.floor((abs % DAY) / HOUR);
    text = h > 0 ? `${d}d ${h}h` : `${d}d`;
  }

  if (text === "just now") return text;
  return ago ? `${text} ago` : `in ${text}`;
}

/** `09:41:06` — the absolute companion shown beside the relative value. */
export function clockTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("en-AU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

/** `11 Sep 2026, 09:41:06` — the full absolute form used on the card. */
export function fullTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.toLocaleDateString("en-AU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })}, ${clockTime(iso)}`;
}

/** `10:07 am` — the receipt/short form. */
export function shortTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d
    .toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit", hour12: true })
    .toLowerCase();
}

export interface Countdown {
  /** `in 71h 42m`, `in 48m`, `EXPIRED`. Text carries the meaning (§6.5). */
  text: string;
  /** Bare remaining figure (`71h 42m`) for compact columns. */
  figure: string;
  level: UrgencyLevel;
  remainingMs: number;
}

/** The decision-TTL countdown (§6.5, §5.2 col 6). */
export function countdownTo(iso: string, now: number = Date.now()): Countdown {
  const target = Date.parse(iso);
  if (Number.isNaN(target)) {
    return { text: "—", figure: "—", level: "normal", remainingMs: 0 };
  }
  const remainingMs = target - now;
  if (remainingMs <= 0) {
    return { text: "EXPIRED", figure: "EXPIRED", level: "expired", remainingMs };
  }

  const h = Math.floor(remainingMs / HOUR);
  const m = Math.floor((remainingMs % HOUR) / MINUTE);
  const figure = h > 0 ? `${h}h ${m}m` : `${m}m`;
  const level: UrgencyLevel =
    remainingMs < HOUR ? "danger" : remainingMs < 12 * HOUR ? "warning" : "normal";

  return { text: `in ${figure}`, figure, level, remainingMs };
}

/**
 * The post-approval consume grace (§6.5, Q3).
 *
 * Q3 is unresolved: the grace window is invisible to the API, so the spec's
 * stated default applies — **hardcode 1 hour and render the countdown from
 * `decided_at + 1h`**. This constant must change in lockstep with
 * `SUNIL_APPROVAL_CONSUME_GRACE_HOURS`; it is deliberately the only such
 * build-time coupling and is flagged in the task file.
 */
export const CONSUME_GRACE_HOURS = 1;

export function graceCountdown(decidedAt: string, now: number = Date.now()): Countdown {
  const decided = Date.parse(decidedAt);
  if (Number.isNaN(decided)) {
    return { text: "—", figure: "—", level: "normal", remainingMs: 0 };
  }
  const expiry = decided + CONSUME_GRACE_HOURS * HOUR;
  const remainingMs = expiry - now;
  if (remainingMs <= 0) {
    return { text: "EXPIRED UNUSED", figure: "EXPIRED UNUSED", level: "expired", remainingMs };
  }
  const inner = countdownTo(new Date(expiry).toISOString(), now);
  return { ...inner, text: `runs within ${inner.figure}` };
}

export function graceDeadline(decidedAt: string): string {
  return new Date(Date.parse(decidedAt) + CONSUME_GRACE_HOURS * HOUR).toISOString();
}

/** `0:14`, `1:07` — elapsed mm:ss / h:mm for a running task (§7.1). */
export function elapsedSince(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "—";
  const total = Math.max(0, Math.floor((now - then) / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}
