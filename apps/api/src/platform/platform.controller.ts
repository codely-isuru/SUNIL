/**
 * `/api/settings`, `/api/providers`, `/api/agents`, `/api/audit`, `/api/usage`, `/api/jobs`
 * — the remainder of the §13 surface.
 *
 * Grouped in one file because each is three thin handlers over a service; splitting them
 * into six modules would add ceremony without adding a boundary.
 */
import { Body, Controller, Get, HttpCode, Inject, Param, Patch, Post, Query } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import {
  AgentCreateSchema,
  AgentUpdateSchema,
  AuditFilterSchema,
  NotFoundError,
  PageRequestSchema,
  UuidSchema,
  z,
} from "@sunil/core";
import type { AuditServiceContract, JobExecutionRepository, UsageRepository } from "@sunil/db";
import { Audited, RequiresPermission } from "../common/declarations.js";
import { currentContext } from "../common/request-context.js";
import { parseInput } from "../common/validation.js";
import { TOKENS } from "../tokens.js";
import type { QueuePort } from "../jobs/queue.port.js";
import type { AgentsService } from "./agents.service.js";
import type { ProvidersService } from "./providers.service.js";
import type { SettingsService } from "./settings.service.js";

const SettingUpdateSchema = z.object({ value: z.unknown() });

const ProviderUpdateSchema = z
  .object({
    enabled: z.boolean().optional(),
    baseUrl: z.string().trim().max(2000).nullish(),
    defaultModel: z.string().trim().max(200).nullish(),
    /** A SecretStore REFERENCE name. There is no field here that could carry a value. */
    credentialName: z.string().trim().max(200).nullish(),
  })
  .refine((value) => Object.keys(value).length > 0, {
    message: "at least one field must be supplied",
  });

@ApiTags("settings")
@Controller("settings")
export class SettingsController {
  constructor(@Inject(TOKENS.SettingsService) private readonly settings: SettingsService) {}

  @Get()
  @RequiresPermission("settings:read")
  async list() {
    return { items: await this.settings.list() };
  }

  @Patch(":key")
  @RequiresPermission("settings:write")
  @Audited("settings.update")
  async update(@Param("key") key: string, @Body() body: unknown) {
    const input = parseInput(SettingUpdateSchema, body);
    const userId = currentContext()?.session?.userId ?? null;
    return this.settings.update(key, input.value as never, userId);
  }
}

@ApiTags("providers")
@Controller("providers")
export class ProvidersController {
  constructor(@Inject(TOKENS.ProvidersService) private readonly providers: ProvidersService) {}

  @Get()
  @RequiresPermission("provider:read")
  @ApiOperation({
    summary:
      "LLM provider configuration. `verificationStatus` is never LIVE_VERIFIED in Phase 1 (FR-065).",
  })
  async list() {
    return { items: await this.providers.list() };
  }

  @Patch(":id")
  @RequiresPermission("provider:write")
  @Audited("provider.update")
  update(@Param("id") id: string, @Body() body: unknown) {
    return this.providers.update(
      parseInput(UuidSchema, id),
      parseInput(ProviderUpdateSchema, body),
    );
  }
}

@ApiTags("agents")
@Controller("agents")
export class AgentsController {
  constructor(@Inject(TOKENS.AgentsService) private readonly agents: AgentsService) {}

  @Get()
  @RequiresPermission("agent:read")
  async list() {
    return { items: await this.agents.list() };
  }

  @Get(":id/activity")
  @RequiresPermission("agent:read")
  @ApiOperation({ summary: "Agent envelopes in emission order (FR-072)" })
  async activity(@Param("id") id: string, @Query() query: unknown) {
    const page = parseInput(PageRequestSchema, query ?? {});
    return { items: await this.agents.activity(parseInput(UuidSchema, id), page) };
  }

  @Post()
  @RequiresPermission("agent:write")
  @Audited("agent.create")
  @HttpCode(201)
  create(@Body() body: unknown) {
    const input = parseInput(AgentCreateSchema, body);
    return this.agents.create({
      slug: input.slug,
      name: input.name,
      role: input.role,
      systemInstructions: input.systemInstructions,
      maxDurationSeconds: input.maxDurationSeconds,
      heartbeatIntervalSeconds: input.heartbeatIntervalSeconds,
      staleThresholdSeconds: input.staleThresholdSeconds,
      toolAllowlist: input.toolAllowlist ?? [],
      providerId: input.providerId ?? null,
      modelId: input.modelId ?? null,
      tokenBudget: input.tokenBudget ?? null,
      costBudgetUsd: input.costBudgetUsd ?? null,
      enabled: input.enabled ?? true,
    });
  }

  @Patch(":id")
  @RequiresPermission("agent:write")
  @Audited("agent.update")
  update(@Param("id") id: string, @Body() body: unknown) {
    const input = parseInput(AgentUpdateSchema, body);
    return this.agents.update(parseInput(UuidSchema, id), input as never);
  }

  @Post(":id/run")
  @RequiresPermission("agent:write")
  @Audited("agent.run")
  @HttpCode(202)
  @ApiOperation({ summary: "Enqueue a skeleton demo run on the agents queue" })
  run(@Param("id") id: string) {
    const correlationId = currentContext()?.correlationId ?? "unknown";
    return this.agents.run(parseInput(UuidSchema, id), correlationId);
  }
}

@ApiTags("audit")
@Controller("audit")
export class AuditController {
  constructor(@Inject(TOKENS.AuditService) private readonly audit: AuditServiceContract) {}

  @Get()
  @RequiresPermission("audit:read")
  @ApiOperation({
    summary: "Query the append-only audit log. Payloads were redacted at write time (FR-053).",
  })
  query(@Query() query: unknown) {
    const raw = (query ?? {}) as Record<string, unknown>;
    const filter = parseInput(AuditFilterSchema, raw);
    const page = parseInput(PageRequestSchema, raw);
    return this.audit.query(filter, page);
  }
}

@ApiTags("usage")
@Controller("usage")
export class UsageController {
  constructor(@Inject(TOKENS.UsageRepository) private readonly usage: UsageRepository) {}

  @Get()
  @RequiresPermission("usage:read")
  list(@Query() query: unknown) {
    return this.usage.listPaged(parseInput(PageRequestSchema, query ?? {}));
  }
}

@ApiTags("jobs")
@Controller("jobs")
export class JobsController {
  constructor(
    @Inject(TOKENS.Queue) private readonly queue: QueuePort,
    @Inject(TOKENS.JobExecutionRepository) private readonly history: JobExecutionRepository,
  ) {}

  @Get("status")
  @RequiresPermission("job:read")
  @ApiOperation({ summary: "Per-queue counts and the registered Job Schedulers (§12.5)" })
  status() {
    return this.queue.status();
  }

  @Get("history")
  @RequiresPermission("job:read")
  @ApiOperation({ summary: "Execution history from Postgres — survives a Redis wipe (FR-083)" })
  history_(@Query() query: unknown) {
    return this.history.listPaged(parseInput(PageRequestSchema, query ?? {}));
  }
}

/** Re-exported so the enumeration test can assert a stable controller set. */
export const NOT_FOUND = NotFoundError;
