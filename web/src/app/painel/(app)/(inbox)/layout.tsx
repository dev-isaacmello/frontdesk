import Link from "next/link";
import { type ReactNode, Suspense } from "react";

import { conversationRow } from "@/lib/panel/labels";
import { listApprovals, listConversations } from "@/server/owner-api";

import { ConversationList } from "../../_components/conversation-list";
import { Chevron } from "../../_components/icons";
import { PageHeader } from "../../_components/page-header";
import { Bar, Loading, LoadFailed, Notice } from "../../_components/states";
import { CONVERSATIONS_PAGE } from "../../limits";

export default function InboxLayout({ children }: { children: ReactNode }) {
  return (
    <div className="lg:grid lg:h-full lg:grid-cols-[23rem_minmax(0,1fr)]">
      {/* Desktop: the list stays beside the open conversation. Phone: one or the other. */}
      <section className="pb-20 group-has-[[data-thread]]/shell:max-lg:hidden lg:h-full lg:overflow-y-auto lg:border-r lg:border-line lg:pb-6">
        <PageHeader title="Conversas" className="px-4 lg:px-5" />
        <Suspense fallback={<ListLoading />}>
          <Inbox />
        </Suspense>
      </section>
      <div className="min-w-0 lg:h-full lg:min-h-0">{children}</div>
    </div>
  );
}

async function Inbox() {
  const [list, approvals] = await Promise.all([listConversations(), listApprovals()]);
  if (!list.ok) {
    return <LoadFailed what="as conversas" className="px-4 lg:px-5" />;
  }
  const { conversations } = list.value;
  if (conversations.length === 0) {
    return (
      <Notice title="Nenhuma conversa ainda" className="px-4 lg:px-5">
        Quando um cliente escrever para o seu negócio, a conversa aparece aqui.
      </Notice>
    );
  }

  const now = new Date();
  const waiting = approvals.ok ? approvals.value.length : 0;
  return (
    <>
      {waiting > 0 ? (
        <Link
          href="/painel/aprovacoes"
          className="mx-4 mb-3 flex items-center justify-between gap-4 rounded-2xl bg-accent px-4 py-3.5 text-accent-ink lg:mx-5"
        >
          <span>
            <span className="block font-medium">
              {waiting === 1
                ? "1 pedido espera a sua aprovação"
                : `${waiting} pedidos esperam a sua aprovação`}
            </span>
            <span className="block text-sm opacity-70">Ver e decidir</span>
          </span>
          <Chevron />
        </Link>
      ) : null}
      <ConversationList
        rows={conversations
          .slice(0, CONVERSATIONS_PAGE)
          .map((conversation) => conversationRow(conversation, now))}
        // The ones that need the owner, however far down the list they are.
        attention={conversations
          .filter((conversation) => conversation.mode === "handoff" || conversation.pending_approval)
          .map((conversation) => conversationRow(conversation, now))}
        total={conversations.length}
      />
    </>
  );
}

function ListLoading() {
  return (
    <Loading label="Carregando as conversas">
      <ul>
        {[0, 1, 2, 3, 4, 5].map((row) => (
          <li key={row} className="border-b border-line px-4 py-4 lg:px-5">
            <div className="flex justify-between gap-6">
              <Bar className="h-4 w-36" />
              <Bar className="h-4 w-10" />
            </div>
            <Bar className="mt-2.5 h-4 w-11/12" />
          </li>
        ))}
      </ul>
    </Loading>
  );
}
