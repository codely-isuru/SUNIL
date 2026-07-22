/**
 * The e2e harness.
 *
 * Every behavioural test in this app runs against a REAL Nest application on the Fastify
 * adapter, talking to a REAL Postgres, exercised through `app.inject()` — the same code path
 * a network request takes, minus the socket. No guard, interceptor or filter is stubbed:
 * if a test passes here, the shipped middleware chain is what made it pass.
 *
 * The suite self-skips when `SUNIL_TEST_DATABASE_URL` is unset, so `pnpm test` stays green
 * on a machine with no containers (FR-003). The Phase 1 acceptance run sets it:
 *
 *   docker run -d --name t3-pg -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_USER=sunil \
 *     -e POSTGRES_DB=sunil -p 55433:5432 pgvector/pgvector:pg16
 *   DATABASE_URL=postgresql://sunil@localhost:55433/sunil?schema=public pnpm db:deploy
 *   SUNIL_TEST_DATABASE_URL=... pnpm --filter @sunil/api test
 */
import { randomUUID } from "node:crypto";
import type { Type } from "@nestjs/common";
import type { NestFastifyApplication } from "@nestjs/platform-fastify";
import { UnitOfWork, AuditService, bootstrap, createPrismaClient, type SunilPrismaClient } from "@sunil/db";
import { createApiApp } from "../app.factory.js";
import { ApiConfig } from "../config/api-config.js";
import { InMemoryCounterStore, type CounterStore } from "../ratelimit/counter-store.js";
import type { QueuePort, QueueStatus } from "../jobs/queue.port.js";

export const TEST_DSN = process.env["SUNIL_TEST_DATABASE_URL"];
export const TEST_REDIS_URL = process.env["SUNIL_TEST_REDIS_URL"];

export const OWNER_EMAIL = "owner@sunil.test";
export const OWNER_PASSWORD = "owner-initial-passphrase-1";

/** A 32-byte key generated per run. No key material is committed anywhere. */
export function testMasterKey(): string {
  return Buffer.alloc(32, 7).toString("base64");
}

export function testEnv(overrides: Record<string, string> = {}): NodeJS.ProcessEnv {
  return {
    NODE_ENV: "test",
    DATABASE_URL: TEST_DSN ?? "postgresql://localhost:5432/none",
    REDIS_URL: TEST_REDIS_URL ?? "redis://localhost:6379",
    SUNIL_MASTER_KEY: testMasterKey(),
    SUNIL_COOKIE_SECURE: "false",
    // Deliberately generous so an unrelated test cannot trip the limiter; the rate-limit
    // tests build their own app with a low ceiling, which is the point of it being config.
    SUNIL_RATE_AUTH_IP_PER_MIN: "10000",
    SUNIL_RATE_SESSION_PER_MIN: "10000",
    ...overrides,
  } as NodeJS.ProcessEnv;
}

/** A queue double: `apps/api` only produces and observes, so this is the whole surface. */
export class FakeQueuePort implements QueuePort {
  readonly enqueued: { agentId: string; taskId: string; correlationId: string }[] = [];

  async enqueueAgentRun(args: { agentId: string; taskId: string; correlationId: string }) {
    this.enqueued.push(args);
    return { jobId: `fake-${this.enqueued.length}` };
  }

  async status(): Promise<QueueStatus> {
    return {
      queues: [
        { queue: "system", waiting: 0, active: 0, completed: 0, failed: 0, delayed: 0 },
        { queue: "agents", waiting: this.enqueued.length, active: 0, completed: 0, failed: 0, delayed: 0 },
      ],
      schedulers: [],
    };
  }

  async ping(): Promise<boolean> {
    return true;
  }

  async close(): Promise<void> {}
}

export interface TestApp {
  readonly app: NestFastifyApplication;
  readonly prisma: SunilPrismaClient;
  readonly queue: FakeQueuePort;
  readonly counters: CounterStore;
  close(): Promise<void>;
}

/**
 * NOTE the absence of `audit_logs`. The initial migration installs BOTH an append-only
 * trigger and a `BEFORE TRUNCATE` trigger on that table, so it cannot be cleared through the
 * application role at all — not by DELETE and not by TRUNCATE. The harness does not fight
 * that (disabling the trigger to make tests convenient would hollow out the control it is
 * meant to prove): audit rows accumulate across the run and every assertion scopes itself by
 * `correlationId`, which is unique per request.
 */
const ALL_TABLES = [
  "usage_records",
  "job_executions",
  "agent_messages",
  "agents",
  "mfa_recovery_codes",
  "mfa_credentials",
  "sessions",
  "invitations",
  "user_roles",
  "role_permissions",
  "permissions",
  "system_settings",
  "llm_providers",
  "secrets",
  "roles",
  "users",
];

/**
 * TRUNCATE, then re-bootstrap. TRUNCATE is deliberate: `audit_logs` carries a BEFORE
 * UPDATE OR DELETE trigger, so a `DELETE` would be rejected by the database — which is
 * exactly the append-only property ET-3 3.4 proves, and a reset routine must not need it
 * relaxed.
 */
