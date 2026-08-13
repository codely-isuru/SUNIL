# S.U.N.I.L. — Agentic OS
## Project Roadmap & Implementation Plan

**Project:** S.U.N.I.L.  
**Type:** Personal + Business Agentic Operating System  
**Roadmap:** V1 → V3  
**Primary principle:** SUNIL is the system. Claude, Codex, OpenAI, Qwen, and future models are interchangeable intelligence providers used by SUNIL.

---

# 1. Project Vision

SUNIL is a personal and business Agentic OS that can:

- Communicate through dashboard, chat, voice, and later mobile.
- Understand natural-language requests.
- Break goals into executable tasks.
- Select appropriate agents.
- Select the best AI model per task.
- Use tools and connected services safely.
- Maintain short-term and long-term memory.
- Coordinate multiple specialist agents.
- Run scheduled and proactive workflows.
- Ask for approval before sensitive actions.
- Gradually move from cloud-first intelligence to local-first intelligence.
- Learn from real usage and become increasingly personalised.

The final system should not depend on one AI provider.

```text
SUNIL
  |
  +-- Claude
  +-- OpenAI
  +-- Codex
  +-- Local Qwen
  +-- Future models
```

---

# 2. Core Architectural Principle

A normal backend application cannot "think".

Therefore SUNIL must separate:

1. **Deterministic software**
2. **AI reasoning**
3. **Agents**
4. **Tools**
5. **Memory**
6. **User interfaces**

The Central Orchestrator is software. It manages execution but calls an LLM whenever natural-language understanding, planning, reasoning, evaluation, or response generation is required.

```text
USER
 |
 v
Dashboard / Chat / Voice / Mobile
 |
 v
Conversation Gateway
 |
 v
SUNIL CORE
 |
 +--> Central Orchestrator
 |      |
 |      +--> Request interpretation -> LLM
 |      +--> Planning               -> LLM
 |      +--> Execution              -> deterministic code
 |      +--> Permissions            -> deterministic code
 |      +--> Tool calls             -> deterministic code
 |      +--> Monitoring             -> deterministic code
 |      +--> Evaluation             -> LLM + deterministic checks
 |      +--> Final response         -> LLM
 |
 v
Model Router
 |
 +--> Local LLM
 +--> Claude
 +--> OpenAI
 +--> Codex
 |
 v
Agents
 |
 v
Tools / Systems
```

---

# 3. High-Level Architecture

```text
+------------------------------------------------------------+
|                    INTERFACE LAYER                         |
|                                                            |
| Dashboard | Chat | Voice | Mobile                          |
+-----------------------------+------------------------------+
                              |
                              v
+------------------------------------------------------------+
|                CONVERSATION GATEWAY                        |
|                                                            |
| Authentication                                             |
| User identity                                              |
| Sessions                                                   |
| Conversation history                                       |
| Context                                                    |
| Voice STT / TTS integration                                |
+-----------------------------+------------------------------+
                              |
                              v
+------------------------------------------------------------+
|                      SUNIL CORE                            |
|                                                            |
| Central Orchestrator                                       |
| Task Manager                                               |
| Workflow Engine                                            |
| Agent Manager                                              |
| Permission Engine                                          |
| Tool Manager                                               |
| Memory Manager                                             |
| Scheduler                                                  |
| Event Bus                                                  |
| Notification Service                                       |
| Audit Logger                                               |
+-----------------------------+------------------------------+
                              |
                              v
+------------------------------------------------------------+
|                   INTELLIGENCE LAYER                       |
|                                                            |
|                       MODEL ROUTER                         |
|                                                            |
| Local Qwen | Claude | OpenAI | Codex | Future Providers    |
+-----------------------------+------------------------------+
                              |
                              v
+------------------------------------------------------------+
|                        AGENTS                              |
|                                                            |
| Personal Assistant                                         |
| Codely Executive                                           |
| Project Manager                                            |
| Developer                                                  |
| QA                                                         |
| DevOps                                                     |
| Support                                                    |
| Email                                                      |
| Research                                                   |
| Marketing                                                  |
+-----------------------------+------------------------------+
                              |
                              v
+------------------------------------------------------------+
|                         TOOLS                              |
|                                                            |
| GitHub | Gmail | Calendar | Jira | Codely Support          |
| Browser | Files | Terminal | Docker | SSH | AWS             |
| Databases | WordPress | Stripe | Other APIs                |
+------------------------------------------------------------+
```

---

# 4. Technology Direction

These are recommended starting technologies, not permanent restrictions.

## Backend

- Python
- FastAPI
- PostgreSQL
- pgvector
- Redis
- WebSockets
- Background workers / job queue
- Docker

