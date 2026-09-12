"use client";

import Link from "next/link";
import { AppShell } from "@/components/shell/AppShell";
import { useShellData } from "@/components/shell/ShellData";
import { Icon } from "@/components/ui/Icon";
import { UntrustedText } from "@/components/ui/UntrustedText";
import { Panel, ViewHeading, ViewSubhead } from "@/components/ui/primitives";
import { countdownTo } from "@/lib/time";
import { useTick } from "@/lib/usePoll";

/**
 * Chat inside the shell (`/chat`) — spec §11, mockup 06.
 *
 * §11.1: the chat components themselves are `M1_CHAT_SPEC.md` unchanged
 * (`MessageList`, `Composer`, `WorkIndicator`, `AssistantMessage`,
 * `TraceDisclosure`, `ErrorCard`, all four composer states, the 45s timeout,
 * the cancel semantics) — only the M1 `TopBar` is replaced by this shell.
 * Porting them to the Obsidian & Gold skin is its own commit and is NOT done
 * here; this route currently hosts the **one genuinely new V2 chat state**,
 * the parked turn (§11.2), and says plainly what is still to come.
 */
export default function ChatPage() {
  return (
    <AppShell title="Chat" crumbs={[{ label: "Chat" }]}>
      <ChatView />
    </AppShell>
  );
}

function ChatView() {
  const now = useTick();
  const { pending } = useShellData();
  const parked = pending[0];

  return (
    <div className="max-w-[768px]">
      <ViewHeading>Chat</ViewHeading>
      <ViewSubhead>
        The M1 chat view, re-hosted in the V2 shell. The message list, composer and work indicator
        are the approved M1 components and are ported in a following commit; the parked turn below
        is the new V2 state (C5 <span className="font-mono text-data">outcome=parked</span>).
      </ViewSubhead>

      {parked ? (
        <div className="mt-4 rounded-md border border-warning border-l-[3px] border-l-warning bg-surface p-4">
          <h2 className="m-0 flex items-center gap-2 font-display text-h2 font-bold uppercase tracking-h2 text-text-secondary">
            <Icon name="pause" className="text-warning" />
            This needs your approval before I can continue.
          </h2>
          <div className="mt-2.5">
            <UntrustedText
              label="What I want to run — text supplied by the request, shown exactly as received"
              value={`${parked.tool}.${parked.operation} — ${parked.summary}`}
            />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3.5">
            <span className="text-small text-text-muted">
              {`Expires ${countdownTo(parked.expires_at, now).text}`}
            </span>
            <span className="flex-1" />
            <Link
              href={`/approvals/${parked.id}`}
              className="inline-flex min-h-[40px] items-center rounded-md border border-accent bg-accent bg-sheen-metal px-4 py-2 text-cell font-semibold text-accent-on hover:bg-accent-hover hover:no-underline"
            >
              Review and decide &rarr;
            </Link>
          </div>
          <p className="mt-2.5 text-small text-text-muted">
            The composer stays idle — the turn is over and you may keep chatting (this differs from
            M1&apos;s Busy behaviour, §11.2).
          </p>
        </div>
      ) : (
        <Panel className="mt-4 p-6 text-center">
          <p className="m-0 font-display text-h2 font-bold uppercase tracking-h2 text-text-secondary">
            Ask me to check on something.
          </p>
          <p className="mx-auto mt-2 max-w-[52ch] text-small text-text-muted">
            Nothing is parked for your approval right now, so there is no parked turn to show here.
          </p>
        </Panel>
      )}
    </div>
  );
}
