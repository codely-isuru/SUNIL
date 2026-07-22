/**
 * DI tokens.
 *
 * Every provider is registered against an explicit string token and every constructor
 * parameter carries an explicit `@Inject`. That is not stylistic: `emitDecoratorMetadata`
 * is a TypeScript-only transform, and the test runner's transformer does not emit
 * `design:paramtypes`. Explicit tokens make the container behave identically under `tsc`
 * and under the test transform, so the wiring the tests exercise is the wiring that ships.
 */
export const TOKENS = {
  Config: "SUNIL_CONFIG",
  Prisma: "SUNIL_PRISMA",
  AuditService: "SUNIL_AUDIT_SERVICE",
  DenialRecorder: "SUNIL_DENIAL_RECORDER",
  UnitOfWork: "SUNIL_UNIT_OF_WORK",
  CounterStore: "SUNIL_COUNTER_STORE",
  SecretStore: "SUNIL_SECRET_STORE",
  Queue: "SUNIL_QUEUE",
  UserRepository: "SUNIL_USER_REPOSITORY",
  RoleRepository: "SUNIL_ROLE_REPOSITORY",
  PermissionRepository: "SUNIL_PERMISSION_REPOSITORY",
  SessionRepository: "SUNIL_SESSION_REPOSITORY",
  SecretRepository: "SUNIL_SECRET_REPOSITORY",
  SystemSettingRepository: "SUNIL_SYSTEM_SETTING_REPOSITORY",
  LlmProviderRepository: "SUNIL_LLM_PROVIDER_REPOSITORY",
  AgentRepository: "SUNIL_AGENT_REPOSITORY",
  AgentMessageRepository: "SUNIL_AGENT_MESSAGE_REPOSITORY",
  UsageRepository: "SUNIL_USAGE_REPOSITORY",
  JobExecutionRepository: "SUNIL_JOB_EXECUTION_REPOSITORY",
  SessionService: "SUNIL_SESSION_SERVICE",
  PermissionService: "SUNIL_PERMISSION_SERVICE",
  LoginService: "SUNIL_LOGIN_SERVICE",
  MfaService: "SUNIL_MFA_SERVICE",
  RoleAssignmentService: "SUNIL_ROLE_ASSIGNMENT_SERVICE",
  InvitationService: "SUNIL_INVITATION_SERVICE",
  UserService: "SUNIL_USER_SERVICE",
  SecretsService: "SUNIL_SECRETS_SERVICE",
  SettingsService: "SUNIL_SETTINGS_SERVICE",
  ProvidersService: "SUNIL_PROVIDERS_SERVICE",
  AgentsService: "SUNIL_AGENTS_SERVICE",
} as const;