## Frontend

- Next.js
- React
- Tailwind CSS
- WebSocket client for live agent/task updates
- PWA support initially
- Native mobile application later if required

## AI Providers

### V1

- Claude as primary reasoning model
- OpenAI as secondary/general model
- Codex for specialist software-development tasks

### V2

- Add local open-weight model
- Qwen-family model preferred initially
- Serve using Ollama or vLLM
- Expose through a provider abstraction

### V3

- Fine-tuned/personalised local model
- Cloud providers become specialist/escalation models

---

# 5. Model Abstraction

No agent or workflow should directly depend on one provider.

Bad:

```python
claude.send(prompt)
```

Preferred concept:

```python
model_router.run(
    task=task,
    capability="complex_reasoning",
    privacy_level="internal",
    cost_priority="balanced"
)
```

The Model Router decides which model is appropriate.

Example routing:

```text
Simple summarisation
-> Local

Private personal information
-> Local

Sensitive Codely information
-> Local

General reasoning
-> Local or Claude

Complex architecture
-> Claude

Large software implementation
-> Codex

Difficult debugging
-> Claude / Codex

Local model failure
-> Escalate to cloud
```

---

# 6. Interface Separation

Dashboard, chat, and voice are not separate AI systems.

They are separate ways of communicating with SUNIL.

## Dashboard

The dashboard is standard application software.

It displays:

- Today's overview
- Tasks
- Projects
- Calendar
- Running agents
- Approvals
- Notifications
- Active workflows
- Agent status
- System health
- Recent conversations
- Codely business overview

The dashboard communicates with SUNIL's backend API.

## Chat

```text
User
 |
 v
Chat UI
 |
 v
Conversation Gateway
 |
 v
SUNIL Orchestrator
 |
 v
Model Router
 |
 v
Selected LLM
```

## Voice

```text
Microphone
 |
 v
Speech-to-Text
 |
 v
SUNIL
 |
 v
Model Router
 |
 v
Selected LLM
 |
 v
Text-to-Speech
 |
 v
Speaker
```

Voice is only another interface.

The reasoning model does not need to be the same service used for STT or TTS.

---

# 7. Central Orchestrator

The Central Orchestrator is the operational core of SUNIL.

It is **not an LLM**.

It is deterministic software that uses LLMs when intelligence is required.

## Responsibilities

- Receive user requests
- Load conversation context
- Load relevant memory
- Request intent analysis from an LLM
- Request task planning from an LLM
- Validate structured plans
- Start workflows
- Allocate agents
- Request models through the Model Router
- Validate tool permissions
- Execute tool calls
- Track task status
- Handle retries
- Handle failures
- Ask for human approval
- Evaluate results
- Produce audit logs
- Return final results

## Example

User:

> Check the PDA project and tell me if the developers completed what they were supposed to do today.

Flow:

```text
1. Conversation Gateway receives request

2. Orchestrator loads:
   - current user
   - conversation
   - PDA project context
   - relevant memory

3. Orchestrator asks reasoning LLM:
   "Interpret this request and create a structured plan."

4. LLM returns:
   - intent
   - project
   - objectives
   - required agents
   - required tools
   - steps

5. Orchestrator validates the plan.

6. Orchestrator starts Project Manager Agent.

7. PM Agent requests GitHub/Jira information.

8. Tool Manager checks permissions.

9. Tools execute.

10. Agent analyses results using selected LLM.

11. Orchestrator verifies completion.

12. Final summary is returned to user.
```

---

# 8. Agent Definition

An agent is not permanently tied to an LLM.

An agent consists of:

- Role
- Instructions
- Objectives
- Memory scope
- Tool permissions
- Workflow rules
- Preferred model capability
- Escalation rules

Example:

```yaml
agent: project_manager

role:
  Manage software projects and identify risks.

instructions:
  - Review project progress.
  - Detect blockers.
  - Compare planned vs completed work.
  - Coordinate development, QA and DevOps agents.
  - Escalate important risks.

memory:
  - project_history
  - developer_activity
  - deadlines

tools:
  github: read
  jira: read_write
  calendar: read
  production: none

preferred_model:
  capability: general_reasoning

escalation:
  capability: complex_reasoning
```

A Project Manager Agent may use:

- Local Qwen for a routine project check
- Claude for difficult reasoning
- Codex if implementation work is required

It remains the same agent.

---

# 9. Initial Agent Set

V1 should start with a controlled number of useful agents.

## 9.1 Personal Assistant Agent

Responsibilities:

- Calendar
- Tasks
- Reminders
- Daily brief
- Personal requests
- Research
- Follow-ups

