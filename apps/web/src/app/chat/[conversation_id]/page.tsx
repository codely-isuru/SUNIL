"use client";

import { useParams } from "next/navigation";
import { AppShell } from "@/components/shell/AppShell";
import { Panel, ViewHeading, ViewSubhead } from "@/components/ui/primitives";

/**
 * A single conversation (`/chat/{conversation_id}`) — the M1 message list
 * re-hosted (§11.1). The route exists so every link that points at it from
 * the approval card and the audit browser resolves; the message components
 * are ported in the chat commit.
 */
export default function ConversationPage() {
  const params = useParams<{ conversation_id: string }>();
  const id = params?.conversation_id ?? "";

  return (
    <AppShell title="Conversation" crumbs={[{ label: "Chat", href: "/chat" }, { label: id, mono: true }]}>
      <div className="max-w-[768px]">
        <ViewHeading>Conversation</ViewHeading>
        <ViewSubhead>
          <span className="font-mono text-data">{id}</span>
        </ViewSubhead>
        <Panel className="mt-4 p-5 text-cell text-text-muted">
          This route hosts the M1 message list, composer and trace disclosure unchanged (§11.1).
          They are ported to the shell in the chat commit; the link path from an approval to its
          conversation is wired now so nothing in the ops views dead-ends.
        </Panel>
      </div>
    </AppShell>
  );
}
