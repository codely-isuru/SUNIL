# ADR-004 — Plan validation: constrained decoding, then Pydantic, then a registry re-check, behind a `ValidatedPlan` type and a runtime guard

**Status:** **Accepted** (owner's architecture review, 2026-08-14) · **Amended once — see Amendment 1**
**Date:** 2026-08-14 · **Decider:** Solution Architect
**Context refs:** `ROADMAP.md` §25, §33 rules 2/3, `docs/ARCHITECTURE_V1.md` §6,
FR-060/061/062, NFR-040/041, **ET-7**.

## Context

This is the single most important control in M1. §25: *"Do not let free-form LLM output directly
trigger privileged actions."* ET-7: *"A fault-injected malformed/unvalidatable LLM plan output never
results in a tool call (zero ToolCall records created)."*

"Validate the plan" can be satisfied at wildly different strengths — from an `if "agents" in plan:`
check to a structural guarantee. ET-7 is graded on the strong reading, and so is the product's
credibility.

## Decision

Five layers, of which layers 1 and 5 are the load-bearing ones.

1. **The JSON Schema is generated from the live registries at runtime.** `agents`, `tools`,
   `project_key` and `steps[].action` are `enum`s built from `config/*.yaml`. Anthropic enforces
   `output_config.format` by **constrained decoding**, so an unregistered agent or tool name is not
   a reachable token sequence. The whitelist is part of the grammar, not a post-hoc filter.
   Two sentinels keep the schema inside the verified feature envelope: `project_key: "__unknown__"`
   (which is how ET-11 becomes structural) and `tool: "none"` (avoiding a nullable union type).
2. **The provider never guesses.** `LLMResponse.data` is populated only on a clean parse of a
   schema-requested response; anything else raises `StructuredOutputError`. No regex, no fence
   stripping, no partial parse. (NFR-041.)
3. **Pydantic** `PlanDraft`, `extra="forbid"` — enforces what JSON Schema cannot express under
   `output_config` (numeric bounds are unsupported there): `0.0 ≤ confidence ≤ 1.0`, non-empty and
   uniquely-identified `steps`.
4. **Registry re-check** — `validate_plan()` independently confirms every agent, tool, action and
   project exists *now*, and that the named agent is granted the named tools in
   `config/permissions.yaml`. Deliberately redundant with layer 1: layer 1 is the provider's
   guarantee, layer 4 is ours, and layer 4 is what still holds if a provider without constrained
   decoding is ever swapped in.
5. **An unforgeable type.** `ValidatedPlan.__init__` requires a module-private sentinel that only
   `validate_plan()` holds; constructing one anywhere else raises `TypeError`. Every downstream
   signature (`execute_plan`, `run_agent`, `ToolCallRequest`) demands the type. **There is no
   expressible code path from raw LLM output to a tool adapter.**

Bounded retry: 3 plan attempts (ADR-000 Q6), each persisted to `plans` with its validation errors and
fed back as corrective context. On exhaustion: outcome `plan_rejected`, stage 12 still emitted, zero
`tool_calls`.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Prompt-only ("respond with JSON matching this shape")** | The failure mode is a plausible-looking plan that names a tool you did not intend. Unacceptable for the control that guards every privileged action. |
| **JSON Schema validation only, no type guarantee** | Correct today, and one refactor away from a code path that takes `dict`. A convention that a reviewer must remember is weaker than a `TypeError`. |
| **Tool-use forcing (`tool_choice: {"type":"tool"}` with `input_schema`)** | A legitimate way to constrain output and the standard technique before structured outputs existed. Rejected because it *binds a tool to the planning call* — the very call that must not be able to invoke anything — and because `output_config` gives the same guarantee with none of that ambiguity. |
| **Pydantic only (no schema sent to the provider)** | Throws away constrained decoding, converting a guarantee into a retry loop, and makes malformed plans common enough to threaten NFR-060. |
| **`client.messages.parse()` with a Pydantic `output_format`** | Convenient, and would replace layers 2–3. Rejected for M1 because the fail-closed design needs its own explicit validation step regardless, and `create()` is the surface documented for the async client. Revisit in M3. |
| **Trusting the constrained-decoding guarantee alone (drop layers 3–5)** | The guarantee is real, but it is *one vendor's* guarantee. A cached-grammar bug, a provider swap, or a future local model (V2) would silently remove it. Defence in depth is cheap here. |

## Consequences

- The schema builder must be rebuilt whenever the registries change; it is a pure function of them,
  and `test_plan_schema_enums_match_registries` fails if they drift.
- The first plan call after a schema change pays a one-off grammar-compilation latency (compiled
  grammars are cached ~24 h). Accounted for in the §5 latency budget.
- The `_VALIDATOR_TOKEN` idiom looks unusual. It is commented in place and covered by
  `test_validated_plan_cannot_be_constructed_directly`, so it reads as deliberate rather than clever.
- Six named tests (`ARCHITECTURE_V1.md` §6.3) make this decision falsifiable. If any of them is
  deleted, the control is gone. *(Amendment 1 raises this to nine.)*

---

## Amendment 1 — the security claim is narrowed, and real runtime enforcement is added

**Date:** 2026-08-14 · **Origin:** the owner's architecture review, §7 · **Status:** Accepted
**Applies to:** decision layer 5 above. Layers 1–4 are unchanged. The *design* is unchanged.

### What was wrong

Layer 5 was described as "an unforgeable type" and the ADR asserted **"There is no expressible code
path from raw LLM output to a tool adapter."** That claim is too strong for Python and I should not
have made it:

- Type annotations are erased at runtime. `def execute_plan(plan: ValidatedPlan)` rejects nothing;
  it is documentation that a type checker reads and the interpreter ignores.
- `__slots__` prevents attribute creation, not construction. `object.__new__(ValidatedPlan)` bypasses
  `__init__` entirely and yields an instance that never met the validator.
- A module-private name is a naming convention. `plan_models._VALIDATOR_TOKEN` is importable by any
  module that wants it; the leading underscore stops linters, not code.

The design still does exactly what it was built to do — it makes the *accidental* path impossible
and the *deliberate* path obvious in review. That is worth having. But a claim of impossibility, in
the ADR that guards every privileged action, is the wrong kind of wrong: it invites a later reader
to skip a check because the type "already guarantees" it.

### What changes

1. **The words "unforgeable" and "no expressible code path" are withdrawn** from this ADR and from
   `ARCHITECTURE_V1.md` §6.1. The accurate claim is: *a `ValidatedPlan` is minted in exactly one
   place, and every privileged entry point verifies at runtime that it received one.*
2. **A runtime guard becomes part of the decision, not an implementation detail.**
   `require_validated_plan(obj)` raises `InvalidPlanExecution` unless `isinstance(obj, ValidatedPlan)`,
   and it is the first statement of `execute_plan()`, of the agent runner, and of
   `ToolManager.execute()`. Three call sites, one function, one test each.
3. **Privilege travels on trusted execution metadata, not on a type alone.** `ExecutionMetadata`
   (`validated_plan_id`, `request_id`, `task_id`, `agent_id`) is minted by the orchestrator from the
   `ValidatedPlan` and the `Task`, is required by `ToolManager.execute()`, and is written onto every
   `tool_calls` row. An agent cannot construct one, and every executed tool call now names the plan
   that authorised it.
4. **Stored-plan verification is specified and deferred with a reason.** The Tool Manager may re-read
   `plans` by `validated_plan_id` and refuse to execute unless the row carries `validated = true`.
   Within a single M1 turn that is genuinely redundant — one process validated the plan seconds
   earlier and still holds it. It stops being redundant when validation and execution are separated
   by time or by a process: **M5's approval queue** and **M10's scheduler**. Recorded as
   `THREAT_MODEL.md` **DC-14**, owned by M5, with the metadata seam built now so it is a ten-line
   addition rather than a refactor.
5. **The enforced chain, end to end** (the owner's review §7 wording, adopted verbatim as the
   canonical order):

```
LLM output → schema validation → Pydantic validation → registry validation → ValidatedPlan
          → runtime execution guard → agent permission check → tool parameter validation
          → permission engine → tool adapter
```

### Rejected alternatives *for the enforcement mechanism*

| Rejected | Why |
|---|---|
| **Leave the claim as written** | The design is good; the sentence was false. A security document that overstates one control teaches its readers to trust the others less. |
| **Rely on `mypy --strict` in CI to make the annotation binding** | Static typing is a development-time control that a runtime attacker, a `dict` deserialised from a queue (M10), or a `# type: ignore` all walk past. It is a useful complement, never the enforcement. |
| **Make `ValidatedPlan` a frozen Pydantic model and re-validate at every boundary** | Re-running full validation at three sites triples the cost of the most expensive check for no additional guarantee, and it invites the anti-pattern of *reconstructing* a `ValidatedPlan` from a dict — precisely the path this ADR closes. |
| **Cryptographically sign the plan (HMAC over the plan JSON, verified at execution)** | Genuinely stronger, and the right answer once a plan crosses a process boundary. Rejected for M1: it needs a key, key rotation and a threat that does not exist in a single in-process turn. Revisit with M10's scheduler — the `validated_plan_id` seam is where it would attach. |
| **Verify the stored `plans` row on every tool call in M1** | A DB round trip inside the hot path to re-confirm what the same process decided seconds ago. Deferred to M5 (DC-14) where it first has meaning. |
