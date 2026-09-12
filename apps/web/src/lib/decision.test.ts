import { describe, expect, test } from "vitest";
import { decisionReducer, initialDecisionState, isDecisionBusy } from "./decision";
import type { Approval } from "./types";

const approvedRow: Approval = {
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

describe("decision state machine (spec §6.7 — arm then commit, never optimistic)", () => {
  test("starts idle", () => {
    expect(initialDecisionState).toEqual({ phase: "idle" });
  });

  test("arming a decision does not submit it", () => {
    const state = decisionReducer(initialDecisionState, { type: "arm", kind: "approve" });
    expect(state).toEqual({ phase: "armed", kind: "approve" });
    expect(isDecisionBusy(state)).toBe(false);
  });

  test("commit is ignored while idle — a decision can only be sent from the armed state", () => {
    const state = decisionReducer(initialDecisionState, { type: "commit" });
    expect(state).toEqual({ phase: "idle" });
  });

  test("commit from armed moves to submitting for the armed kind", () => {
    const armed = decisionReducer(initialDecisionState, { type: "arm", kind: "refuse" });
    const state = decisionReducer(armed, { type: "commit" });
    expect(state).toEqual({ phase: "submitting", kind: "refuse" });
    expect(isDecisionBusy(state)).toBe(true);
  });

  test("escape disarms, but an in-flight decision cannot be cancelled", () => {
    const armed = decisionReducer(initialDecisionState, { type: "arm", kind: "approve" });
    expect(decisionReducer(armed, { type: "disarm" })).toEqual({ phase: "idle" });

    const submitting = decisionReducer(armed, { type: "commit" });
    expect(decisionReducer(submitting, { type: "disarm" })).toEqual(submitting);
  });

  test("arming the other kind while armed switches the armed control", () => {
    const armed = decisionReducer(initialDecisionState, { type: "arm", kind: "approve" });
    expect(decisionReducer(armed, { type: "arm", kind: "refuse" })).toEqual({
      phase: "armed",
      kind: "refuse",
    });
  });

  test("success renders the server's returned row, not the pressed intent", () => {
    const submitting = decisionReducer(
      decisionReducer(initialDecisionState, { type: "arm", kind: "approve" }),
      { type: "commit" },
    );
    // Deliberately hostile case: the press was "approve", the server says refused.
    const serverRow: Approval = { ...approvedRow, status: "refused" };
    const state = decisionReducer(submitting, { type: "resolved", approval: serverRow });
    expect(state).toEqual({ phase: "decided", approval: serverRow });
    if (state.phase !== "decided") throw new Error("unreachable");
    expect(state.approval.status).toBe("refused");
  });

  test("409 renders the server's current_status and message verbatim", () => {
    const submitting = decisionReducer(
      decisionReducer(initialDecisionState, { type: "arm", kind: "approve" }),
      { type: "commit" },
    );
    const state = decisionReducer(submitting, {
      type: "conflict",
      currentStatus: "expired",
      message: "approval expired at decision time",
    });
    expect(state).toEqual({
      phase: "conflict",
      currentStatus: "expired",
      message: "approval expired at decision time",
    });
  });

  test("a network failure keeps the armed kind so the retry re-sends the same decision", () => {
    const submitting = decisionReducer(
      decisionReducer(initialDecisionState, { type: "arm", kind: "refuse" }),
      { type: "commit" },
    );
    const failed = decisionReducer(submitting, { type: "network_error" });
    expect(failed).toEqual({ phase: "network_error", kind: "refuse" });
    expect(decisionReducer(failed, { type: "commit" })).toEqual({
      phase: "submitting",
      kind: "refuse",
    });
  });

  test("a decided or conflicted card is terminal — no further arming", () => {
    const decided = decisionReducer(
      decisionReducer(
        decisionReducer(initialDecisionState, { type: "arm", kind: "approve" }),
        { type: "commit" },
      ),
      { type: "resolved", approval: approvedRow },
    );
    expect(decisionReducer(decided, { type: "arm", kind: "refuse" })).toEqual(decided);

    const conflict = decisionReducer(
      { phase: "submitting", kind: "approve" },
      { type: "conflict", currentStatus: "refused", message: "already refused" },
    );
    expect(decisionReducer(conflict, { type: "arm", kind: "approve" })).toEqual(conflict);
  });
});
