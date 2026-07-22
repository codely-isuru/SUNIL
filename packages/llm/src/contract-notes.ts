/**
 * Recorded provider-contract ambiguities (risk R-01: "where a provider's contract is
 * ambiguous, record it rather than guessing silently").
 *
 * Each entry is a decision this package made that a live endpoint would settle in one line.
 * They are exported as data so the phase report and the providers page can list them next
 * to the "unverified against live endpoints" label instead of burying them in comments.
 */
import type { ProviderSlug } from "@sunil/core";

export interface ContractNote {
  readonly provider: ProviderSlug;
  /** Short id so a Phase 2 smoke test can tick items off. */
  readonly id: string;
  readonly ambiguity: string;
  readonly decision: string;
}

export const CONTRACT_NOTES: readonly ContractNote[] = [
  {
    provider: "anthropic",
    id: "anthropic.system-messages",
    ambiguity:
      "Our CompletionRequest allows `system` messages inline; the Messages API takes a separate top-level `system` parameter.",
    decision:
      "All `system` messages are concatenated (newline-joined, original order) into the top-level `system` parameter and removed from `messages`.",
  },
  {
    provider: "anthropic",
    id: "anthropic.stream-usage",
    ambiguity:
      "Streaming token counts arrive split across `message_start` (input) and `message_delta` (output) events.",
    decision:
      "Both are accumulated; the usage row for a stream is written when the iterator finishes. If the stream is abandoned early, the row carries the counts seen so far.",
  },
  {
    provider: "openai",
    id: "openai.max-tokens-field",
    ambiguity:
      "`max_tokens` is deprecated in favour of `max_completion_tokens`; older models/proxies accept only the former.",
    decision:
      "We send `max_completion_tokens`. A live smoke test against an older deployment is the only way to confirm this is safe for every target model.",
  },
  {
    provider: "openai",
    id: "openai.embedding-token-counts",
    ambiguity:
      "The embeddings response reports `prompt_tokens`/`total_tokens` only — there is no output-token concept.",
    decision: "`tokensIn` = prompt_tokens, `tokensOut` = 0 on every embedding usage row.",
  },
  {
    provider: "openai",
    id: "openai.embedding-encoding",
    ambiguity:
      "The SDK silently requests `encoding_format: \"base64\"` and decodes the result to a Float32Array, so the wire shape differs from the documented float-array response.",
    decision:
      "We accept the SDK default (its decode path is then exercised by the fixtures) and normalise with `Array.from`, so a float array and a Float32Array both yield `number[]`.",
  },
  {
    provider: "ollama",
    id: "ollama.token-count-fields",
    ambiguity:
      "Ollama reports `prompt_eval_count` / `eval_count`, and both are omitted for some models and some cached responses.",
    decision: "Missing counts are recorded as 0 rather than guessed or estimated from text length.",
  },
  {
    provider: "ollama",
    id: "ollama.embed-endpoint",
    ambiguity:
      "Both `/api/embed` (batch, `embeddings`) and the older `/api/embeddings` (single, `embedding`) exist depending on server version.",
    decision:
      "We call `/api/embed` and read `embeddings`. Against an older server this returns a 404, which surfaces as a typed `contract` ProviderError rather than a silent empty vector.",
  },
];

export function contractNotesFor(provider: ProviderSlug): readonly ContractNote[] {
  return CONTRACT_NOTES.filter((note) => note.provider === provider);
}
