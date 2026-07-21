# SUNIL — Integrations

All integrations are adapters behind common interfaces in
`packages/integrations`. Each account is individually configurable, enabled/
disabled and permission-controlled from the portal, which displays: connection
state, account identity, granted scopes, last successful sync, last failure,
reconnect, disable, and sync logs.

Common conventions: OAuth/tokens in the encrypted `SecretStore`; delta/cursor
sync state in `integration_accounts`; idempotent imports via provider external
IDs; every outbound action approval-checked and audit-logged.

## Provider interfaces

| Interface | Implementations (initial) |
|---|---|
| `MailProvider` | Microsoft Graph Mail (Hotmail + M365); IMAP/SMTP fallback |
| `CalendarProvider` | Microsoft Graph Calendar |
| `ChatProvider` | Microsoft Teams (Graph) |
| `IssueProvider` | Jira Cloud |
| `SupportProvider` | Codely Support adapter (backend TBC) |
| `WeatherProvider` | Open-Meteo (default, keyless) / BOM / OpenWeather |
| `LLMProvider` | Anthropic, OpenAI, Gemini, Ollama, OpenAI-compatible |

## Microsoft accounts (Graph)

One Azure app registration; per-account OAuth connections with
least-privilege, staged scopes:

| Account | Purpose | Initial scopes |
|---|---|---|
| Personal Hotmail | Daily brief §4.1, calendar | `Mail.Read`, `Calendars.Read`, `offline_access` |
| `isuru@codely.digital` | Client/project mail | `Mail.Read` → `Mail.ReadWrite` + `Mail.Send` only when reply automation is enabled |
| `admin@codely.digital` | Operational mail | `Mail.Read` |
| Teams | Channels/chats/mentions | `Chat.Read`, `ChannelMessage.Read.All` (tenant-appropriate) |

Notes:

* Delta queries for incremental mail sync; message `id` +
  `internetMessageId` as external IDs to prevent duplicate tasks.
* Send-capable scopes are requested only when Isuru enables the corresponding
  automation, and sending remains approval-gated per `SECURITY_MODEL.md` §6.
* Web links back to messages (`webLink`) are stored so briefs and tasks can
  deep-link to the original.

## `info@ezycleanco.com.au`

Mailbox host to confirm (Microsoft/Google/IMAP) — the `MailProvider` interface
covers all three. Pipeline: classify → filter marketing/SEO/unsolicited
promotion into a reviewable **Blocked** category (configurable sender
patterns + content classifier; never permanent deletion) → detect enquiries,
quotes, bookings, changes, cancellations, complaints, invoices, follow-ups →
create tasks/reminders → draft or (with explicit permission rules) send
replies → escalate complaints, legal, refunds, safety incidents, unusual
requests and high-value enquiries.

## Jira

OAuth 2.0 (3LO) or API token. Reads: assigned, recently updated, overdue,
blocked, stale issues; project status summaries. Writes: create/update issues
**only** via approval or trusted rule. Sync stores Jira issue keys as external
IDs on SUNIL tasks and writes a `jira_links` record both ways, preventing
duplicate creation and update loops (echo suppression via `updated` timestamp
+ actor check).

## Codely Support

The current support backend is unconfirmed (email, Jira, custom system, or
WordPress portal). The `SupportProvider` interface (list new tickets, get
ticket, detect urgency/severity, affected client/site, post draft response,
update status) isolates this decision — the adapter is written once the
backend is confirmed, with **no change to orchestrator logic**. Until then a
clearly marked mock adapter serves development and tests.

## Weather

Configurable provider and location (default: Hobart, Tasmania). Open-Meteo as
the default implementation (no API key, suits local dev). Brief content:
current conditions, daily forecast, rain probability, temperature range, wind,
warnings, and a practical recommendation line.

## LLM providers

Configured in the portal per provider: base URL, credential (write-only),
available models, default model, temperature, max tokens, timeout, retry
policy, monthly budget, enabled state. Feature-based routing rules (coding,
daily tasks, email classification, reply drafting, summarisation, vision,
private/offline via Ollama, research, agent planning) with primary + fallback
model, cost/latency caps, capability requirements and failover, per
`SUNIL_ARCHITECTURE.md` §2.4.

## Future providers (interface-ready, not scheduled)

Slack (`ChatProvider`), GitHub (`IssueProvider`/repo tools), Gmail/Google
Workspace (`MailProvider`), cloud storage, custom webhooks & APIs (generic
inbound trigger + outbound action adapters for the workflow engine).