## 9.2 Codely Executive Agent

Responsibilities:

- Company overview
- Project priorities
- Client issues
- Business risks
- Important approvals
- Executive summaries

## 9.3 Project Manager Agent

Responsibilities:

- Project status
- Task tracking
- Deadlines
- Blockers
- Developer progress
- Planning
- Agent coordination

## 9.4 Developer Agent

Responsibilities:

- Understand codebases
- Investigate bugs
- Review code
- Implement smaller changes
- Coordinate Codex/Claude Code
- Prepare development summaries

## 9.5 QA Agent

Responsibilities:

- Test plans
- Regression testing
- Bug verification
- Release validation
- Quality reports

## 9.6 DevOps Agent

Responsibilities:

- Deployment preparation
- Server health
- Logs
- Docker
- Cloud systems
- Monitoring
- Infrastructure operations

## 9.7 Support Agent

Responsibilities:

- Read support tickets
- Classify issues
- Detect urgent tickets
- Draft responses
- Escalate technical issues
- Create development tasks

## 9.8 Email Agent

Responsibilities:

- Read selected mailboxes
- Summarise
- Prioritise
- Draft replies
- Extract tasks
- Schedule follow-ups

---

# 10. Tool Architecture

LLMs should not receive unrestricted direct access to company systems.

All tool access must pass through the SUNIL Tool Manager.

```text
Agent / LLM
 |
 | requests tool operation
 v
Tool Manager
 |
 +--> Permission Engine
 |
 +--> Audit Logger
 |
 v
Tool Adapter
 |
 v
External System
```

Initial tools:

- GitHub
- Gmail
- Google Calendar
- Jira / project system
- Codely Support
- Local filesystem
- Browser
- Terminal
- Docker
- SSH
- AWS / cloud
- Databases
- WordPress
- Stripe
- Notification services

---

# 11. Permissions

Every tool action should result in one of:

```text
ALLOW
DENY
ASK USER
```

Example:

```yaml
developer_agent:

  github:
    read: allow
    create_branch: allow
    push_branch: allow
    merge_main: ask_user

  production:
    deploy: ask_user

  database:
    read: allow
    write: ask_user
    delete: deny

  email:
    read: allow
    draft: allow
    send: ask_user
```

Sensitive actions should not rely solely on model judgement.

---

# 12. Human Approval System

V1 must remain human-supervised for important operations.

Examples requiring approval:

- Production deployments
- Sending external client emails
- Deleting files
- Deleting database records
- Payment operations
- Infrastructure changes
- Credential changes
- Major Git operations
- Client-facing production changes

Example UI:

```text
SUNIL requests approval

Action:
Deploy PDA update to production

Reason:
Bug fix passed QA.

Changes:
3 files

Tests:
All passed

[Approve]
[Reject]
[Review]
```

---

# 13. Memory Architecture

Memory should not mean "send every historical conversation to the LLM".

Use different memory types.

## Short-Term Memory

- Current conversation
- Current task
- Recent agent actions

## Long-Term Memory

- Important decisions
- Project history
- Historical context
- User preferences

## Structured Memory

- Clients
- Projects
- People
- Tasks
- Systems
- Relationships

## Knowledge / RAG

- Documents
- Reports
- SRS documents
- Support cases
- Technical documentation
- Meeting notes
- Internal procedures

## Preference Memory

- Communication style
- Technology preferences
- Decision patterns
- Approval preferences
- Business rules

Recommended:

```text
PostgreSQL
+
pgvector
+
Document/file storage
```

---

# 14. PHASE 1 — V1: SUNIL CORE

## Objective

Build a functional cloud-first Agentic OS.

Do not fine-tune a local LLM in V1.

## V1 Major Deliverables

### Epic 1 — Project Foundation

- [ ] Create monorepo/project structure
- [ ] Backend service
- [ ] Frontend service
- [ ] PostgreSQL
- [ ] Redis
- [ ] Docker Compose
- [ ] Environment configuration
- [ ] Authentication foundation
- [ ] Logging
- [ ] Basic CI pipeline

### Epic 2 — Conversation Gateway

- [ ] User/session handling
- [ ] Conversation persistence
- [ ] Chat API
- [ ] WebSocket streaming
- [ ] Context management
- [ ] Conversation history
- [ ] Request IDs / correlation IDs

### Epic 3 — Model Provider Layer

- [ ] Define common provider interface
- [ ] Claude provider
- [ ] OpenAI provider
- [ ] Codex/development provider
- [ ] Model Router
- [ ] Provider error handling
- [ ] Retry rules
- [ ] Cost/usage tracking
- [ ] Capability metadata

