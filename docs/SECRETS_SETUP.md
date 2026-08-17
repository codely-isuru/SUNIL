# Secrets setup — what the owner needs to create, exactly

**For:** Isuru (owner). **Needed by:** Day 3 of the M1 build (2026-08-16), before the exit tests
can run. **Nothing here should be pasted into a chat, a commit, an issue or a prompt.**

**T25 (2026-08-17) update:** provider API keys are now optional at the settings layer — the app
boots fine with only one of Anthropic/OpenAI configured, or neither. What is actually required
**today** is `OPENAI_API_KEY` + `GITHUB_TOKEN`: `general_reasoning` (`config/models.yaml`), the
M1 hot path both the plan call and the analysis call use, resolves to `openai` (T24). Anthropic
is genuinely optional until some capability an agent can reach points at it again — see §0 and
§4 below, both updated.

Two credentials go into **one file you create yourself**:

```
C:\repo\SUNIL\.env
```

That path is gitignored (`.gitignore` line `.env`), so it cannot be committed. The file does not
exist yet — `.env.example` (created by task T1) is the template with placeholder values only. A
real value in `.env.example` is an exit-test failure (ET-10), so copy the template, don't edit it
in place.

---

## 0. Which model provider — decided 2026-08-17

The owner asked whether SUNIL could use the existing **Claude subscription** instead of an
API key. **It cannot.** The subscription authenticates the Claude apps and Claude Code;
calling a model from our own application goes through the metered Anthropic API, which has
its own keys. There is no supported way to point the Model Router at subscription
credentials, and borrowing Claude Code's own token would be unsupported and would break on
any rotation.

**Decision: wire OpenAI first (the owner already has that key), add Anthropic later.** Two
registered providers is the V1 target state regardless — the Model Router selects per
capability. This is also the first real test of ADR-003's claim that a provider can be added
without touching an agent.

**So the credential you need first is `OPENAI_API_KEY`** (no `SUNIL_` prefix — confirmed
against `.env.example`/`ARCHITECTURE_V1.md` §14.4 by T23, per this section's own rule below:
"if they disagree, `.env.example` wins"). The Anthropic section below stays accurate for when
you add that key; neither is required for the 559 tests that already pass on fixtures.

**T25 update:** `OPENAI_API_KEY` is no longer "first" in the sense of "add this one now, add the
other one later on the same footing" — as of T24, `general_reasoning` (the M1 hot path)
resolves to `openai`, so `OPENAI_API_KEY` is required for any real turn to work at all, while
`ANTHROPIC_API_KEY` is genuinely optional: the app boots and every fixture-based test passes
without it, and it stays optional until a capability an agent can actually reach (its
`preferred_capability`) is repointed at `anthropic` again. Add it whenever convenient, not
because anything currently blocks on it.

---

## 1. Anthropic API key

**Where:** <https://console.anthropic.com/settings/keys> → *Create Key*.

**Name it** something identifiable, e.g. `sunil-v1-dev`.

**Scope/limits:** if the console offers a workspace or spend limit, put this key in its own
workspace with a modest monthly cap. M1 makes two logical LLM calls per chat turn (planning and
analysis) plus retries, so a small cap is plenty and it bounds the damage if the key ever leaks.

**Note this is a metered API key, not your Claude subscription.** SUNIL calls the API directly
through its Model Router; the subscription that runs Claude Code cannot be used for it.

Add to `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## 1.5. OpenAI API key — the one to add first (§0)

**Where:** <https://platform.openai.com/api-keys> → *Create new secret key*.

**Name it** something identifiable, e.g. `sunil-v1-dev`, same as the Anthropic key above.

**Scope/limits:** same reasoning as §1 — a modest project-level spend cap bounds the damage if
the key ever leaks. **T24 update:** `general_reasoning` — the M1 hot path, used by both the
orchestrator's plan call and the PM agent's analysis call — now resolves to this provider
(`config/models.yaml`). Every real chat turn calls it.

Add to `.env`:

```
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
```

`OPENAI_BASE_URL` is optional — it defaults to the value above and only needs setting to
override it (the same ADR-017 loopback-or-canonical rule as `ANTHROPIC_BASE_URL`/
`GITHUB_API_BASE_URL` applies).

---

## 2. GitHub personal access token — fine-grained, read-only

**Where:** <https://github.com/settings/personal-access-tokens/new> — *Fine-grained tokens*, **not**
the classic tab.

Fill it in exactly like this:

| Field | Value |
|---|---|
| **Token name** | `sunil-m1-readonly` |
| **Resource owner** | `codely-isuru` |
| **Expiration** | 30 days (M1 needs days, not months) |
| **Repository access** | *Only select repositories* → **`codely-isuru/easy_clean_workforce`** — this one repo, nothing else |

**Repository permissions — set exactly these three to `Read-only`, and leave every other
permission at `No access`:**

| Permission | Level |
|---|---|
| Contents | **Read-only** |
| Pull requests | **Read-only** |
| Issues | **Read-only** |

Do **not** grant: Actions, Administration, Secrets, Webhooks, Workflows, or any `Read and write`
level. The agent's job is to read recent activity and summarise it. Anything beyond read on those
three surfaces is privilege the tool has no use for, and the permission engine is configured to
deny it regardless.

Add to `.env`:

```
GITHUB_TOKEN=github_pat_...
```

**Why fine-grained and not the classic PAT already on this machine:** the classic token in
`C:\repo\env\FTP Accounts.txt` carries broad org-wide scope. Handing an autonomous agent a
credential far wider than its task contradicts roadmap §26.7 (least privilege) and §26.3, and it
would make the ET-10 and ET-12 results much less meaningful. Two minutes of token creation buys a
genuinely scoped credential.

---

## 3. After you create the file

```bash
cd C:\repo\SUNIL
copy .env.example .env
```

…then paste the two values in, save, and tell me. I do **not** need to see them, and I will not
ask for them. What I will do is confirm the app can read them — the health check reports whether
each secret is *present*, never its value (`SecretStr` serialises to `[REDACTED]`, by ADR-006).

## 4. What is blocked until they arrive

**T25 update:** the table below described a world where every provider key was mandatory at
the settings layer. That is no longer true — a missing provider key is a startup failure only
if some agent's `preferred_capability` actually resolves to that provider
(`sunil/providers/registry.py`'s `validate_capability_providers()`). Since T24 repointed
`general_reasoning` to `openai`, the row that used to say "Anthropic key" for ET-5/ET-8/ET-9 was
wrong the moment that landed — corrected below.

| Blocked | Needs |
|---|---|
| ET-1 (real data, not fabricated), ET-12 (prompt-injection defence) | GitHub token |
| ET-5, ET-8, ET-9 (analysis, provider failure, cost per attempt) | OpenAI key (not Anthropic — T24 moved the hot path) |
| The full M1 end-to-end run | OpenAI key + GitHub token |

Anthropic's key blocks nothing in M1 today: no capability an agent can reach points at it (T25).
Add it whenever convenient — the app does not need it to boot or to run a real turn.

Everything else — T1 through T11, the frontend, the red test harness, the security boundary
tests — builds and runs against fixtures without any live credential.

## 5. If a secret is ever exposed

Revoke first, then rotate; do not delete the evidence. Both consoles above have a revoke button
on the token, and both tokens are cheap to recreate. Tell me and I will have the security lane
check whether it reached any log, prompt or commit.
