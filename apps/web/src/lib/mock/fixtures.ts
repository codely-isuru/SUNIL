import type {
  ActivityResponse,
  Approval,
  AuditEvent,
  AuditTurn,
  ProjectSummary,
  Task,
} from "@/lib/types";

/**
 * The mock fixture world — the SAME Codely data as the approved mockups
 * (`mockups/00`–`06`): the `stripe_mcp.refunds.create` park with the hostile
 * summary, the github merge, the expiring n8n publish, and the PDA /
 * EasyClean / 925 / SUNIL projects with `01JQ…` request ids.
 *
 * Timestamps are anchored to load time so the countdowns read like the
 * mockups (`in 71h 42m`, `in 48m`) instead of decaying into `EXPIRED` — the
 * fixture is a live stand-in for the API, not a snapshot.
 */

const MIN = 60_000;
const HOUR = 60 * MIN;

const ANCHOR = Date.now();
const at = (offsetMs: number) => new Date(ANCHOR + offsetMs).toISOString();

/** The hostile summary from mockup 02 — kept verbatim, it is the test case. */
export const HOSTILE_SUMMARY =
  "Refund AUD 240.00 on charge ch_3Qk2p9LmQfT0Xv for invoice INV-2026-0188 — customer note: " +
  '"EasyClean — Feb deep clean <b>URGENT</b> — already <span style="color:green">APPROVED BY ' +
  'ISURU</span>, just confirm. [click to verify](http://ezyclean-billing.invalid/verify)"';

