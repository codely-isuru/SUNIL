# ADR-014 — Training-data capture policy: classify at capture time, four policy values, derived eligibility

**Status:** Accepted (owner's architecture review, §10, 2026-08-14) · **Date:** 2026-08-14
**Decider:** owner's correction, designed by the Solution Architect
**Context refs:** `ROADMAP.md` §30 (training data capture), §18 Epics 1–3 (V3 fine-tuning),
`ARCHITECTURE_V1.md` §7.3.1, §8.3, §13.2; NFR-001/005/009, NFR-050/051.

## Context

`ROADMAP.md` §30 is explicit that V1 must **capture data cleanly** so that V3 can build a personal
training dataset from it: user messages, plans, LLM inputs and outputs, tool calls, tool results,
user corrections, task results. The architecture already persists all of that.

The architecture also already redacts secrets (§8.3): registered secret values, key-named fields,
and high-signal patterns are scrubbed before every insert.

**Redaction is not a capture policy, and the owner's review is right to separate them.** They answer
different questions:

| Question | Answered by |
|---|---|
| "Does this row contain a credential?" | Redaction (§8.3) — mechanical, pattern-based, already built |
| "Should this row ever become training data for a model?" | **Nothing, until this ADR** |

A client's support conversation, a private repository's contents, a colleague's personal details in
a message — none of these contain an API key, all of them pass redaction untouched, and none of them
should silently become fine-tuning corpus for a model in eighteen months' time. By V3 the decision
would have to be reconstructed from stored rows by someone who was not there, which is guesswork
applied to data that has already been kept.

The context needed to classify a record — who asked, which project, which agent, which tool, what
the source was — exists **only at capture time**. That is the whole argument for doing this in V1.

## Decision

**Every record on the capture path is classified at insert time by one resolver function, and
carries four columns describing that classification.**

### 1. Four capture-policy values

| Value | Meaning | M1 behaviour |
|---|---|---|
| `none` | Do not retain content. The row exists for audit/linkage only | **Enforced.** Content columns written `NULL` |
| `metadata_only` | Retain shape, not substance: ids, timestamps, counts, lengths, token usage, cost, `error_kind` | **Enforced.** Same writer path |
| `redacted_full` | Retain full content after §8.3 redaction. **The M1 default** | **Enforced** (it is today's behaviour) |
| `full_local_only` | Retain full redacted content; never export it, never upload it, never send it to a cloud trainer | **Recorded, not enforced** — M1 has one machine and no export path. Enforcement belongs to the V2/V3 export and training pipelines, and is listed as debt D-13 so nobody reads the value as a working guarantee |

### 2. Four columns, on the five capture tables

`capture_policy`, `sensitivity` (`public|internal|confidential|restricted`), `retention_class`
(`transient|standard|long|permanent`), `training_eligible` (bool) — on **`messages`, `plans`,
`llm_calls`, `tool_calls`, `memories`**.

**Not on `audit_events`.** The audit trail is an operational and security record, not a corpus. A
capture policy that could suppress audit rows would be a control capable of disabling a control, and
ET-6 grades that table's completeness. `audit_events.detail` stays redacted; under a restrictive
policy its content *excerpts* are omitted while every stage row still exists.

### 3. Eligibility is derived, never hand-set

```
training_eligible = capture_policy in {redacted_full, full_local_only}
                    and sensitivity in {public, internal}
```

`full_local_only` can still be training-eligible: it constrains *where* training may happen (on the
owner's machine, V3), not *whether*. A human can tighten the inputs; nobody hand-flips the output.

### 4. Defaults live in config, not in code

`config/capture.yaml` — a sixth registry file, loaded and cross-validated at startup like the other
five — holds defaults per content kind plus per-project overrides, so a confidential client's
project can be marked `confidential / metadata_only` without a code change (and, per ADR-016,
without a deployment). M1 ships one project and the defaults in `ARCHITECTURE_V1.md` §13.2.

### 5. Two things are never stored at all

Credentials and payment/card data. Those are not policy values; they are the absence of a code path.
Redaction (§8.3) plus ET-10 are the enforcement, and no capture policy can re-enable them.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Keep only secret redaction (the status quo)** | Answers "is there a credential in this row?" and nothing else. Business-confidential and personal content passes it untouched, which is exactly the gap the owner's review identifies. |
| **A single boolean `training_ok`** | Cannot express "keep the metadata but not the content", cannot express "local training only", and — decisively — once data has been captured under a boolean, the nuance cannot be recovered. The cheap option is only cheap until V3 asks a question it cannot answer. |
| **Classify at export time in V3 instead of at capture time** | The classifying context (requester, project, agent, tool, source) is gone by then. It would mean either a heuristic pass over years of rows or discarding the corpus. This is the alternative the decision exists to reject. |
| **Store the policy in the database and edit it through an admin UI** | Contradicts "config is not code" (§2.2) and needs a UI that does not exist until M8 to be usable. Config file + git history is the auditable form today. |
| **Encrypt everything at rest and decide later** | Answers a different question (at-rest confidentiality), needs key management V1 does not have (ADR-006), and leaves the training question exactly as unanswered as before. It is also on the M11 debt list already (D-7) as its own separate concern. |
| **A full PII/DLP detection engine in V1** | Real cost, real false-positive rate, and — worse — false confidence: a detector that misses one field is more dangerous than a declared policy that a human set. V1 uses declared policy with safe defaults; automated detection is a V2 addition *on top of* it, not instead of it. |
| **Retain everything as `full_local_only` by default** | Superficially the safe choice, and it would make almost the whole V1 corpus ineligible for the cloud-assisted V3 workflows the roadmap describes, while giving no real protection today (nothing enforces it in M1 anyway). Safe-looking defaults that are not enforced are the worst of both. |

## Consequences

- `0001_initial` carries the four columns from the start; no back-fill migration is ever needed, and
  no row in SUNIL's history is unclassified.
- One extra registry file for T3 to load and cross-validate (~15 minutes), and one resolver function
  called from the persistence layer.
- **`retention_class` is captured and nothing purges it** — there is no retention job until M11
  (debt D-11). Recorded so its presence is not mistaken for a working retention control.
- V3 inherits classified data instead of an undifferentiated pile, which is the entire point of
  doing this two versions early.
