import type { CSSProperties } from "react";

/**
 * The one place untrusted strings are allowed on screen (C4 §4, spec §6.3).
 *
 * Three mechanisms, all required:
 *
 * 1. **Mechanical** — the value is rendered as a React child, i.e. a text
 *    node. There is no `dangerouslySetInnerHTML` in this repository and none
 *    may be added near this component; the value is never interpolated into
 *    `href`/`src`/`style`/`title`/`aria-*` either, so a hostile string cannot
 *    become a link, a tooltip or an accessible name.
 * 2. **Visual** — `surface-raised` ground, 1px border, 3px sand left bar,
 *    mono face: it *looks quoted*, visibly not SUNIL's own voice.
 * 3. **Labelled** — the provenance line above states where the text came from.
 *
 * The containment CSS (`unicode-bidi: plaintext`, `pre-wrap`,
 * `overflow-wrap: anywhere`) is applied as an inline style, not a utility
 * class, so a renamed or purged Tailwind class can never silently disable an
 * RTL-override defence or let a 500-char single token blow the layout out.
 */

const CONTAINMENT: CSSProperties = {
  unicodeBidi: "plaintext",
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
};

const CONTAINMENT_COMPACT: CSSProperties = {
  unicodeBidi: "plaintext",
  // A queue/dashboard row is one line: the value is clamped with an ellipsis
  // and the full string lives on the card. `pre-wrap` is kept so the style
  // contract is identical in both forms.
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
  display: "block",
  overflow: "hidden",
  textOverflow: "ellipsis",
  maxHeight: "1.5em",
};

export interface UntrustedTextProps {
  /** The untrusted string, exactly as received. */
  value: string;
  /** Provenance label rendered above the block (spec §6.3 rule 3). */
  label?: string;
  /** Single-line row form used by the queue and the dashboard hero. */
  compact?: boolean;
  className?: string;
}

export function UntrustedText({ value, label, compact = false, className }: UntrustedTextProps) {
  const base =
    "border border-border border-l-[3px] border-l-text-muted bg-surface-raised font-mono text-untrusted text-text-primary";
  const box = compact
    ? `${base} rounded-r-sm px-2 py-[3px] leading-[1.5]`
    : `${base} max-h-[16em] overflow-auto rounded-r-md px-3.5 py-3 leading-[1.6]`;

  return (
    <div className={className}>
      {label ? (
        <p className="mb-1.5 flex items-center gap-[7px] text-micro font-semibold uppercase tracking-micro text-text-muted">
          {label}
        </p>
      ) : null}
      <div data-untrusted="" style={compact ? CONTAINMENT_COMPACT : CONTAINMENT} className={box}>
        {value}
      </div>
    </div>
  );
}