### Epic 4 — Central Orchestrator

- [ ] Request intake
- [ ] LLM intent interpretation
- [ ] Structured task-plan schema
- [ ] Plan validation
- [ ] Workflow creation
- [ ] Task execution lifecycle
- [ ] Retry/failure handling
- [ ] Completion detection
- [ ] Final response generation

### Epic 5 — Agent Framework

- [ ] Agent registry
- [ ] Agent configuration schema
- [ ] Agent lifecycle
- [ ] Agent memory scope
- [ ] Agent tool permissions
- [ ] Agent-to-orchestrator communication
- [ ] Initial agents

### Epic 6 — Tool Framework

- [ ] Tool registry
- [ ] Tool adapter interface
- [ ] Permission checks
- [ ] Tool execution logs
- [ ] Result normalisation
- [ ] Error handling

### Epic 7 — Initial Integrations

- [ ] GitHub
- [ ] Gmail
- [ ] Google Calendar
- [ ] Project tracker
- [ ] Codely Support
- [ ] Filesystem
- [ ] Browser
- [ ] Terminal
- [ ] Docker
- [ ] SSH

### Epic 8 — Permission & Approval Engine

- [ ] Role-based permissions
- [ ] Agent permissions
- [ ] Tool-level permissions
- [ ] Resource-level permissions
- [ ] Approval queue
- [ ] Approve/reject workflow
- [ ] Audit trail

### Epic 9 — Memory V1

- [ ] Conversation memory
- [ ] Long-term memory
- [ ] Project/client entities
- [ ] Vector embeddings
- [ ] RAG retrieval
- [ ] Memory relevance scoring
- [ ] Memory write rules

### Epic 10 — Dashboard

- [ ] Home overview
- [ ] Chat
- [ ] Tasks
- [ ] Agents
- [ ] Workflows
- [ ] Approvals
- [ ] Projects
- [ ] Calendar
- [ ] Notifications
- [ ] Activity log
- [ ] Settings

### Epic 11 — Voice V1

- [ ] Browser microphone input
- [ ] Cloud STT integration
- [ ] Send transcript through normal SUNIL conversation flow
- [ ] Cloud TTS integration
- [ ] Stream audio response
- [ ] Voice session history

### Epic 12 — Scheduler

- [ ] One-time scheduled tasks
- [ ] Recurring tasks
- [ ] Background jobs
- [ ] Scheduled agent runs
- [ ] Notifications

---

# 15. V1 Acceptance Test

V1 is considered successful when the following request works end-to-end:

> SUNIL, check everything happening at Codely today and tell me what requires my attention.

SUNIL should:

- [ ] Understand the request using an LLM
- [ ] Create a structured plan
- [ ] Select appropriate agents
- [ ] Read connected systems
- [ ] Collect project/task information
- [ ] Analyse findings
- [ ] Identify important issues
- [ ] Produce a concise executive summary
- [ ] Create tasks where appropriate
- [ ] Request approval for sensitive actions
- [ ] Store useful memory
- [ ] Produce complete audit logs

---

# 16. PHASE 2 — V2: HYBRID SUNIL

## Objective

Introduce local AI while retaining cloud models.

```text
SUNIL
 |
 v
Model Router
 |
 +--> Local Qwen
 +--> Claude
 +--> OpenAI
 +--> Codex
```

## V2 Deliverables

### Epic 1 — Local AI Server

- [ ] Select local Qwen model based on available hardware
- [ ] Install Ollama or vLLM
- [ ] Create local provider adapter
- [ ] Health checking
- [ ] Model loading/unloading
- [ ] Performance metrics
- [ ] Context/window management

### Epic 2 — Privacy Classification

Every request receives a classification:

- PUBLIC
- INTERNAL
- CONFIDENTIAL
- HIGHLY CONFIDENTIAL
- LOCAL ONLY

- [ ] Classification engine
- [ ] Routing restrictions
- [ ] Local-only enforcement
- [ ] Sensitive-data redaction where required

### Epic 3 — Intelligent Model Routing

Route based on:

- Capability
- Privacy
- Complexity
- Cost
- Latency
- Model availability
- Historical success rate

- [ ] Routing policy engine
- [ ] Escalation rules
- [ ] Local fallback
- [ ] Cloud fallback
- [ ] Failure counters

### Epic 4 — Shadow Mode

For selected tasks:

```text
Task
 |
 +--> Cloud model -> Result A
 |
 +--> Local model -> Result B
 |
 v
Evaluator
```

Record:

- Quality
- Accuracy
- Latency
- Cost
- Failures
- User corrections
- Approval/rejection rate

