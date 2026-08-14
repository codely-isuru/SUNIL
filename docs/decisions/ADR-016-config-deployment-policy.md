# ADR-016 — `config/*.yaml` is mounted, never baked into an image; a change takes effect on restart

**Status:** Proposed (Solution Architect) — the owner's review asked for a stated V1 policy; the
specific mechanism below is my choice · **Date:** 2026-08-14
**Context refs:** owner's architecture review §12; `ARCHITECTURE_V1.md` §2.2, §10.2, §14.2, §14.5;
FR-084, FR-107, ADR-000 Q7, ADR-011; `THREAT_MODEL.md` DC-11.

## Context

FR-084: *agent role, instructions and permissions must be changeable without a code deployment.*
The architecture satisfies that by putting them in `config/*.yaml` outside the Python package, and
§2.2 says so in as many words: **"changing configuration requires no code deployment."**

The owner's review §12 points out that this is only true if the *deployment* treats config as
external. Bake `config/` into a Docker image with `COPY config/ /app/config/` and every permission
edit becomes an image build, a push and a redeploy. The requirement would then be satisfied in the
repository layout and false in the running system — the worst kind of documentation, because nobody
discovers it until they need to change a permission in a hurry.

Nothing in the architecture said which way it goes. Whoever writes `Dockerfile.api` would decide it
by accident. That is what this ADR removes.

## Decision

1. **`Dockerfile.api` never copies `config/`.** It installs the `sunil` package and nothing from
   `config/`. An image containing baked config is a defect, and the security review checks for it.
2. **Compose mounts it read-only:** `./config:/app/config:ro`. Read-only because the API reads
   config and never writes it; a writable mount would let a compromised process rewrite
   `permissions.yaml` and grant itself a tool.
3. **`SUNIL_CONFIG_DIR` (default `./config`) is the single place the loaders look**, so an operator
   can relocate config — to a volume, a mounted secret, a config map — without touching code.
4. **A config change takes effect on restart. No hot reload in V1.** The registries are loaded and
   cross-validated once at startup, and the process refuses to boot on a mismatch (§10.2). That
   refusal is the control that makes a bad edit loud and immediate.
5. **"No code deployment" is not "no change control."** `permissions.yaml` is a privilege boundary
   and `projects.yaml` is the tool's target list. Both live in git, both are reviewed like code, and
   DC-11 (permission-config change auditing, M5) exists precisely because a deployment-free change
   is the kind that can escape an audit trail.

For local development, restart-on-change is not merely acceptable, it is the intended workflow: the
API restarts in under a second and `uvicorn --reload` already does it on save.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Bake `config/` into the image (the accidental default)** | Makes FR-084 false in the deployed system while it stays true in the repository. Also couples a permissions fix to an image build at exactly the moment — revoking a grant — when speed matters most. |
| **Hot reload on file change (watchdog / SIGHUP)** | Sounds like the obvious upgrade and introduces a genuine hazard: a turn that starts under one permission set and finishes under another. The permission engine exists to give one unambiguous answer per decision, and a mid-flight swap makes "what was allowed at 14:03?" unanswerable from config alone. Revisit only with versioned config snapshots pinned per request. |
| **Move configuration into the database with an admin UI** | Contradicts §2.2 and §7.3's deliberate "`agents` is not a table" decision, duplicates the source of truth, and needs M8's dashboard before it is usable. Config-in-git has a review trail and a `git blame`; a table has neither until someone builds them. |
| **A configuration service (Consul / AWS AppConfig / SSM Parameter Store)** | The right answer for a fleet. V1 is one process on one machine; adding a network dependency to the startup path of a single-user system buys nothing and adds a way for the app to fail to boot. Reconsider at the first multi-instance deployment. |
| **Environment variables instead of YAML for agent config** | Agent instructions are multi-line prose and nested tool grants. Flattening that into env vars is unreadable, unreviewable and loses the cross-validation that catches an agent referenced in `permissions.yaml` but missing from `agents.yaml`. |

## Consequences

- One extra line in `docker-compose.yml`, one line **not** in `Dockerfile.api`, one env var in the
  inventory (`SUNIL_CONFIG_DIR`) — the whole cost.
- A hosted V1 deployment must provide `config/` as a mount. Recorded here so it is a known deployment
  requirement and not a surprise on the first non-local install.
- Config changes remain reviewable by `git diff` and remain gated by the same review as code, which
  is what keeps FR-084's convenience from becoming a privilege-escalation route.
