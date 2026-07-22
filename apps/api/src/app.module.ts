/**
 * The composition root.
 *
 * Assembled as a dynamic module so that exactly one wiring definition serves both the
 * process (`main.ts`) and the tests — a test never re-declares providers, it only substitutes
 * the two adapters that need a container (`CounterStore`, `QueuePort`) and, for the ET-3
 * negative control, appends a deliberately undecorated controller.
 *
 * Guard order is the §7.3 chain and it is load-bearing:
 *
 *     SessionGuard → CsrfGuard → RateLimitGuard → PermissionGuard → handler
 *
 * Interceptor order matters too: the audit tally is outermost, so it observes the tally
 * after every inner interceptor and the handler have finished.
 */
import {
  Module,
  RequestMethod,
  type DynamicModule,
  type Provider,
  type Type,
} from "@nestjs/common";
import { APP_FILTER, APP_GUARD, APP_INTERCEPTOR } from "@nestjs/core";
import { LoggerModule } from "nestjs-pino";
import { PINO_REDACT_PATHS, REDACTED } from "@sunil/core";
import {
  AgentMessageRepository,
  AgentRepository,
  AuditService,
  JobExecutionRepository,
  LlmProviderRepository,
  PermissionRepository,
  RoleRepository,
  SecretRepository,
  SessionRepository,
  SystemSettingRepository,
  UnitOfWork,
  UsageRepository,
  UserRepository,
  createPrismaClient,
  type AuditServiceContract,
  type SunilPrismaClient,
} from "@sunil/db";
import { randomUUID } from "node:crypto";
import { AuditedUnitOfWork } from "./audit/audited-unit-of-work.js";
import { DenialRecorder } from "./audit/denial-recorder.js";
import { AuthController } from "./auth/auth.controller.js";
import { LoginService } from "./auth/login.service.js";
import { MfaService } from "./auth/mfa.service.js";
import { SessionService } from "./auth/session.service.js";
import { SunilExceptionFilter } from "./common/error.filter.js";
import type { ApiConfig } from "./config/api-config.js";
import { CsrfGuard } from "./guards/csrf.guard.js";
import { PermissionGuard } from "./guards/permission.guard.js";
import { RateLimitGuard } from "./guards/rate-limit.guard.js";
import { SessionGuard } from "./guards/session.guard.js";
import { HealthController } from "./health/health.controller.js";
import { AuditTallyInterceptor } from "./interceptors/audit-tally.interceptor.js";
import { IdempotencyInterceptor } from "./interceptors/idempotency.interceptor.js";
import { SecretSerialisationInterceptor } from "./interceptors/secret-serialisation.interceptor.js";
import { InvitationService } from "./invitations/invitation.service.js";
import { InvitationsController } from "./invitations/invitations.controller.js";
import { BullmqQueuePort } from "./jobs/bullmq-queue.js";
import type { QueuePort } from "./jobs/queue.port.js";
import {
  AgentsController,
  AuditController,
  JobsController,
  ProvidersController,
  SettingsController,
  UsageController,
} from "./platform/platform.controller.js";
import { AgentsService } from "./platform/agents.service.js";
import { ProvidersService } from "./platform/providers.service.js";
import { SettingsService } from "./platform/settings.service.js";
import { RbacController } from "./rbac/rbac.controller.js";
import { PermissionService } from "./rbac/permission.service.js";
import { RoleAssignmentService } from "./rbac/role-assignment.service.js";
import { RedisCounterStore } from "./ratelimit/redis-counter-store.js";
import type { CounterStore } from "./ratelimit/counter-store.js";
import { EnvelopeSecretStore } from "./secrets/envelope-secret-store.js";
import { SecretsController } from "./secrets/secrets.controller.js";
import { TOKENS } from "./tokens.js";
import { UserService } from "./users/user.service.js";
import { UsersController } from "./users/users.controller.js";
import { LifecycleService } from "./lifecycle.service.js";

/**
 * The complete §13 controller set. The route-enumeration test walks THIS list and
 * cross-checks it against Fastify's own route table, so a controller registered outside it
 * would fail the test rather than ship undeclared.
 */
export const API_CONTROLLERS: readonly Type<unknown>[] = [
  HealthController,
  AuthController,
  InvitationsController,
  UsersController,
  RbacController,
  SecretsController,
  SettingsController,
  ProvidersController,
  AgentsController,
  AuditController,
  UsageController,
  JobsController,
];