### Epic 5 — Local Voice

- [ ] Local STT
- [ ] Local TTS
- [ ] Offline voice operation
- [ ] Voice interruption
- [ ] Streaming
- [ ] Wake-word exploration if required

### Epic 6 — Agent-to-Agent Communication

- [ ] Parent/child tasks
- [ ] Agent delegation
- [ ] Shared project context
- [ ] Agent messages/events
- [ ] Result handoff
- [ ] Conflict resolution
- [ ] Orchestrator supervision

### Epic 7 — Autonomous Workflows

Examples:

- Morning Codely briefing
- Email review
- Project monitoring
- Support monitoring
- Development progress review
- Server health checks
- Client follow-up tracking

- [ ] Scheduled autonomous agent runs
- [ ] Conditional triggers
- [ ] Exception-based notifications
- [ ] Workflow history
- [ ] Automatic retry

---

# 17. V2 Acceptance Test

SUNIL should be able to run routine work locally while automatically escalating difficult work.

Example:

```text
User:
"Review today's Codely activity."

SUNIL:
1. Local model interprets request.
2. Project Manager Agent checks systems.
3. Routine summaries use local model.
4. Difficult architecture issue is escalated to Claude.
5. Coding task is delegated to Codex.
6. Sensitive data remains local.
7. Final result is consolidated by SUNIL.
```

V2 is done when:

- [ ] Local and cloud models are interchangeable
- [ ] Privacy restrictions are enforced
- [ ] Routine tasks run reliably locally
- [ ] Cloud escalation works
- [ ] Agents collaborate
- [ ] Voice can operate locally
- [ ] Autonomous scheduled workflows run reliably
- [ ] Performance data is collected continuously

---

# 18. PHASE 3 — V3: PERSONALISED SUNIL

## Objective

Turn SUNIL into a local-first personal and business AI trained around real usage.

## V3 Deliverables

### Epic 1 — Training Dataset Pipeline

Collect high-quality traces:

```text
Original request
-> Context
-> Plan
-> Agents
-> Tool calls
-> Model responses
-> SUNIL decisions
-> User corrections
-> User approval/rejection
-> Final result
```

- [ ] Dataset collection
- [ ] Quality filtering
- [ ] PII/sensitive-data handling
- [ ] Preference examples
- [ ] Successful workflow examples
- [ ] Failed workflow examples
- [ ] Human corrections
- [ ] Dataset versioning

### Epic 2 — Personal Fine-Tuning

Use LoRA/QLoRA.

Teach behaviour, not changing factual knowledge.

Examples:

- How the user communicates
- How work is delegated
- Preferred technologies
- How Codely operates
- How client communication is handled
- Project-management preferences
- Decision patterns
- Risk tolerance
- Escalation preferences
- Preferred response structure
- Coding/review preferences

Changing knowledge should remain in memory/RAG/databases.

### Epic 3 — Personal Local Model

```text
Base Open Model
      +
SUNIL Interaction Dataset
      +
Codely Workflow Dataset
      +
Personal Preference Dataset
      |
      v
Personal SUNIL Model
```

### Epic 4 — Local-First Routing

Target:

```text
Routine tasks
-> Personal local model

Private tasks
-> Personal local model

Company operations
-> Personal local model

Difficult reasoning
-> Claude/OpenAI

Large implementation
-> Codex
```

Cloud remains available but becomes an escalation/specialist layer.

### Epic 5 — Proactive Intelligence

SUNIL should identify situations without waiting for explicit prompts.

Examples:

- Project is slipping
- Developer is blocked
- Important client has not received a reply
- Server health degraded
- Deadline approaching
- Invoice needs attention
- Support issue is escalating

SUNIL should avoid unnecessary interruptions.

### Epic 6 — Autonomous Delegation

High-level goal:

> Build the new customer portal.

Possible flow:

```text
SUNIL
 |
 +--> Requirements
 +--> Research
 +--> Architecture
 +--> UI planning
 +--> Development tasks
 +--> Developer Agent
 +--> QA Agent
 +--> Security checks
 +--> DevOps Agent
 +--> Staging deployment
 +--> Human approval
 +--> Production deployment
```

### Epic 7 — Controlled Computer Access

Only introduce broader computer control after the security model is mature.

Possible abilities:

- Launch approved applications
- Use browser
- Read/write approved files
- Run terminals
- Manage Docker
- SSH into approved servers
- Work with development environments
- Upload/download files
- Manage local applications

Everything must pass through:

```text
Permission Engine
+
Sandbox
+
Audit Log
+
Approval Rules
```

---