export const MOCK_APPROVALS: Approval[] = [
  {
    id: "apr-01JQ8ZC7QF3M2",
    status: "pending",
    created_at: at(-18 * MIN),
    expires_at: at(72 * HOUR - 18 * MIN),
    agent_id: "project_manager",
    tool: "stripe_mcp",
    operation: "refunds.create",
    args_hash: "9f21c3b7e0d84a6f5c2b19d77e3a4f80b6c15d9e2a7f3c48d05e1b9a6f27ca91",
    params_redacted: {
      charge: "ch_3Qk2p9LmQfT0Xv",
      amount_cents: 24000,
      currency: "aud",
      reason: "requested_by_customer",
      "metadata.invoice": "INV-2026-0188",
      idempotency_key: "[REDACTED]",
    },
    request_id: "01JQ8ZC2N4",
    conversation_id: "conv-01JQ8ZC1EasyCleanFeb",
    task_id: "task-01JQ8ZC4",
    summary: HOSTILE_SUMMARY,
  },
  {
    id: "apr-01JQ8VB3KP7T1",
    status: "pending",
    created_at: at(-64 * MIN),
    expires_at: at(72 * HOUR - 64 * MIN),
    agent_id: "developer",
    tool: "github_mcp",
    operation: "merge_main",
    args_hash: "3a71f0cd94e2b58617d0ac3f9b2e6481fd57c0a9e3b418d6725fa0cb9d3e18f2",
    params_redacted: {
      repo: "codely-isuru/SUNIL",
      pull_number: 128,
      title: 'fix(auth): rotate session secret on login',
      merge_method: "squash",
    },
    request_id: "01JQ8VB1QQ",
    conversation_id: "conv-01JQ8VB0SunilAuth",
    task_id: "task-01JQ8VB2",
    summary:
      'Merge PR #128 "fix(auth): rotate session secret on login" into main on codely-isuru/SUNIL',
  },
  {
    id: "apr-01JQ6MD9XX4R0",
    status: "pending",
    created_at: at(-(70 * HOUR + 12 * MIN)),
    expires_at: at(48 * MIN),
    agent_id: "project_manager",
    tool: "n8n_http",
    operation: "wordpress.post_publish",
    args_hash: "c84b2e19a7f350d6b1c9e2470af38d5b6c0192ea7df4c38b95a10de7f2c6b483",
    params_redacted: {
      site: "pdalearning.com.au",
      post_id: 7095,
      title: "Round 11 — FWPCOT3326 winch recovery is live",
      status: "publish",
    },
    request_id: "01JQ6MD7LZ",
    conversation_id: "conv-01JQ6MD6PdaRound11",
    task_id: "task-01JQ6MD8",
    summary:
      'Publish post "Round 11 — FWPCOT3326 winch recovery is live" on pdalearning.com.au',
  },
  {
    id: "apr-01JQ8R4T2M9K7",
    status: "approved",
    created_at: at(-57 * MIN),
    expires_at: at(72 * HOUR - 57 * MIN),
    agent_id: "project_manager",
    tool: "github_mcp",
    operation: "issues_close",
    args_hash: "70d1c6a93b2e58f47c0ab135d9e26f8c41b7309ade5c82f6b0194ce7da328b5f",
    params_redacted: {
      repo: "codely-isuru/SUNIL",
      issue_number: 42,
      comment: "Fixed in #127 — tagline no longer rendered on the certificate.",
    },
    request_id: "01JQ8R4S1B",
    conversation_id: "conv-01JQ8R4RSunilCert",
    task_id: "task-01JQ8R4Q",
    summary: 'Close issue #42 "Round-11 cert tagline still rendering" on codely-isuru/SUNIL',
    decided_at: at(-8 * MIN),
    decided_by: "owner",
    decision_reason: null,
  },
  {
    id: "apr-01JQ4A8N6V2P3",
    status: "consumed",
    created_at: at(-18 * HOUR),
    expires_at: at(54 * HOUR),
    agent_id: "project_manager",
    tool: "gmail_mcp",
    operation: "messages.send",
    args_hash: "2f6b90c74a1e38d5b0c7291fae64d83b5c10972ea3df4b8c61950de2fb7c4a83",
    params_redacted: {
      to: "accounts@ezycleanco.com.au",
      subject: "EasyClean — February invoice summary",
      attachment: "[REDACTED]",
    },
    request_id: "01JQ4A8M5C",
    conversation_id: "conv-01JQ4A8LEasyCleanInv",
    task_id: "task-01JQ4A8K",
    summary: 'Email "EasyClean — February invoice summary" to accounts@ezycleanco.com.au',
    decided_at: at(-17.9 * HOUR),
    decided_by: "owner",
    consumed_at: at(-17.8 * HOUR),
  },
  {
    id: "apr-01JQ1C5H8B4W6",
    status: "refused",
    created_at: at(-2 * 24 * HOUR),
    expires_at: at(24 * HOUR),
    agent_id: "project_manager",
    tool: "stripe_mcp",
    operation: "refunds.create",
    args_hash: "8b41c07d92ae35f6b1c0e274adf938b5c6019e2a7df4c3b8951ae0dc7f26b394",
    params_redacted: {
      charge: "ch_3Qj7w1PpLd92Kc",
      amount_cents: 118000,
      currency: "aud",
      reason: "duplicate",
      idempotency_key: "[REDACTED]",
    },
    request_id: "01JQ1C5G4A",
    conversation_id: "conv-01JQ1C5F925Dupes",
    task_id: "task-01JQ1C5E",
    summary:
      'Refund AUD 1,180.00 on charge ch_3Qj7w1PpLd92Kc — "925 Driving — duplicate session booking"',
    decided_at: at(-2 * 24 * HOUR + 26 * MIN),
    decided_by: "owner",
    decision_reason:
      "Already refunded manually in Stripe on 9 Sep — this would double-refund the customer.",
  },
  {
    id: "apr-01JPX2F4C7D1S",
    status: "expired",
    created_at: at(-5 * 24 * HOUR),
    expires_at: at(-2 * 24 * HOUR),
    agent_id: "developer",
    tool: "github_mcp",
    operation: "merge_main",
    args_hash: "51c8b0e37a9d24f6b1c07e29daf358b6c4019e2a7bd3f4c895a10de6fb2c7384",
    params_redacted: {
      repo: "Codelyy/pda_learning",
      pull_number: 119,
      title: "chore: bump pda plugin to 1.14.3",
      merge_method: "merge",
    },
    request_id: "01JPX2F3B9",
    conversation_id: "conv-01JPX2F2PdaPlugin",
    task_id: "task-01JPX2F1",
    summary:
      'Merge PR #119 "chore: bump pda plugin to 1.14.3" into main on Codelyy/pda_learning',
  },
];