export interface ApiModuleOptions {
  readonly config: ApiConfig;
  /** Substituted only by tests and only for the two adapters that need a container. */
  readonly prisma?: SunilPrismaClient;
  readonly counterStore?: CounterStore;
  readonly queue?: QueuePort;
  /** ET-3 3.2's negative control registers an undecorated fixture controller here. */
  readonly extraControllers?: readonly Type<unknown>[];
  /**
   * Log level and destination. Present so ET-3 3.8 can capture real structured log output
   * and correlate it to an audit record by correlation id (NFR-012) — the alternative is
   * asserting that logging "probably" works, which proves nothing.
   */
  readonly logger?: { readonly level?: string; readonly destination?: NodeJS.WritableStream };
}

@Module({})
export class AppModule {
  static register(options: ApiModuleOptions): DynamicModule {
    const { config } = options;

    const providers: Provider[] = [
      { provide: TOKENS.Config, useValue: config },
      {
        provide: TOKENS.Prisma,
        useFactory: () =>
          options.prisma ?? createPrismaClient({ datasourceUrl: config.databaseUrl() }),
      },
      {
        provide: TOKENS.CounterStore,
        useFactory: () => options.counterStore ?? new RedisCounterStore(config.redisUrl()),
      },
      {
        provide: TOKENS.Queue,
        useFactory: () => options.queue ?? new BullmqQueuePort(config.redisUrl()),
      },

      // ── audit plumbing ────────────────────────────────────────────────────
      {
        provide: TOKENS.AuditService,
        useFactory: (prisma: SunilPrismaClient) => new AuditService(prisma),
        inject: [TOKENS.Prisma],
      },
      {
        provide: TOKENS.DenialRecorder,
        useFactory: (audit: AuditServiceContract) => new DenialRecorder(audit),
        inject: [TOKENS.AuditService],
      },
      {
        provide: TOKENS.UnitOfWork,
        useFactory: (prisma: SunilPrismaClient, audit: AuditServiceContract) =>
          new AuditedUnitOfWork(new UnitOfWork(prisma, audit)),
        inject: [TOKENS.Prisma, TOKENS.AuditService],
      },

      // ── repositories ──────────────────────────────────────────────────────
      repo(TOKENS.UserRepository, UserRepository),
      repo(TOKENS.RoleRepository, RoleRepository),
      repo(TOKENS.PermissionRepository, PermissionRepository),
      repo(TOKENS.SessionRepository, SessionRepository),
      repo(TOKENS.SecretRepository, SecretRepository),
      repo(TOKENS.SystemSettingRepository, SystemSettingRepository),
      repo(TOKENS.LlmProviderRepository, LlmProviderRepository),
      repo(TOKENS.AgentRepository, AgentRepository),
      repo(TOKENS.AgentMessageRepository, AgentMessageRepository),
      repo(TOKENS.UsageRepository, UsageRepository),
      repo(TOKENS.JobExecutionRepository, JobExecutionRepository),

      // ── domain services ───────────────────────────────────────────────────
      {
        provide: TOKENS.SessionService,
        useFactory: (prisma: SunilPrismaClient, sessions: SessionRepository) =>
          new SessionService(prisma, sessions, config),
        inject: [TOKENS.Prisma, TOKENS.SessionRepository],
      },
      {
        provide: TOKENS.PermissionService,
        useFactory: (users: UserRepository) => new PermissionService(users),
        inject: [TOKENS.UserRepository],
      },
      {
        provide: TOKENS.SecretStore,
        useFactory: (secrets: SecretRepository, uow: AuditedUnitOfWork) =>
          new EnvelopeSecretStore(secrets, uow, config),
        inject: [TOKENS.SecretRepository, TOKENS.UnitOfWork],
      },
      {
        provide: TOKENS.LoginService,
        useFactory: (
          users: UserRepository,
          sessions: SessionService,
          counters: CounterStore,
          uow: AuditedUnitOfWork,
          denials: DenialRecorder,
        ) => new LoginService(users, sessions, counters, uow, denials, config),
        inject: [
          TOKENS.UserRepository,
          TOKENS.SessionService,
          TOKENS.CounterStore,
          TOKENS.UnitOfWork,
          TOKENS.DenialRecorder,
        ],
      },
      {
        provide: TOKENS.MfaService,
        useFactory: (
          prisma: SunilPrismaClient,
          secrets: EnvelopeSecretStore,
          uow: AuditedUnitOfWork,
          denials: DenialRecorder,
          sessions: SessionService,
        ) => new MfaService(prisma, secrets, uow, denials, sessions),
        inject: [
          TOKENS.Prisma,
          TOKENS.SecretStore,
          TOKENS.UnitOfWork,
          TOKENS.DenialRecorder,
          TOKENS.SessionService,
        ],
      },
      {
        provide: TOKENS.UserService,
        useFactory: (
          prisma: SunilPrismaClient,
          users: UserRepository,
          uow: AuditedUnitOfWork,
          denials: DenialRecorder,
          sessions: SessionService,
          logins: LoginService,
        ) => new UserService(prisma, users, uow, denials, sessions, logins),
        inject: [
          TOKENS.Prisma,
          TOKENS.UserRepository,
          TOKENS.UnitOfWork,
          TOKENS.DenialRecorder,
          TOKENS.SessionService,
          TOKENS.LoginService,
        ],
      },
      {
        provide: TOKENS.RoleAssignmentService,
        useFactory: (
          prisma: SunilPrismaClient,
          permissions: PermissionService,
          uow: AuditedUnitOfWork,
        ) => new RoleAssignmentService(prisma, permissions, uow),
        inject: [TOKENS.Prisma, TOKENS.PermissionService, TOKENS.UnitOfWork],
      },
      {
        provide: TOKENS.InvitationService,
        useFactory: (
          prisma: SunilPrismaClient,
          users: UserRepository,
          uow: AuditedUnitOfWork,
          denials: DenialRecorder,
        ) => new InvitationService(prisma, users, uow, denials, config),
        inject: [TOKENS.Prisma, TOKENS.UserRepository, TOKENS.UnitOfWork, TOKENS.DenialRecorder],
      },
      {
        provide: TOKENS.SettingsService,
        useFactory: (settings: SystemSettingRepository, uow: AuditedUnitOfWork) =>
          new SettingsService(settings, uow),
        inject: [TOKENS.SystemSettingRepository, TOKENS.UnitOfWork],
      },
      {
        provide: TOKENS.ProvidersService,
        useFactory: (
          providers_: LlmProviderRepository,
          secrets: SecretRepository,
          uow: AuditedUnitOfWork,
        ) => new ProvidersService(providers_, secrets, uow),
        inject: [TOKENS.LlmProviderRepository, TOKENS.SecretRepository, TOKENS.UnitOfWork],
      },
      {
        provide: TOKENS.AgentsService,
        useFactory: (
          agents: AgentRepository,
          messages: AgentMessageRepository,
          uow: AuditedUnitOfWork,
          queue: QueuePort,
        ) => new AgentsService(agents, messages, uow, queue),
        inject: [
          TOKENS.AgentRepository,
          TOKENS.AgentMessageRepository,
          TOKENS.UnitOfWork,
          TOKENS.Queue,
        ],
      },

      LifecycleService,

      // ── the §7.3 guard chain, in order ────────────────────────────────────
      { provide: APP_GUARD, useClass: SessionGuard },
      { provide: APP_GUARD, useClass: CsrfGuard },
      { provide: APP_GUARD, useClass: RateLimitGuard },
      { provide: APP_GUARD, useClass: PermissionGuard },

      // ── interceptors ──────────────────────────────────────────────────────
      { provide: APP_INTERCEPTOR, useClass: AuditTallyInterceptor },
      { provide: APP_INTERCEPTOR, useClass: SecretSerialisationInterceptor },
      { provide: APP_INTERCEPTOR, useClass: IdempotencyInterceptor },

      { provide: APP_FILTER, useClass: SunilExceptionFilter },
    ];

    const pinoOptions = {
      level: options.logger?.level ?? (config.isProduction ? "info" : "warn"),
      // ONE redaction definition for logs and audit payloads alike (§9.5, NFR-011).
      redact: { paths: [...PINO_REDACT_PATHS], censor: REDACTED },
      // The request id IS the correlation id, so a log line and an audit row for the same
      // request carry the same value (NFR-012, ET-3 3.8).
      genReqId: (req: { headers: Record<string, unknown> }) =>
        (req.headers["x-correlation-id"] as string | undefined) ?? randomUUID(),
      autoLogging: true,
    };

    return {
      module: AppModule,
      imports: [
        LoggerModule.forRoot({
          pinoHttp: (options.logger?.destination
            ? [pinoOptions, options.logger.destination]
            : pinoOptions) as never,
          // `path-to-regexp` 8 requires a NAMED wildcard; nestjs-pino's default `*` is the
          // legacy form and makes Nest emit a deprecation warning on every boot.
          forRoutes: [{ path: "*path", method: RequestMethod.ALL }],
        }),
      ],
      controllers: [...API_CONTROLLERS, ...(options.extraControllers ?? [])],
      providers,
      exports: [TOKENS.Prisma, TOKENS.Config, TOKENS.SecretStore, TOKENS.UnitOfWork],
    };
  }
}

/** Repositories all share one shape: `new Repo(prisma)`. */
function repo<T>(token: string, Ctor: new (prisma: SunilPrismaClient) => T): Provider {
  return {
    provide: token,
    useFactory: (prisma: SunilPrismaClient) => new Ctor(prisma),
    inject: [TOKENS.Prisma],
  };
}