# 19. V3 Acceptance Test

SUNIL V3 should:

- [ ] Understand natural requests
- [ ] Know personal working preferences
- [ ] Maintain long-term context
- [ ] Run Codely workflows
- [ ] Manage multiple agents
- [ ] Reason primarily locally
- [ ] Protect sensitive data
- [ ] Work through chat and voice
- [ ] Proactively identify important problems
- [ ] Delegate work autonomously
- [ ] Verify work
- [ ] Recover from failures
- [ ] Use cloud models only when useful
- [ ] Control approved computer resources
- [ ] Learn from corrections and feedback

---

# 20. Suggested Repository Structure

```text
sunil/
|
+-- apps/
|   +-- web/                    # Next.js dashboard/chat
|   +-- api/                    # FastAPI application
|
+-- core/
|   +-- orchestrator/
|   +-- conversations/
|   +-- tasks/
|   +-- workflows/
|   +-- agents/
|   +-- models/
|   +-- tools/
|   +-- permissions/
|   +-- memory/
|   +-- scheduler/
|   +-- events/
|   +-- notifications/
|   +-- audit/
|
+-- providers/
|   +-- claude/
|   +-- openai/
|   +-- codex/
|   +-- local/
|
+-- agents/
|   +-- personal_assistant/
|   +-- codely_executive/
|   +-- project_manager/
|   +-- developer/
|   +-- qa/
|   +-- devops/
|   +-- support/
|   +-- email/
|
+-- tools/
|   +-- github/
|   +-- gmail/
|   +-- calendar/
|   +-- jira/
|   +-- codely_support/
|   +-- filesystem/
|   +-- browser/
|   +-- terminal/
|   +-- docker/
|   +-- ssh/
|   +-- aws/
|
+-- memory/
|   +-- embeddings/
|   +-- retrieval/
|   +-- documents/
|   +-- preferences/
|
+-- voice/
|   +-- stt/
|   +-- tts/
|
+-- infra/
|   +-- docker/
|   +-- database/
|   +-- redis/
|   +-- deployment/
|
+-- tests/
|   +-- unit/
|   +-- integration/
|   +-- e2e/
|   +-- agent_eval/
|
+-- docs/
|   +-- architecture/
|   +-- agents/
|   +-- tools/
|   +-- security/
|   +-- api/
|
+-- scripts/
|
+-- .env.example
+-- docker-compose.yml
+-- README.md
```

---

# 21. Core Data Objects

Design these early.

## User

```text
User
- id
- name
- preferences
- security settings
```

## Conversation

```text
Conversation
- id
- user_id
- title
- messages
- active_context
```

## Task

```text
Task
- id
- objective
- status
- priority
- parent_task_id
- assigned_agent
- privacy_level
- model_used
- created_at
- completed_at
```

## Agent

```text
Agent
- id
- role
- instructions
- tools
- permissions
- memory_scope
- preferred_capabilities
```

## Workflow

```text
Workflow
- id
- trigger
- status
- tasks
- schedule
- owner
```

## Tool Call

```text
ToolCall
- id
- agent
- tool
- operation
- parameters
- permission_decision
- result
- timestamp
```

## Approval

```text
Approval
- id
- action
- risk
- requested_by
- status
- user_decision
```

## Memory

```text
Memory
- id
- type
- content
- source
- relevance
- sensitivity
- embeddings
```

---

# 22. First Development Milestone

Do not begin with every integration.

Build a vertical slice first.

## Milestone 1

```text
Chat UI
   |
   v
FastAPI
   |
   v
Conversation Gateway
   |
   v
Orchestrator
   |
   v
Claude Provider
   |
   v
Structured Plan
   |
   v
Simple Agent
   |
   v
One Tool
   |
   v
Result
   |
   v
Chat UI
```

Recommended first tool: GitHub or a mock tool.

Success criteria:

User says:

> Check project X.

SUNIL:

1. Understands the request.
2. Produces JSON plan.
3. Creates task.
4. Starts Project Manager Agent.
5. Calls tool.
6. Analyses result.
7. Returns answer.
8. Logs everything.

Only after this flow works should additional agents/tools be added.

---

# 23. Suggested V1 Build Order

## Step 1 — Foundation

- [ ] Initialise repository
- [ ] Docker Compose
- [ ] PostgreSQL
- [ ] Redis
- [ ] FastAPI
- [ ] Next.js
- [ ] Environment handling
- [ ] Authentication stub
- [ ] Logging

## Step 2 — Provider Abstraction

- [ ] Base LLM interface
- [ ] Claude adapter
- [ ] OpenAI adapter
- [ ] Model Router
- [ ] Structured-output helper