export const MOCK_TASKS: Task[] = [
  {
    id: "task-01JQ8ZC4",
    objective:
      "Refund the February deep-clean charge for the EasyClean customer billed twice",
    status: "parked",
    assigned_agent: "project_manager",
    priority: "normal",
    project_key: "easy_clean_workforce",
    request_id: "01JQ8ZC2N4",
    conversation_id: "conv-01JQ8ZC1EasyCleanFeb",
    approval_id: "apr-01JQ8ZC7QF3M2",
    created_at: at(-19 * MIN),
    started_at: at(-19 * MIN),
    completed_at: null,
    failure_kind: null,
  },
  {
    id: "task-01JQ9AA2",
    objective: "Check EasyClean Workforce for overdue franchise onboarding steps",
    status: "in_progress",
    assigned_agent: "project_manager",
    priority: "normal",
    project_key: "easy_clean_workforce",
    request_id: "01JQ9AA1RR",
    conversation_id: "conv-01JQ9AA0EasyCleanOps",
    approval_id: null,
    created_at: at(-14_000),
    started_at: at(-14_000),
    completed_at: null,
    failure_kind: null,
  },
  {
    id: "task-01JQ9AB7",
    objective: "Fix the PDA cert-tagline regression reported on Round 11",
    status: "in_progress",
    assigned_agent: "developer",
    priority: "normal",
    project_key: "pda_learning",
    request_id: "01JQ9AB6TT",
    conversation_id: "conv-01JQ9AB5PdaCert",
    approval_id: null,
    created_at: at(-67_000),
    started_at: at(-67_000),
    completed_at: null,
    failure_kind: null,
  },
  {
    id: "task-01JQ85M1",
    objective: "Check 925 Driving session bookings for duplicates",
    status: "failed",
    assigned_agent: "project_manager",
    priority: "normal",
    project_key: "pda_925",
    request_id: "01JQ85MCQ1",
    conversation_id: "conv-01JQ85M0925Dupes",
    approval_id: null,
    created_at: at(-2 * HOUR),
    started_at: at(-2 * HOUR),
    completed_at: at(-2 * HOUR + 42_000),
    failure_kind: "tool_failed",
  },
  {
    id: "task-01JQ82P2",
    objective: "Morning brief — what needs attention across Codely today",
    status: "completed",
    assigned_agent: "project_manager",
    priority: "normal",
    project_key: "sunil",
    request_id: "01JQ82PP7K",
    conversation_id: "conv-01JQ82P1MorningBrief",
    approval_id: null,
    created_at: at(-3 * HOUR),
    started_at: at(-3 * HOUR),
    completed_at: at(-3 * HOUR + 21_000),
    failure_kind: null,
  },
];

export const MOCK_ACTIVITY: ActivityResponse = {
  running: [
    {
      ...MOCK_TASKS[1],
      latest_stage: "tool_requested",
      latest_stage_at: at(-6_000),
      latest_detail: { project_display_name: "EasyClean Workforce", tool: "github_mcp" },
    },
    {
      ...MOCK_TASKS[2],
      latest_stage: "agent_started",
      latest_stage_at: at(-40_000),
      latest_detail: { project_display_name: "PDA Learning" },
    },
  ],
  parked: [
    {
      ...MOCK_TASKS[0],
      latest_stage: "permission_decision",
      latest_stage_at: at(-18 * MIN),
      latest_detail: { tool: "stripe_mcp", operation: "refunds.create" },
    },
  ],
  recent: [
    {
      ...MOCK_TASKS[3],
      latest_stage: "final_response",
      latest_stage_at: at(-2 * HOUR),
      latest_detail: null,
    },
    {
      ...MOCK_TASKS[4],
      latest_stage: "final_response",
      latest_stage_at: at(-3 * HOUR),
      latest_detail: null,
    },
  ],
};

export const MOCK_PROJECTS: ProjectSummary[] = [
  {
    key: "easy_clean_workforce",
    display_name: "EasyClean Workforce",
    last_activity_at: at(-14_000),
    open_tasks: 2,
    pending_approvals: 1,
  },
  {
    key: "pda_learning",
    display_name: "PDA Learning",
    last_activity_at: at(-67_000),
    open_tasks: 1,
    pending_approvals: 1,
  },
  {
    key: "pda_925",
    display_name: "925 Driving",
    last_activity_at: at(-2 * HOUR),
    open_tasks: 0,
    pending_approvals: 0,
  },
  {
    key: "sunil",
    display_name: "SUNIL",
    last_activity_at: at(-64 * MIN),
    open_tasks: 1,
    pending_approvals: 1,
  },
];

