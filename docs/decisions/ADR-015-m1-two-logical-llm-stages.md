# ADR-015 — M1 has two logical LLM stages; the Project Manager agent's analysis *is* the user-facing response

**Status:** Accepted (owner's architecture review, §11, 2026-08-14) · **Date:** 2026-08-14
**Decider:** owner's correction, applied by the Solution Architect
**Context refs:** `ARCHITECTURE_V1.md` §1.1, §3.4, §5, §10.1; `ROADMAP.md` §22;
FR-020/022, FR-080, NFR-060; **ET-1, ET-5**; ADR-000 Q2.
**Supersedes:** the three-stage flow described in `ARCHITECTURE_V1.md` §3.4 as first issued.

## Context

The first cut of the architecture ran three logical LLM stages per turn:

```
planning LLM → GitHub tool → analysis LLM → final-response LLM → user
```

That shape is right for the SUNIL of M6 and beyond, where several agents run and somebody has to
merge several `AgentResult`s into one coherent answer in the user's voice. It is not right for M1.
M1 has **one** agent, **one** tool, **one** result — and the Project Manager agent's own contract
(ADR-000 Q2, `config/agents.yaml`) already asks it for *"a 2–4 sentence summary highlighting anything
that looks like it needs attention"*. That summary is prose, it is grounded in the tool result, and
it is written for the owner to read. Passing it through a second model to be rewritten produces a
paraphrase of a paraphrase.

## Decision

**M1 runs two logical LLM stages: `plan` and `analysis`. `AgentResult.summary` is persisted as the
assistant message and returned to the user unchanged.**

```
planning LLM → GitHub tool → PM analysis LLM → AgentResult.summary
             → persisted as the assistant message → final_response trace stage → user
```

Consequently:

- **Stage 12 `final_response` is still emitted**, by `core/orchestrator`, when it persists the
  assistant message. The twelve NFR-020 stages are unchanged, ET-6 is unchanged, the SSE frames are
  unchanged, and `M1_CHAT_SPEC` §5.3's 12→4 phase map is unchanged.
- `LLMPurpose.FINAL_RESPONSE` remains in the enum and in the `llm_calls.purpose` check constraint.
  **No M1 code path writes it.** M1 writes `plan` and `analysis` only, and QA may assert exactly that.
- The orchestrator still owns composition; what it composes from is a summary, not a completion.
- A dedicated final-response synthesiser arrives with **M6**, when multiple simultaneous agent
  results first exist to merge. Recorded as debt **D-14**.

## Effect on the exit tests — checked before adopting, because the brief requires it

| Exit test | Reads | Verdict |
|---|---|---|
| **ET-1** | "SUNIL returns a coherent natural-language status response … traceable to real data returned by the M1 tool (not fabricated)" | **Passes, unchanged, and more strongly.** The response is now the output of the call that had the tool result in front of it. One fewer generation step is one fewer place to drift from the data. Latency improves by 3–6 s against the same NFR-060 target. |
| **ET-5** | "The tool's raw result was used as an input to the agent's analysis LLM call (verifiable via the LLM input/output log), and the final chat response reflects that analysis rather than raw JSON" | **Passes, unchanged.** Both clauses still hold literally: the tool result is still the analysis call's input and is still visible in `llm_calls`; the final chat response no longer merely *reflects* the analysis — it **is** the analysis, which is a strictly stronger reading of the same sentence. Note the wording never required a third model call. |
| ET-2, ET-3, ET-4, ET-7, ET-11 | plan/task/tool/permission assertions | Untouched — nothing before stage 11 changes. |
| **ET-6** | all twelve stages present and in order | **Passes.** Stage 12 is still emitted; only its author changes from a model to deterministic code. |
| **ET-8** | transient failure recovers or fails cleanly, terminal state audited | **Passes, with a smaller surface.** One fewer provider call is one fewer thing that can fail mid-turn. |
| **ET-9** | a cost record for every LLM call, non-zero tokens | **Passes.** Two logical stages, ≥2 provider attempts, one `llm_calls` row each. The test must count *attempts*, not a hard-coded 3 (see A-2) — if any QA fixture asserted "exactly three `llm_calls` rows", that assertion was wrong before this ADR too, because a single retry broke it. |
| ET-10 | no secret in any prompt or persisted log | Untouched. |

**No exit test changes wording. One QA assumption must change:** a turn's `llm_calls` rows are
`purpose ∈ {plan, analysis}`, one per provider attempt, minimum two.

**No Designer change either.** `M1_CHAT_SPEC` §5.3 maps stages 11 and 12 to the same visible
"Finishing" phase, and its own **400 ms minimum phase display** rule already covers two stages
arriving back to back. The user sees the identical four phases.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Keep the third LLM call in M1** | Costs 3–6 s of a 30 s p95 budget, a third of the turn's token spend, and a third failure surface — to rewrite prose that is already addressed to the reader. It also makes the *hardest* stage to debug (why did the answer drift from the tool data?) a two-hop problem instead of one. |
| **Compose the final message deterministically from `AgentResult` fields with a template** | Removes the LLM entirely, but M1's answer is genuinely open-ended ("anything that looks like it needs attention"). A template would produce "Project X: 12 commits, 3 open PRs" — a report, not an answer, and it would fail ET-1's "coherent natural-language response" on any input the template did not anticipate. |
| **Have the analysis call return a structured `{summary, findings[], risk}` object and render the summary field** | Attractive, and probably right at M6. Rejected for M1: it puts a JSON schema on the analysis call, which then needs its own validation layer, its own failure mode, and its own retry — reintroducing most of the cost the third call was removed to save. It also constrains the model's prose to a shape nobody has yet needed. |
| **Keep three calls but make the third one optional behind a flag** | Two code paths through the most-tested part of the system, doubling what QA must verify, so that a future milestone can flip a switch. M6 will introduce a synthesiser with a different signature anyway (it merges *many* results); the flag would not survive contact with it. |

## Consequences

- Nominal turn latency drops from 11–24 s to **7.5–17.5 s** (`ARCHITECTURE_V1.md` §5.1), which is
  the headroom that now pays for a retry without breaching 30 s.
- Per-turn token spend drops by roughly a third.
- The agent's `instructions` in `config/agents.yaml` become **user-facing copy**, because its summary
  is now the answer verbatim. That is a real change in what those three lines are: "Never claim
  anything the tool result does not show" is no longer advice to an intermediate step, it is the
  last line of defence before the owner reads it. Reviewed as such.
- `core/orchestrator/turn.py` gets simpler: stage 12 becomes a persist-and-emit, not a model call.
