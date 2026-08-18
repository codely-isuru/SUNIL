# 2026-08-19 — M1 live-verified, and the credentials earned their keep

**Team:** Minions Team 18 · `main` @ live-verified

## The result

A real chat turn, driven through the browser against real credentials:

```
request_id 70a19c8c-…   completed in 5.8s
stages     12 (ET-6)  ·  tool_calls 1 allow + validated_plan_id (ET-4)
llm_calls  plan 260->126, analysis 2676->209, one row per attempt (ET-9)
task       completed / project_manager (ET-3)
```

564 fixture tests and 7 live tests passing.

## What only live credentials could find

The fixture suite was green for a full day before any real key existed. Every one of these
was invisible to it:

1. **A security test leaked a real GitHub token.** `assert github and anthropic` — pytest's
   assertion rewriting prints operand values on failure, so the token was published to a
   terminal and had to be revoked and rotated. The audit found **four** assertions in that
   file with raw credentials as operands. The file whose purpose is proving secrets never
   leak, leaking one.
2. **A precondition demanded a key we had deliberately made optional.** T25 made provider
   keys optional; the live fixtures still required Anthropic, so the end-to-end tests
   skipped on a condition that was no longer true — and that same stale precondition is
   what made the leaking assertion fire.
3. **The suite had been passing partly by accident of an empty environment.** No `.env` had
   ever existed on the machine, so `monkeypatch.delenv` looked sufficient. The moment a real
   file appeared, one test failed and another was revealed as a **false pass** that had
   never exercised its own case.
4. **A security test measured a field that could not vary with what it claimed to measure.**
   `permissions` on `GET /repos/{owner}/{repo}` reports the *user's* role, so it read
   `admin: True` for a token that got 403 on `/commits`. T-17's "Mitigated" rating rested on
   a check that could never have falsified it.
5. **The replacement probe picked a Metadata-gated endpoint** as a write test.
   `/collaborators` is readable by every fine-grained token, so it could never be satisfied.

Each was found by running against reality, and each was fixed at the mechanism rather than
the symptom.

## What was declined

- Proving absence of write access. Every GET is gated by a *read* permission, so no GET can
  demonstrate it, and attempting a write is out. The test was renamed to what it can prove,
  with the residual stated in its docstring.
- Containment by enumeration. No endpoint reports a fine-grained token's scope, so that test
  **skips** unless a private control repository is named, rather than passing falsely.
- Using the owner's Claude Max and ChatGPT Plus subscriptions. Neither grants API access;
  the unsupported routes (browser automation, reusing another client's OAuth token) were
  refused rather than built.

## Carried forward

`docs/STATUS.md` §3a. Headline items: cost figures are placeholders, no frontend test
runner until M11, OpenAI's structured-output guarantee is conditional where Anthropic's is
unconditional, and DC-1 expires when agents loop at M6.
