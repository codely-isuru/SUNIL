"use client";

import type { ReactNode } from "react";

/**
 * A small, dependency-free markdown-to-React renderer for exactly the
 * subset M1_CHAT_SPEC.md §5.2 asks for: bold, lists, inline code, fenced
 * code blocks. No library in `ARCHITECTURE_V1.md` §14.3 covers markdown —
 * rather than add one (an Architect escalation per the build plan's rule
 * 0.2.3), this renders directly to React elements and never touches
 * `dangerouslySetInnerHTML`, so raw HTML in a message can never execute
 * (THREAT_MODEL.md T-02) — React escapes text nodes by construction.
 */

interface CodeBlock {
  type: "code";
  lang?: string;
  code: string;
}
interface ListBlock {
  type: "ul" | "ol";
  items: string[];
}
interface ParagraphBlock {
  type: "p";
  text: string;
}
type Block = CodeBlock | ListBlock | ParagraphBlock;

const UL_MARKER = /^\s*[-*]\s+/;
const OL_MARKER = /^\s*\d+\.\s+/;
const FENCE = /^```(\w*)\s*$/;

function parseBlocks(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") {
      i++;
      continue;
    }

    const fenceMatch = line.match(FENCE);
    if (fenceMatch) {
      const lang = fenceMatch[1] || undefined;
      i++;
      const codeLines: string[] = [];
      while (i < lines.length && !/^```\s*$/.test(lines[i])) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip the closing fence
      blocks.push({ type: "code", lang, code: codeLines.join("\n") });
      continue;
    }

    if (UL_MARKER.test(line) || OL_MARKER.test(line)) {
      const marker = UL_MARKER.test(line) ? UL_MARKER : OL_MARKER;
      const listType = marker === UL_MARKER ? "ul" : "ol";
      const items: string[] = [];
      while (i < lines.length && marker.test(lines[i])) {
        items.push(lines[i].replace(marker, ""));
        i++;
      }
      blocks.push({ type: listType, items });
      continue;
    }

    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !FENCE.test(lines[i]) &&
      !UL_MARKER.test(lines[i]) &&
      !OL_MARKER.test(lines[i])
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    blocks.push({ type: "p", text: paraLines.join("\n") });
  }

  return blocks;
}

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`)/g;

function parseInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let idx = 0;
  let match: RegExpExecArray | null;
  INLINE.lastIndex = 0;

  while ((match = INLINE.exec(text))) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(
        <strong key={`${keyPrefix}-b-${idx}`} className="font-semibold">
          {token.slice(2, -2)}
        </strong>,
      );
    } else {
      nodes.push(
        <code
          key={`${keyPrefix}-c-${idx}`}
          className="rounded bg-surface-raised px-1 py-0.5 font-mono-body text-code text-text-secondary"
        >
          {token.slice(1, -1)}
        </code>,
      );
    }
    idx++;
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function renderParagraphLines(text: string, keyPrefix: string): ReactNode {
  const lines = text.split("\n");
  return lines.map((line, i) => (
    <span key={`${keyPrefix}-line-${i}`}>
      {parseInline(line, `${keyPrefix}-${i}`)}
      {i < lines.length - 1 && <br />}
    </span>
  ));
}

export interface MarkdownBodyProps {
  content: string;
}

/** Renders assistant markdown (M1_CHAT_SPEC.md §5.2): bold, lists, inline code, fenced code blocks. */
export function MarkdownBody({ content }: MarkdownBodyProps) {
  const blocks = parseBlocks(content);

  return (
    <div className="space-y-3">
      {blocks.map((block, i) => {
        const key = `block-${i}`;
        switch (block.type) {
          case "code":
            return (
              <pre
                key={key}
                className="overflow-x-auto rounded-md border border-border bg-surface-raised p-3"
              >
                <code className="font-mono-body text-code text-text-primary">{block.code}</code>
              </pre>
            );
          case "ul":
            return (
              <ul key={key} className="list-disc space-y-1 pl-5 font-mono-body text-body text-text-primary">
                {block.items.map((item, j) => (
                  <li key={`${key}-${j}`}>{parseInline(item, `${key}-${j}`)}</li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={key} className="list-decimal space-y-1 pl-5 font-mono-body text-body text-text-primary">
                {block.items.map((item, j) => (
                  <li key={`${key}-${j}`}>{parseInline(item, `${key}-${j}`)}</li>
                ))}
              </ol>
            );
          case "p":
          default:
            return (
              <p key={key} className="font-mono-body text-body text-text-primary">
                {renderParagraphLines(block.text, key)}
              </p>
            );
        }
      })}
    </div>
  );
}
