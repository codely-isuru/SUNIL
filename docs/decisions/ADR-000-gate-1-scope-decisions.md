# ADR-000 — Gate 1 scope decisions for SUNIL V1

**Status:** Accepted · **Date:** 2026-08-14 · **Decided by:** Isuru (owner), at Gate 1
**Supersedes:** all planning decisions in the retired TypeScript build
(`archive/v0-typescript-foundation`)

## Context

`docs/ROADMAP.md` describes three product versions and thirteen agents. `docs/REQUIREMENTS_V1.md`
narrows that to V1 and, within V1, to Milestone 1 — the roadmap §22 vertical slice, due
**2026-08-17**. Seven questions had to be settled before architecture could start. The Business
Analyst presented each with a recommended default; the owner accepted all seven as-is.

This ADR records those decisions so no later agent reopens them. Architectural mechanisms are
*not* decided here — they belong to the Solution Architect's ADR-001 onward.

## Decisions

| # | Decision | Rejected alternative | Why |
|---|---|---|---|
| Q1 | **M1's single tool is a read-only GitHub adapter.** | A mock tool; or mock-then-GitHub. | Exit test ET-1 requires the answer be traceable to *real* data. A mock proves the plumbing but not the claim, and would leave a real adapter still to write. |
| Q2 | **The M1 Project Manager Agent** resolves the project, makes one read-only call, and has an LLM summarise it in 2–4 sentences. | Real project-management reasoning (planned-vs-actual, blockers, risk). | M1 exists to prove the *path*, not the agent. Real PM logic is M6. |
| Q3 | **Auth is single-user local session.** No signup, no RBAC, no tenancy. The schema still carries `user_id` throughout. | Multi-user auth from the start. | There is exactly one human user in V1. Carrying `user_id` in the schema means V2/V3 add users without a re-model; building the UI now would be unused work. |
| Q4 | **No approval flow in M1.** The M1 tool is pre-configured ALLOW. | Building the approval queue in M1. | The tool is read-only, so nothing in M1 warrants an approval. **The permission decision point still exists and is recorded on every ToolCall** (ET-4) — only the human-in-the-loop UI is deferred, to M5. |
| Q5 | **Latency target ≤30 s p95** per chat turn. | A tighter target; or none. | The roadmap is silent. A turn spans two-plus LLM calls and a network tool call; 30 s is honest for M1 and still forces the UI to show progress rather than a spinner. |
| Q6 | **Retry: max 3 attempts, exponential backoff.** | Unbounded retry; no retry. | Bounded so a provider outage fails cleanly (ET-8) instead of hanging a turn. Exact mechanics are the Architect's. |
| Q7 | **M1 reads `codely-isuru/easy_clean_workforce`**, via a minimal-scope read-only PAT. | `Codelyy/pda-erp`; `codely-isuru/SUNIL`; deciding later. | Busiest real history, so "what happened on this project" has something to summarise. **The repository must be a config value, never hard-coded.** |

**Q8 — message/conversation schema normalisation and storage technology — was explicitly NOT
decided at Gate 1.** The Business Analyst correctly declined to name a database, ORM or queue.
It belongs to the Solution Architect and lands at Gate 2.

## Consequences

- A GitHub PAT with read-only scope must be provisioned before the M1 exit tests can run. It is
  supplied through the secret mechanism the Architect specifies — never in code, prompts or logs
  (`ROADMAP.md` §26.5, NFR-001/005, ET-10).
- The permission engine ships in M1 even though no approval UI does; a ToolCall without a
  recorded permission decision fails ET-4.
- Milestones M2–M11 remain undated. Only M1 has a committed date.

## References

- `docs/REQUIREMENTS_V1.md` §12 (open questions Q1–Q8), §7 (exit tests ET-1…ET-11)
- `docs/ROADMAP.md` §22 (first development milestone), §26 (security rules), §33 (design rules)
