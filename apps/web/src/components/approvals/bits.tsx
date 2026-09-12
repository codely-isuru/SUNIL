import { Icon } from "@/components/ui/Icon";
import { countdownTo, type Countdown } from "@/lib/time";

/**
 * The two small approval renderings shared by the queue, the dashboard hero
 * and the card, so a change to either propagates everywhere (§16.1).
 */

/**
 * `tool.operation` — **trusted**: both are registry keys from
 * `config/tools.yaml`, so they may be styled as an identifier (§5.2 col 2).
 * The tool half takes `gold-deep` (warmth without claiming interactivity).
 */
export function OperationIdentifier({
  tool,
  operation,
  size = "sm",
}: {
  tool: string;
  operation: string;
  size?: "sm" | "lg";
}) {
  return (
    <span
      className={`whitespace-nowrap font-mono ${
        size === "lg" ? "text-[1.0625rem]" : "text-data"
      } text-text-primary`}
    >
      <span className="text-gold-deep">{tool}</span>
      {size === "lg" ? " . " : "."}
      {size === "lg" ? <b>{operation}</b> : operation}
    </span>
  );
}

const TONE: Record<Countdown["level"], string> = {
  normal: "text-text-primary",
  warning: "text-warning",
  danger: "text-danger font-semibold",
  expired: "text-text-muted",
};

/**
 * The decision-TTL meter (§6.5): **text first**, never a bar alone. Under 12h
 * it is `warning`, under 1h `danger` with the alert icon. It re-renders on the
 * parent's 30s tick — not per second: a per-second timer on a 72-hour window
 * is noise and a needless repaint.
 */
export function ExpiryMeter({
  expiresAt,
  now,
  showExpiringSuffix = false,
}: {
  expiresAt: string;
  now: number;
  showExpiringSuffix?: boolean;
}) {
  const countdown = countdownTo(expiresAt, now);
  return (
    <span className={`whitespace-nowrap font-mono text-data ${TONE[countdown.level]}`}>
      {countdown.level === "danger" || countdown.level === "expired" ? (
        <Icon name="alert-triangle" size={12} className="mr-1 inline align-[-1px]" />
      ) : null}
      {countdown.text}
      {showExpiringSuffix && countdown.level === "danger" ? (
        <span className="ml-1.5 text-micro font-semibold uppercase tracking-micro text-danger">
          Expiring
        </span>
      ) : null}
    </span>
  );
}
