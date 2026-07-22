/**
 * Fixture payloads captured from PUBLISHED provider response shapes — TEST/DEV ONLY.
 *
 * These are the contract-drift detector referenced by ADR-008: when Phase 2 obtains real
 * keys, the live smoke test diffs real responses against these fixtures, and any difference
 * is exactly the R-01 risk materialising. Streaming fixtures are raw SSE/NDJSON text so the
 * SDK framing code runs for real.
 *
 * No fixture contains a credential. `sk-…`-shaped strings never appear here.
 */

export const ANTHROPIC_MESSAGE_FIXTURE = {
  id: "msg_01FixtureOnly",
  type: "message",
  role: "assistant",
  model: "claude-sonnet-4-5",
  content: [{ type: "text", text: "Fixture completion from a mocked transport." }],
  stop_reason: "end_turn",
  stop_sequence: null,
  usage: { input_tokens: 42, output_tokens: 17 },
};

/** SSE bytes, exactly as the Messages API frames a stream. */
export const ANTHROPIC_STREAM_SSE = [
  'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_01FixtureStream","type":"message","role":"assistant","model":"claude-sonnet-4-5","content":[],"stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":11,"output_tokens":0}}}\n\n',
  'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n',
  'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n',
  'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" world"}}\n\n',
  'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
  'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":7}}\n\n',
  'event: message_stop\ndata: {"type":"message_stop"}\n\n',
].join("");

export const ANTHROPIC_RATE_LIMIT_FIXTURE = {
  type: "error",
  error: { type: "rate_limit_error", message: "Number of request tokens has exceeded your rate limit" },
};

export const ANTHROPIC_SERVER_ERROR_FIXTURE = {
  type: "error",
  error: { type: "api_error", message: "Internal server error" },
};

export const OPENAI_COMPLETION_FIXTURE = {
  id: "chatcmpl-fixture",
  object: "chat.completion",
  created: 1_700_000_000,
  model: "gpt-4.1-mini",
  choices: [
    {
      index: 0,
      message: { role: "assistant", content: "Fixture completion from a mocked transport." },
      finish_reason: "stop",
    },
  ],
  usage: { prompt_tokens: 31, completion_tokens: 9, total_tokens: 40 },
};

export const OPENAI_STREAM_SSE = [
  'data: {"id":"chatcmpl-fixture","object":"chat.completion.chunk","created":1700000000,"model":"gpt-4.1-mini","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"},"finish_reason":null}]}\n\n',
  'data: {"id":"chatcmpl-fixture","object":"chat.completion.chunk","created":1700000000,"model":"gpt-4.1-mini","choices":[{"index":0,"delta":{"content":" world"},"finish_reason":null}]}\n\n',
  'data: {"id":"chatcmpl-fixture","object":"chat.completion.chunk","created":1700000000,"model":"gpt-4.1-mini","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n',
  'data: {"id":"chatcmpl-fixture","object":"chat.completion.chunk","created":1700000000,"model":"gpt-4.1-mini","choices":[],"usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18}}\n\n',
  "data: [DONE]\n\n",
].join("");

/**
 * NOTE the base64 embeddings: the `openai` SDK requests `encoding_format: "base64"` by
 * default and decodes it to a Float32Array. Capturing the fixture in the shape the SDK
 * actually receives means its decode path is exercised instead of bypassed — the same reason
 * the streaming fixtures are raw SSE bytes (ADR-008). Decoded, these are
 * [0.01, -0.02, 0.03, 0.04] and [0.05, -0.06, 0.07, 0.08] at float32 precision.
 */
export const OPENAI_EMBEDDING_FIXTURE = {
  object: "list",
  model: "text-embedding-3-small",
  data: [
    { object: "embedding", index: 0, embedding: "CtcjPArXo7yPwvU8CtcjPQ==" },
    { object: "embedding", index: 1, embedding: "zcxMPY/Cdb0pXI89CtejPQ==" },
  ],
  usage: { prompt_tokens: 8, total_tokens: 8 },
};

export const OPENAI_ERROR_FIXTURE = {
  error: {
    message: "Rate limit reached for requests",
    type: "requests",
    param: null,
    code: "rate_limit_exceeded",
  },
};

export const OLLAMA_CHAT_FIXTURE = {
  model: "llama3.2",
  created_at: "2026-01-01T00:00:00.000Z",
  message: { role: "assistant", content: "Fixture completion from a mocked transport." },
  done: true,
  done_reason: "stop",
  prompt_eval_count: 19,
  eval_count: 12,
};

/** NDJSON, one object per line — how Ollama frames a stream. */
export const OLLAMA_STREAM_NDJSON = [
  '{"model":"llama3.2","message":{"role":"assistant","content":"Hello"},"done":false}',
  '{"model":"llama3.2","message":{"role":"assistant","content":" world"},"done":false}',
  '{"model":"llama3.2","message":{"role":"assistant","content":""},"done":true,"done_reason":"stop","prompt_eval_count":5,"eval_count":3}',
].join("\n");

export const OLLAMA_EMBED_FIXTURE = {
  model: "nomic-embed-text",
  embeddings: [
    [0.11, 0.22, 0.33],
    [0.44, 0.55, 0.66],
  ],
  prompt_eval_count: 6,
};