## Step 3 — Conversation

- [ ] Conversation endpoints
- [ ] Streaming
- [ ] Message persistence
- [ ] Context loading

## Step 4 — Orchestrator

- [ ] Intent schema
- [ ] Plan schema
- [ ] Plan generation
- [ ] Plan validation
- [ ] Task state machine

## Step 5 — First Agent

- [ ] Project Manager Agent
- [ ] Agent configuration
- [ ] Agent execution loop

## Step 6 — First Tool

- [ ] GitHub adapter
- [ ] Permission wrapper
- [ ] Audit logging

## Step 7 — Complete Vertical Slice

- [ ] Chat request
- [ ] Reasoning
- [ ] Planning
- [ ] Agent execution
- [ ] Tool call
- [ ] Final response
- [ ] Logs

## Step 8 — Dashboard

- [ ] Chat
- [ ] Task list
- [ ] Agent activity
- [ ] Running workflows
- [ ] Approvals

## Step 9 — Memory

- [ ] Project entities
- [ ] Long-term memory
- [ ] RAG
- [ ] Preferences

## Step 10 — Remaining Agents

- [ ] Personal Assistant
- [ ] Codely Executive
- [ ] Developer
- [ ] QA
- [ ] DevOps
- [ ] Support
- [ ] Email

## Step 11 — Remaining Tools

- [ ] Gmail
- [ ] Calendar
- [ ] Project system
- [ ] Support system
- [ ] Browser
- [ ] Terminal
- [ ] Docker
- [ ] SSH

## Step 12 — Voice

- [ ] STT
- [ ] TTS
- [ ] Voice UI
- [ ] Streaming responses

## Step 13 — Scheduler

- [ ] Recurring tasks
- [ ] Scheduled workflows
- [ ] Notifications

## Step 14 — V1 Hardening

- [ ] Unit tests
- [ ] Integration tests
- [ ] Agent evaluation suite
- [ ] Permission tests
- [ ] Security review
- [ ] Failure/retry testing
- [ ] Usage/cost monitoring
- [ ] Backup strategy

---

# 24. Initial API Boundaries

Suggested API groups:

```text
/api/auth
/api/conversations
/api/messages
/api/tasks
/api/workflows
/api/agents
/api/tools
/api/models
/api/memory
/api/approvals
/api/notifications
/api/calendar
/api/system
/api/voice
```

WebSocket channels:

```text
/ws/conversations/{id}
/ws/tasks
/ws/agents
/ws/notifications
/ws/system
```

---

# 25. Structured LLM Output Rule

Whenever SUNIL asks an LLM to make a system decision, require structured output.

Example:

```json
{
  "intent": "project_status_review",
  "confidence": 0.94,
  "privacy_level": "internal",
  "objective": "Review today's PDA development progress",
  "agents": [
    "project_manager"
  ],
  "tools": [
    "github",
    "project_tracker"
  ],
  "steps": [
    {
      "id": "step_1",
      "action": "load_planned_tasks"
    },
    {
      "id": "step_2",
      "action": "load_developer_activity"
    },
    {
      "id": "step_3",
      "action": "compare_plan_to_progress"
    }
  ]
}
```

Do not let free-form LLM output directly trigger privileged actions.

---

# 26. Security Rules

These rules should exist from V1.

1. LLMs do not receive unrestricted credentials.
2. Tool calls must pass through controlled adapters.
3. Production access must be explicitly scoped.
4. Dangerous actions require approval.
5. Secrets must be stored outside prompts.
6. Every important action must be auditable.
7. Agents should run with least privilege.
8. Tool arguments must be validated.
9. Sensitive memory must carry privacy classifications.
10. Model Router must respect LOCAL ONLY data.
11. Prompt injection from external content must be treated as untrusted input.
12. Browser/email/document content must never automatically override SUNIL system rules.

---

# 27. Evaluation Framework

Create tests for agents, not only code.

Example evaluation categories:

```text
Intent understanding
Planning correctness
Tool selection
Tool argument accuracy
Permission compliance
Memory retrieval
Hallucination rate
Task completion
Final response quality
Escalation correctness
Latency
Cost
```

Store evaluation results so V2 routing can use real evidence.

---

# 28. Logging & Observability

Each request should be traceable.

```text
Request ID
 |
 +-- User message
 +-- Context loaded
 +-- Memory retrieved
 +-- Model selected
 +-- LLM input/output
 +-- Plan created
 +-- Agent started
 +-- Tool requested
 +-- Permission decision
 +-- Tool result
 +-- Agent result
 +-- Evaluation
 +-- Final response
```

