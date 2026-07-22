/**
 * In-loop budget and timeout enforcement (§11.4, FR-074).
 *
 * THE RULE: enforcement is these checks, never prompt text. A system prompt may mention a
 * limit for context, but the control is `RunGuard.check()` running AFTER EVERY STEP, plus the
 * `AbortController` deadline carried by in-flight LLM calls. The model is never asked to
 * self-limit.
 *
 * All three limits are per-agent CONFIGURATION (`maxDurationSeconds`, `tokenBudget`,
 * `costBudgetUsd`) — there are no constants in this file.
 */
import type { AgentConfig, BlockedReason } from "@sunil/core";

export interface HaltDecision {
  readonly halt: boolean;
  readonly reason?: BlockedReason;
  readonly detail?: string;
}

const CONTINUE: HaltDecision = { halt: false };

export class RunGuard {
  readonly #config: AgentConfig;
  readonly #now: () => number;
  readonly #startedAt: number;
  readonly #controller = new AbortController();
  #tokensUsed = 0;
  #costUsd = 0;

  constructor(config: AgentConfig, now: () => number = Date.now) {
    this.#config = config;
    this.#now = now;
    this.#startedAt = now();
  }

  /** Cancels in-flight provider calls the moment the run is halted (§11.4). */
  get signal(): AbortSignal {
    return this.#controller.signal;
  }

  get tokensUsed(): number {
    return this.#tokensUsed;
  }

  get costUsd(): number {
    return Math.round(this.#costUsd * 1_000_000) / 1_000_000;
  }

  get elapsedMs(): number {
    return this.#now() - this.#startedAt;
  }

  /** Milliseconds left before `maxDurationSeconds` is exhausted; never negative. */
  remainingMs(): number {
    return Math.max(0, this.#config.maxDurationSeconds * 1000 - this.elapsedMs);
  }

  /** Accumulate the usage a step actually consumed, from usage records — not an estimate. */
  addUsage(tokens = 0, costUsd = 0): void {
    this.#tokensUsed += tokens;
    this.#costUsd += costUsd;
  }

  /**
   * The check the loop runs after every step (and once before the first one). Returns a halt
   * decision rather than throwing, so the caller can emit `TASK_BLOCKED` with the reason and
   * persist it before unwinding.
   */
  check(): HaltDecision {
    const elapsed = this.elapsedMs;
    if (elapsed >= this.#config.maxDurationSeconds * 1000) {
      return this.#halt(
        "timeout",
        `elapsed ${Math.round(elapsed / 1000)}s reached maxDurationSeconds=${this.#config.maxDurationSeconds}`,
      );
    }

    const tokenBudget = this.#config.tokenBudget;
    if (tokenBudget !== null && tokenBudget !== undefined && this.#tokensUsed >= tokenBudget) {
      return this.#halt("budget", `tokensUsed ${this.#tokensUsed} reached tokenBudget=${tokenBudget}`);
    }

    const costBudget = this.#config.costBudgetUsd;
    if (costBudget !== null && costBudget !== undefined && this.costUsd >= costBudget) {
      return this.#halt("budget", `costUsd ${this.costUsd} reached costBudgetUsd=${costBudget}`);
    }

    return CONTINUE;
  }

  /** Abort in-flight work for a reason decided elsewhere (e.g. an external STALE transition). */
  abort(reason?: unknown): void {
    if (!this.#controller.signal.aborted) this.#controller.abort(reason);
  }

  #halt(reason: BlockedReason, detail: string): HaltDecision {
    this.abort(new Error(detail));
    return { halt: true, reason, detail };
  }
}