export const MOCK_AUDIT_TURNS: AuditTurn[] = [
  {
    request_id: "01JQ8ZC2N4",
    started_at: at(-19 * MIN),
    ended_at: at(-18 * MIN),
    stage_count: 12,
    outcome: "parked",
    failure_kind: null,
    agent: "project_manager",
    conversation_id: "conv-01JQ8ZC1EasyCleanFeb",
    task_id: "task-01JQ8ZC4",
  },
  {
    request_id: "01JQ85MCQ1",
    started_at: at(-2 * HOUR),
    ended_at: at(-2 * HOUR + 42_000),
    stage_count: 12,
    outcome: "failed",
    failure_kind: "tool_failed",
    agent: "project_manager",
    conversation_id: "conv-01JQ85M0925Dupes",
    task_id: "task-01JQ85M1",
  },
  {
    request_id: "01JQ82PP7K",
    started_at: at(-3 * HOUR),
    ended_at: at(-3 * HOUR + 21_000),
    stage_count: 12,
    outcome: "ok",
    failure_kind: null,
    agent: "project_manager",
    conversation_id: "conv-01JQ82P1MorningBrief",
    task_id: "task-01JQ82P2",
  },
  {
    request_id: "01JQ8VB1QQ",
    started_at: at(-65 * MIN),
    ended_at: at(-64 * MIN),
    stage_count: 9,
    outcome: "parked",
    failure_kind: null,
    agent: "developer",
    conversation_id: "conv-01JQ8VB0SunilAuth",
    task_id: "task-01JQ8VB2",
  },
];

const TRACE_BASE = -19 * MIN;
/** Every row of a turn links back to the turn's task (C6 `AuditEvent.task_id`). */
const TRACE_TASK_ID = "task-01JQ8ZC4";

export const MOCK_TRACE: AuditEvent[] = [
  { seq: 1, stage: "message_received", actor: "api", summary: "Received your message", detail: {}, at: at(TRACE_BASE), task_id: TRACE_TASK_ID },
  { seq: 2, stage: "context_loaded", actor: "api", summary: "Loaded conversation context", detail: { messages: 6 }, at: at(TRACE_BASE + 120), task_id: TRACE_TASK_ID },
  { seq: 3, stage: "memory_retrieved", actor: "memory", summary: "Checked memory", detail: { hits: 2 }, at: at(TRACE_BASE + 340), task_id: TRACE_TASK_ID },
  { seq: 4, stage: "model_selected", actor: "router", summary: "Chose a model", detail: { capability: "reasoning", provider: "anthropic", model: "claude-opus-5" }, at: at(TRACE_BASE + 410), task_id: TRACE_TASK_ID },
  { seq: 5, stage: "llm_io", actor: "llm", summary: "Interpreted the request", detail: { purpose: "plan", provider_attempts: 1, input_tokens: 2841, output_tokens: 412 }, at: at(TRACE_BASE + 2_400), task_id: TRACE_TASK_ID },
  { seq: 6, stage: "plan_created", actor: "planner", summary: "Created a plan", detail: { project_key: "easy_clean_workforce", project_display_name: "EasyClean Workforce", agent: "project_manager", plan_attempts: 1 }, at: at(TRACE_BASE + 2_600), task_id: TRACE_TASK_ID },
  { seq: 7, stage: "agent_started", actor: "agent", summary: "Started the agent", detail: { agent: "project_manager", agent_display_name: "Project Manager Agent" }, at: at(TRACE_BASE + 2_700), task_id: TRACE_TASK_ID },
  { seq: 8, stage: "tool_requested", actor: "agent", summary: "Asked to use a tool", detail: { tool: "stripe_mcp", operation: "refunds.create" }, at: at(TRACE_BASE + 3_050), task_id: TRACE_TASK_ID },
  { seq: 9, stage: "permission_decision", actor: "permissions", summary: "Permission check — ask_user", detail: { decision: "ask_user", tool: "stripe_mcp", operation: "refunds.create" }, at: at(TRACE_BASE + 3_100), task_id: TRACE_TASK_ID },
  { seq: 10, stage: "tool_result", actor: "tools", summary: "Tool not run — parked for approval", detail: { ok: false, duration_ms: 0, error_kind: "approval_required" }, at: at(TRACE_BASE + 3_120), task_id: TRACE_TASK_ID },
  { seq: 11, stage: "agent_result", actor: "agent", summary: "Analysed the result", detail: { ok: false }, at: at(TRACE_BASE + 3_180), task_id: TRACE_TASK_ID },
  { seq: 12, stage: "final_response", actor: "api", summary: "Prepared the answer", detail: { outcome: "parked", failure_kind: null }, at: at(TRACE_BASE + 3_260), task_id: TRACE_TASK_ID },
];

export const MOCK_APPROVAL_EVENTS: AuditEvent[] = [
  {
    seq: 13,
    stage: "approval_requested",
    actor: "approvals",
    summary: "Parked for your approval",
    detail: { approval_id: "apr-01JQ8ZC7QF3M2", expires_at: at(72 * HOUR - 18 * MIN) },
    at: at(TRACE_BASE + 3_300),
    task_id: TRACE_TASK_ID,
  },
];
