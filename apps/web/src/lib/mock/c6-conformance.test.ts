import { beforeEach, describe, expect, test } from "vitest";
import { mockActivity, mockAuditIndex, mockAuditTrace, mockListTasks, resetMockBackend } from "./backend";

/**
 * The mock layer is the only thing standing in for the API until Stream A
 * lands the routes, so it must be a *faithful* stand-in: if it serves a field
 * C6 does not freeze, every view built against it is built against fiction and
 * breaks on the day the flag flips to `api`.
 *
 * These assertions are transcribed from the FROZEN contract
 * `docs/contracts/C6-ops-reads-openapi.yaml` v1.0.0 (`required:` lists, and the
 * `latest_detail` three-key projection of `C6-ops-reads.md` §2.3). They are
 * deliberately EXACT-key, not subset: an extra key is the drift that matters
 * (the previous pass invented `AuditTurn.conversation_label`, which C6 does not
 * return).
 */

const TASK_KEYS = [
  "id",
  "objective",
  "status",
  "assigned_agent",
  "priority",
  "project_key",
  "request_id",
  "conversation_id",
  "approval_id",
  "created_at",
  "started_at",
  "completed_at",
  "failure_kind",
].sort();

const ACTIVITY_ITEM_KEYS = [...TASK_KEYS, "latest_stage", "latest_stage_at", "latest_detail"].sort();

const AUDIT_TURN_KEYS = [
  "request_id",
  "started_at",
  "ended_at",
  "stage_count",
  "outcome",
  "failure_kind",
  "agent",
  "conversation_id",
  "task_id",
].sort();

const AUDIT_EVENT_KEYS = ["seq", "stage", "actor", "summary", "detail", "at", "task_id"].sort();

const keys = (o: object) => Object.keys(o).sort();

beforeEach(() => resetMockBackend());

describe("the mock layer serves exactly the frozen C6 shapes", () => {
  test("Task — every C6 key present, no extras, priority is a string", () => {
    const { tasks } = mockListTasks();
    expect(tasks.length).toBeGreaterThan(0);
    for (const task of tasks) {
      expect(keys(task)).toEqual(TASK_KEYS);
      // C6 §13.1: `tasks.priority`, V2 writes "normal" — a trusted STRING,
      // not the numeric rank the first pass assumed.
      expect(typeof task.priority).toBe("string");
    }
  });

  test("ActivityItem — Task plus the three latest_* keys, latest_detail projected to three keys", () => {
    const snapshot = mockActivity();
    const items = [...snapshot.running, ...snapshot.parked, ...snapshot.recent];
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect(keys(item)).toEqual(ACTIVITY_ITEM_KEYS);
      if (item.latest_detail) {
        // §2.3: other `detail` keys MUST NOT pass the projection — audit
        // detail may embed untrusted excerpts.
        for (const key of Object.keys(item.latest_detail)) {
          expect(["project_display_name", "tool", "operation"]).toContain(key);
        }
      }
    }
    expect(snapshot.recent.length).toBeLessThanOrEqual(20);
  });

  test("AuditTurn — the nine C6 keys only (no conversation_label)", () => {
    const { turns } = mockAuditIndex();
    expect(turns.length).toBeGreaterThan(0);
    for (const turn of turns) {
      expect(keys(turn)).toEqual(AUDIT_TURN_KEYS);
      expect(["ok", "failed", "parked", null]).toContain(turn.outcome);
    }
  });

  test("AuditTrace — events and approval_events both present, every event carries task_id", () => {
    const trace = mockAuditTrace("01JQ8ZC2N4");
    expect(Object.keys(trace).sort()).toEqual(["approval_events", "events"]);
    for (const event of [...trace.events, ...(trace.approval_events ?? [])]) {
      expect(keys(event)).toEqual(AUDIT_EVENT_KEYS);
    }
  });
});
