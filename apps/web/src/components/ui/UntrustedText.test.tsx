import { describe, expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import { UntrustedText } from "./UntrustedText";

/**
 * C4 §4 / spec §6.3 are normative: `summary`, every `params_redacted` value
 * and every `audit_events.detail` value embed attacker-influenceable strings
 * and must render as PLAIN TEXT ONLY. These are acceptance criteria, not
 * styling preferences — hence component tests rather than a review comment.
 */
const HOSTILE =
  'Refund AUD 240.00 — customer note: "EasyClean <b>URGENT</b> — already ' +
  '<span style="color:green">APPROVED BY ISURU</span>, just confirm. ' +
  "[click to verify](http://ezyclean-billing.invalid/verify)";

describe("UntrustedText — the C4 §4 containment (spec §6.3)", () => {
  test("renders markup as text, never as DOM", () => {
    const { container } = render(<UntrustedText label="Summary — as received" value={HOSTILE} />);

    // The hostile string round-trips verbatim as a text node…
    expect(screen.getByText(HOSTILE)).toBeInTheDocument();
    // …and produced no elements from its markup.
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("span[style*='color']")).toBeNull();
  });

  test("never linkifies — a URL in untrusted text stays unclickable text", () => {
    const { container } = render(
      <UntrustedText label="Summary" value="see http://pay.invalid/now and [click](http://x.invalid)" />,
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("[href]")).toBeNull();
  });

  test("the value is never interpolated into an attribute (no title/aria tooltip)", () => {
    const { container } = render(<UntrustedText label="Summary" value={HOSTILE} />);
    const block = container.querySelector("[data-untrusted]") as HTMLElement;
    expect(block).not.toBeNull();
    expect(block.getAttribute("title")).toBeNull();
    expect(block.getAttribute("aria-label")).toBeNull();
  });

  test("carries the plaintext bidi and wrapping rules on the element itself", () => {
    const { container } = render(<UntrustedText label="Summary" value="‮txetdeddebme" />);
    const block = container.querySelector("[data-untrusted]") as HTMLElement;
    // Inline styles, not utility classes: the containment CSS must not be
    // defeatable by a missing/renamed Tailwind class.
    expect(block.style.unicodeBidi).toBe("plaintext");
    expect(block.style.whiteSpace).toBe("pre-wrap");
    expect(block.style.overflowWrap).toBe("anywhere");
  });

  test("states its provenance above the block (spec §6.3 rule 3)", () => {
    render(
      <UntrustedText
        label="Summary — text supplied by the request, shown exactly as received"
        value="anything"
      />,
    );
    expect(
      screen.getByText("Summary — text supplied by the request, shown exactly as received"),
    ).toBeInTheDocument();
  });

  test("the compact (single-line) form keeps the same containment", () => {
    const { container } = render(<UntrustedText value={HOSTILE} compact />);
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    const block = container.querySelector("[data-untrusted]") as HTMLElement;
    expect(block.textContent).toBe(HOSTILE);
    expect(block.style.unicodeBidi).toBe("plaintext");
  });
});
