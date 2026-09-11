import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import DashboardPage from "./page";
import ApprovalsPage from "./approvals/page";
import ApprovalCardPage from "./approvals/[approval_id]/page";
import { HOSTILE_SUMMARY } from "@/lib/mock/fixtures";
import { resetMockBackend } from "@/lib/mock/backend";

/**
 * Smoke coverage for the three views the Gate-2 mockups specify in full
 * (00 dashboard, 01 queue, 02 card): they render against the mock fixture
 * world, show the fixture data, and log nothing to `console.error`.
 *
 * The console assertion is deliberate — "no console errors on the three main
 * views" is an exit criterion, and a React key/hydration warning is exactly
 * the kind of defect a human screenshot pass does not catch.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams("status=pending"),
  useParams: () => ({ approval_id: "apr-01JQ8ZC7QF3M2" }),
}));

let errors: unknown[][] = [];

beforeEach(() => {
  resetMockBackend();
  errors = [];
  vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
    errors.push(args);
  });
  vi.spyOn(console, "warn").mockImplementation((...args: unknown[]) => {
    errors.push(args);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the three mockup-complete views render against the mock API", () => {
  test("Dashboard (mockup 00) — hero count, compact quotation rows, section boxes", async () => {
    render(<DashboardPage />);

    expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Pending approvals")).toBeInTheDocument());

    // The one gold key figure: three pending in the fixture world. It is
    // aria-hidden (the count is announced by the rail badge's label instead),
    // so it is matched by its glow class, not by role.
    const keyFigure = document.querySelector<HTMLElement>("span.text-key");
    expect(keyFigure?.textContent).toBe("3");
    expect(keyFigure?.className).toContain("text-accent");
    // Hero rows carry the untrusted summary in the compact quotation pattern.
    const quoted = document.querySelectorAll("[data-untrusted]");
    expect(quoted.length).toBeGreaterThanOrEqual(3);
    // The hostile fixture summary is text, not markup, on the dashboard too.
    expect(document.querySelector("[data-untrusted] b")).toBeNull();
    // Every section box is present and navigable.
    for (const heading of ["Agent activity", "Tasks", "Projects", "Recent audit"]) {
      expect(await screen.findByText(heading)).toBeInTheDocument();
    }
    expect(screen.getAllByRole("link", { name: /open full view/i }).length).toBe(5);
    expect(errors).toEqual([]);
  });

  test("Approvals queue (mockup 01) — seven columns, one primary link per row, no decision buttons", async () => {
    render(<ApprovalsPage />);

    expect(await screen.findByRole("heading", { level: 1, name: "Approvals" })).toBeInTheDocument();
    const table = await screen.findByRole("table");
    expect(table).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")).toHaveLength(7);

    // Decision 4: a list may never decide an approval.
    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /refuse/i })).toBeNull();

    // The row's accessible name carries the whole row (§5.2).
    expect(
      await screen.findByRole("link", { name: /stripe_mcp\.refunds\.create.*review and decide/i }),
    ).toBeInTheDocument();
    expect(errors).toEqual([]);
  });

  test("Approval card (mockup 02) — containment, both clocks, decision bar", async () => {
    render(<ApprovalCardPage />);

    expect(await screen.findByRole("heading", { level: 1, name: "Approval" })).toBeInTheDocument();
    expect(await screen.findByText(HOSTILE_SUMMARY)).toBeInTheDocument();
    // Nothing in the hostile string was interpreted.
    expect(document.querySelector("[data-untrusted] b")).toBeNull();
    expect(document.querySelector("[data-untrusted] a")).toBeNull();

    // Provenance is stated, redaction is explained, both clocks are present.
    expect(
      screen.getByText(/summary — text supplied by the request, shown exactly as received/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/●●●●●●●● redacted/)).toBeInTheDocument();
    expect(screen.getByText(/expires in/i)).toBeInTheDocument();
    expect(screen.getByText(/approving runs this once, now/i)).toBeInTheDocument();

    // The decision lives here, with the params on screen.
    expect(screen.getByRole("button", { name: /approve this action/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^refuse$/i })).toBeInTheDocument();
    expect(errors).toEqual([]);
  });
});