export async function resetDatabase(prisma: SunilPrismaClient): Promise<void> {
  await prisma.$executeRawUnsafe(
    `TRUNCATE TABLE ${ALL_TABLES.map((t) => `"${t}"`).join(", ")} RESTART IDENTITY CASCADE`,
  );
  const audit = new AuditService(prisma);
  const uow = new UnitOfWork(prisma, audit);
  await bootstrap({
    prisma,
    uow,
    env: {
      DATABASE_URL: TEST_DSN ?? "",
      SUNIL_MASTER_KEY: testMasterKey(),
      SUNIL_OWNER_EMAIL: OWNER_EMAIL,
      SUNIL_OWNER_INITIAL_PASSWORD: OWNER_PASSWORD,
    } as NodeJS.ProcessEnv,
  });
}

export interface CreateTestAppOptions {
  readonly env?: Record<string, string>;
  readonly extraControllers?: readonly Type<unknown>[];
  readonly counterStore?: CounterStore;
  readonly reset?: boolean;
  readonly onRoute?: (route: { method: string; path: string }) => void;
  readonly logger?: { readonly level?: string; readonly destination?: NodeJS.WritableStream };
}

export async function createTestApp(options: CreateTestAppOptions = {}): Promise<TestApp> {
  if (!TEST_DSN) throw new Error("SUNIL_TEST_DATABASE_URL is required for the API e2e suite");

  const prisma = createPrismaClient({ datasourceUrl: TEST_DSN });
  if (options.reset !== false) await resetDatabase(prisma);

  const config = ApiConfig.load(testEnv(options.env));
  const queue = new FakeQueuePort();
  const counters = options.counterStore ?? new InMemoryCounterStore();

  const app = await createApiApp(
    {
      config,
      prisma,
      queue,
      counterStore: counters,
      ...(options.extraControllers ? { extraControllers: options.extraControllers } : {}),
      ...(options.logger ? { logger: options.logger } : {}),
    },
    options.onRoute ? { onRoute: options.onRoute } : {},
  );

  return {
    app,
    prisma,
    queue,
    counters,
    async close() {
      await app.close();
      await prisma.$disconnect();
    },
  };
}

export interface InjectOptions {
  readonly method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  readonly url: string;
  readonly payload?: unknown;
  readonly cookie?: string;
  readonly csrfToken?: string;
  readonly headers?: Record<string, string>;
}

export interface InjectResult {
  readonly statusCode: number;
  readonly headers: Record<string, string | string[] | undefined>;
  readonly raw: string;
  json<T = Record<string, unknown>>(): T;
}

export async function call(app: NestFastifyApplication, options: InjectOptions): Promise<InjectResult> {
  const headers: Record<string, string> = { ...(options.headers ?? {}) };
  if (options.cookie) headers["cookie"] = options.cookie;
  if (options.csrfToken) headers["x-csrf-token"] = options.csrfToken;

  const response = await app.inject({
    method: options.method,
    url: options.url,
    headers,
    ...(options.payload === undefined ? {} : { payload: options.payload as object }),
  });

  const raw = response.body;
  return {
    statusCode: response.statusCode,
    headers: response.headers as Record<string, string | string[] | undefined>,
    raw,
    json<T = Record<string, unknown>>(): T {
      return JSON.parse(raw) as T;
    },
  };
}

export interface Principal {
  readonly cookie: string;
  readonly csrfToken: string;
  readonly userId: string;
  readonly email: string;
}

export function setCookieValue(result: InjectResult): string {
  const raw = result.headers["set-cookie"];
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (!value) throw new Error("no Set-Cookie header on the response");
  return value.split(";")[0]!;
}

export async function login(
  app: NestFastifyApplication,
  email: string,
  password: string,
): Promise<Principal> {
  const response = await call(app, {
    method: "POST",
    url: "/api/auth/login",
    payload: { email, password },
  });
  if (response.statusCode !== 200) {
    throw new Error(`login failed: ${response.statusCode} ${response.raw}`);
  }
  const body = response.json<{ user: { id: string }; csrfToken: string }>();
  return {
    cookie: setCookieValue(response),
    csrfToken: body.csrfToken,
    userId: body.user.id,
    email,
  };
}

export function loginAsOwner(app: NestFastifyApplication): Promise<Principal> {
  return login(app, OWNER_EMAIL, OWNER_PASSWORD);
}

/**
 * Create a second principal with a chosen role, through the real invitation flow — the only
 * way a user can come into existence in Phase 1 besides bootstrap.
 */
export async function inviteAndAccept(
  app: NestFastifyApplication,
  owner: Principal,
  roleId: string,
  password = `invited-passphrase-${randomUUID().slice(0, 8)}`,
): Promise<Principal> {
  const email = `user-${randomUUID().slice(0, 8)}@sunil.test`;

  const invitation = await call(app, {
    method: "POST",
    url: "/api/invitations",
    payload: { email, roleId },
    cookie: owner.cookie,
    csrfToken: owner.csrfToken,
  });
  if (invitation.statusCode !== 201) {
    throw new Error(`invite failed: ${invitation.statusCode} ${invitation.raw}`);
  }
  const { token } = invitation.json<{ token: string }>();

  const accepted = await call(app, {
    method: "POST",
    url: `/api/invitations/${token}/accept`,
    payload: { password },
  });
  if (accepted.statusCode !== 201) {
    throw new Error(`accept failed: ${accepted.statusCode} ${accepted.raw}`);
  }

  return login(app, email, password);
}