Dashboard should later expose a developer/debug trace view.

---

# 29. Cost Tracking

Track cloud usage from V1.

Per request:

- Provider
- Model
- Input tokens
- Output tokens
- Estimated cost
- Agent
- Task
- Workflow

This data will help determine which workloads should move local in V2.

---

# 30. Training Data Preparation Starts in V1

Do not train yet.

But structure data so useful examples can be retained later.

Capture:

- Successful requests
- Correct plans
- User edits
- User approvals
- Rejected outputs
- Corrected emails
- Development decisions
- Tool traces
- Agent collaboration traces
- Final accepted results

V3 training quality will depend heavily on how cleanly V1/V2 data is captured.

---

# 31. Three-Phase Summary

```text
=============================================================
V1 — SUNIL CORE
=============================================================

Cloud-first Agentic OS

Build:
- Dashboard
- Chat
- Voice
- Conversation Gateway
- Central Orchestrator
- Model Router
- Agents
- Tools
- Memory
- Permissions
- Approval system
- Scheduler

Result:
A functional, useful Agentic OS.


                         |
                         v


=============================================================
V2 — SUNIL HYBRID
=============================================================

Local + Cloud intelligence

Build:
- Local Qwen server
- Local provider
- Privacy classifier
- Intelligent routing
- Shadow mode
- Local voice
- Agent collaboration
- Autonomous workflows
- Performance evaluation

Result:
A private hybrid Agentic OS.


                         |
                         v


=============================================================
V3 — PERSONALISED SUNIL
=============================================================

Local-first personal AI

Build:
- Training dataset
- Fine-tuned local model
- Personal behaviour model
- Local-first intelligence
- Proactive monitoring
- Autonomous delegation
- Controlled computer access
- Continuous learning/evaluation

Result:
A personal autonomous AI operating system.
```

---

# 32. Immediate Next Action

Start only with this:

```text
PHASE 1
  |
  v
V1 FOUNDATION
  |
  +-- Repository
  +-- FastAPI
  +-- Next.js
  +-- PostgreSQL
  +-- Redis
  +-- Docker
  |
  v
MODEL ABSTRACTION
  |
  +-- Claude
  +-- OpenAI
  +-- Model Router
  |
  v
CONVERSATION
  |
  v
ORCHESTRATOR
  |
  v
PROJECT MANAGER AGENT
  |
  v
ONE TOOL
  |
  v
END-TO-END VERTICAL SLICE
```

Do **not** begin by implementing every agent, every tool, local training, or computer control.

The first engineering target is:

> A user message enters SUNIL, an LLM understands it, SUNIL creates and validates a structured plan, an agent executes that plan through a controlled tool, and SUNIL returns and logs the result.

Once that works reliably, build outward.

---

# 33. Non-Negotiable Design Rules

1. **SUNIL is the product; models are replaceable resources.**
2. **The Central Orchestrator controls execution but does not pretend to think.**
3. **LLMs reason; deterministic code controls privileged actions.**
4. **Agents are roles/workflows, not permanently attached to one LLM.**
5. **All tools pass through permission and audit layers.**
6. **Sensitive actions require explicit approval until proven safe.**
7. **Memory and RAG hold changing knowledge; fine-tuning teaches behaviour.**
8. **Local AI is added only after V1 works reliably.**
9. **Cloud models remain available as escalation/specialist resources.**
10. **Every important request, model decision, tool call, and action must be observable.**
11. **Security and permissions are core architecture, not later additions.**
12. **Build a vertical slice before expanding the system.**

---

# 34. Final Target

```text
                         YOU
                          |
           +--------------+--------------+
           |              |              |
       Dashboard         Chat           Voice
           |              |              |
           +--------------+--------------+
                          |
                          v
                    SUNIL CORE
                          |
             Central Orchestrator
                          |
           +--------------+--------------+
           |                             |
        Memory                       Model Router
                                         |
                    +--------------------+--------------------+
                    |                    |                    |
                 Local AI             Claude              Codex
                    |                    |                    |
                    +--------------------+--------------------+
                                         |
                                      Agents
                                         |
              +--------------------------+-------------------------+
              |              |             |          |            |
             PM          Developer         QA       DevOps       Support
              |              |             |          |            |
              +--------------------------+-------------------------+
                                         |
                                      Tools
                                         |
        +------------+----------+----------+----------+-------------+
        |            |          |          |          |             |
      GitHub       Gmail       Jira       AWS       Browser     Databases
```

SUNIL should ultimately operate as the permanent orchestration, memory, security, workflow, and user-interface layer.

The underlying AI models can change without requiring the Agentic OS to be redesigned.
