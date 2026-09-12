import { describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DecisionBar } from "./DecisionBar";
import { StateConflictError } from "@/lib/api";
import type { Approval } from "@/lib/types";

const serverRow: Approval = {
  id: "apr-01JQ8ZC7QF3M2",
  status: "approved",
  created_at: "2026-09-11T09:41:06Z",
  expires_at: "2026-09-14T09:41:06Z",
  agent_id: "project_manager",
  tool: "stripe_mcp",
  operation: "refunds.create",
  args_hash: "9f21c3a91",
  params_redacted: {},
  request_id: "01JQ8ZC2N4",
  conversation_id: "conv-1",
  task_id: "task-01JQ8ZC4",
  summary: "Refund AUD 240.00",
  decided_at: "2026-09-11T09:59:12Z",
  decided_by: "owner",
};

function setup(
  overrides: Partial<React.ComponentProps<typeof DecisionBar>> = {},
) {
  const onSubmit = overrides.onSubmit ?? vi.fn().mockResolvedValue(serverRow);
  const onResolved = overrides.onResolved ?? vi.fn();
  render(
    <DecisionBar canDecide onSubmit={onSubmit} onResolved={onResolved} {...overrides} />,
  );
  return { onSubmit, onResolved };
}

describe("DecisionBar — arm then commit (spec §6.6–6.7)", () => {
  test("renders both decisions, Refuse left of Approve, Approve labelled in full", () => {
    setup();
    const buttons = screen.getAllByRole("button");
    const labels = buttons.map((b) => b.textContent);
    expect(labels.some((l) => l?.includes("Refuse"))).toBe(true);
    expect(screen.getByRole("button", { name: /approve this action/i })).toBeInTheDocument();
    // Destructive action away from the resting position on the primary.
    expect(labels.findIndex((l) => l?.includes("Refuse"))).toBeLessThan(
      labels.findIndex((l) => l?.includes("Approve this action")),
    );
  });

  test("pressing Approve arms it and sends nothing", async () => {
    const user = userEvent.setup();
    const { onSubmit } = setup();

    await user.click(screen.getByRole("button", { name: /approve this action/i }));

    expect(screen.getByRole("button", { name: /confirm approve/i })).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test("the shimmer/glow is on the armed control only", async () => {
    const user = userEvent.setup();
    const { container } = { container: document.body };
    setup();

    expect(container.querySelectorAll(".shimmer-sweep")).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: /approve this action/i }));
    const confirm = screen.getByRole("button", { name: /confirm approve/i });
    expect(confirm.className).toContain("shimmer-sweep");
    expect(confirm.className).toContain("shadow-glow-armed");

    // The other control is not armed and therefore never glows.
    const cancel = screen.getByRole("button", { name: /cancel/i });
    expect(cancel.className).not.toContain("shimmer-sweep");
  });

  test("confirming submits exactly once and hands the server's row back", async () => {
    const user = userEvent.setup();
    const { onSubmit, onResolved } = setup();

    await user.click(screen.getByRole("button", { name: /approve this action/i }));
    await user.click(screen.getByRole("button", { name: /confirm approve/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith("approve", undefined);
    await waitFor(() => expect(onResolved).toHaveBeenCalledWith(serverRow));
  });

  test("no optimistic status: while submitting the bar says Approving…, never Approved", async () => {
    const user = userEvent.setup();
    let release: (value: Approval) => void = () => {};
    const onSubmit = vi.fn(
      () => new Promise<Approval>((resolve) => {
        release = resolve;
      }),
    );
    setup({ onSubmit });

    await user.click(screen.getByRole("button", { name: /approve this action/i }));
    await user.click(screen.getByRole("button", { name: /confirm approve/i }));

    const submitting = await screen.findByRole("button", { name: /approving/i });
    expect(submitting).toBeDisabled();
    expect(screen.queryByText(/^Approved$/)).toBeNull();

    release(serverRow);
  });

  test("Escape disarms", async () => {
    const user = userEvent.setup();
    const { onSubmit } = setup();

    await user.click(screen.getByRole("button", { name: /approve this action/i }));
    await user.keyboard("{Escape}");

    expect(screen.getByRole("button", { name: /approve this action/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /confirm approve/i })).toBeNull();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test("R and A arm refuse/approve; a bare keystroke never commits", async () => {
    const user = userEvent.setup();
    const { onSubmit } = setup();

    await user.keyboard("a");
    expect(screen.getByRole("button", { name: /confirm approve/i })).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    await user.keyboard("{Escape}");
    await user.keyboard("r");
    expect(screen.getByRole("button", { name: /confirm refuse/i })).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test("refusing offers the reason box expanded and sends what was typed", async () => {
    const user = userEvent.setup();
    const { onSubmit } = setup();

    await user.click(screen.getByRole("button", { name: /^refuse$/i }));
    const reason = screen.getByLabelText(/reason/i);
    await user.type(reason, "Already refunded manually.");
    await user.click(screen.getByRole("button", { name: /confirm refuse/i }));

    expect(onSubmit).toHaveBeenCalledWith("refuse", "Already refunded manually.");
  });

  test("stale data disables both decisions and says why (§1.5 / Decision 11)", () => {
    setup({ canDecide: false, blockedReason: "Reconnect before deciding — this page may be out of date." });

    expect(screen.getByRole("button", { name: /approve this action/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^refuse$/i })).toBeDisabled();
    expect(
      screen.getByText(/reconnect before deciding — this page may be out of date/i),
    ).toBeInTheDocument();
  });

  test("a 409 renders the server's current_status verbatim and applies nothing", async () => {
    const user = userEvent.setup();
    const onSubmit = vi
      .fn()
      .mockRejectedValue(
        new StateConflictError("refused", "approval is refused, not pending"),
      );
    const { onResolved } = setup({ onSubmit });

    await user.click(screen.getByRole("button", { name: /approve this action/i }));
    await user.click(screen.getByRole("button", { name: /confirm approve/i }));

    expect(await screen.findByText(/this was already refused/i)).toBeInTheDocument();
    expect(screen.getByText(/current_status = refused/i)).toBeInTheDocument();
    expect(screen.getByText(/your decision was not applied/i)).toBeInTheDocument();
    expect(onResolved).not.toHaveBeenCalled();
  });

  test("an expiry race (409, expired) gets its own copy", async () => {
    const user = userEvent.setup();
    const onSubmit = vi
      .fn()
      .mockRejectedValue(new StateConflictError("expired", "expired at decision time"));
    setup({ onSubmit });

    await user.click(screen.getByRole("button", { name: /approve this action/i }));
    await user.click(screen.getByRole("button", { name: /confirm approve/i }));

    expect(
      await screen.findByText(/this approval expired before your decision landed/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/approval_expired/)).toBeInTheDocument();
  });

  test("a lost request says nothing changed and the retry re-sends the same decision", async () => {
    const user = userEvent.setup();
    const onSubmit = vi
      .fn()
      .mockRejectedValueOnce(new Error("Failed to fetch"))
      .mockResolvedValueOnce(serverRow);
    const { onResolved } = setup({ onSubmit });

    await user.click(screen.getByRole("button", { name: /^refuse$/i }));
    await user.click(screen.getByRole("button", { name: /confirm refuse/i }));

    expect(
      await screen.findByText(/your decision didn't reach sunil — nothing has changed/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(onResolved).toHaveBeenCalledWith(serverRow));
    expect(onSubmit).toHaveBeenNthCalledWith(2, "refuse", undefined);
  });
});
