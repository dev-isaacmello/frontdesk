import Link from "next/link";
import { Suspense } from "react";

import { formatClock, formatDayHeading } from "@/lib/panel/format";
import { authorLabel, customerName, outcomeLabel } from "@/lib/panel/labels";
import { buildThread } from "@/lib/panel/thread";
import type { ConversationDetail, Message, Turn } from "@/lib/panel/types";
import { getConversation } from "@/server/owner-api";

import { Chevron } from "../../../../_components/icons";
import { ReplyBox } from "../../../../_components/reply-box";
import { ReturnButton } from "../../../../_components/return-button";
import { ScrollToEnd } from "../../../../_components/scroll-to-end";
import { Bar, Loading, LoadFailed, Notice } from "../../../../_components/states";
import { TurnTimeline } from "../../../../_components/turn-timeline";

type Props = PageProps<"/painel/conversas/[id]">;

export default function ConversationPage({ params }: Props) {
  return (
    // The marker tells the shell that a conversation is open: on a phone it takes the
    // whole screen, without the list and without the tabs.
    <div data-thread className="flex h-dvh flex-col bg-surface lg:h-full">
      <Suspense fallback={<ConversationLoading />}>
        <Conversation params={params} />
      </Suspense>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/painel"
      aria-label="Voltar para as conversas"
      className="-ml-2 rounded-full p-2 text-ink-soft lg:hidden"
    >
      <Chevron direction="left" />
    </Link>
  );
}

async function Conversation({ params }: Pick<Props, "params">) {
  const { id } = await params;
  const result = await getConversation(id);
  if (!result.ok) {
    return (
      <>
        <header className="flex items-center border-b border-line px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))] lg:hidden">
          <BackLink />
        </header>
        {result.failure === "not_found" ? (
          <Notice
            title="Conversa não encontrada"
            action={
              <Link href="/painel" className="font-medium underline">
                Ver todas as conversas
              </Link>
            }
          >
            Ela não existe ou não é do seu negócio.
          </Notice>
        ) : (
          <LoadFailed what="a conversa" />
        )}
      </>
    );
  }

  const conversation = result.value;
  const handoff = conversation.mode === "handoff";
  const waitsForOwner = conversation.turns.some((turn) => turn.status === "awaiting_approval");

  return (
    <>
      <header className="border-b border-line">
        <div className="flex items-center gap-2 px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))] lg:gap-6 lg:px-8 lg:py-5">
          <BackLink />
          <div className="min-w-0 flex-1">
            <h1 className="truncate font-semibold lg:text-xl">
              {customerName(conversation.customer_name)}
            </h1>
            <p className="truncate text-sm text-ink-soft">
              {handoff
                ? "Em atendimento humano. Quem responde é você."
                : "O atendente automático está respondendo."}
            </p>
          </div>
          {handoff ? (
            <div className="hidden lg:block">
              <ReturnButton conversationId={conversation.id} />
            </div>
          ) : null}
        </div>
        {/* Phone: the way back to the agent gets its own row, away from the keyboard. */}
        {handoff ? (
          <div className="border-t border-line bg-canvas px-4 py-2.5 lg:hidden">
            <ReturnButton conversationId={conversation.id} />
          </div>
        ) : null}
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4 lg:px-8">
        <Thread conversation={conversation} />
        {waitsForOwner ? (
          <Link
            href="/painel/aprovacoes"
            className="mx-auto mt-5 flex max-w-2xl items-center justify-between gap-4 rounded-2xl bg-accent px-4 py-3.5 text-accent-ink"
          >
            <span>
              <span className="block font-medium">Este cliente espera a sua aprovação</span>
              <span className="block text-sm opacity-70">Ver o pedido e decidir</span>
            </span>
            <Chevron />
          </Link>
        ) : null}
        <ScrollToEnd count={conversation.messages.length} />
      </div>

      {handoff ? (
        <ReplyBox conversationId={conversation.id} />
      ) : (
        <p className="border-t border-line px-4 pt-3.5 pb-[max(0.875rem,env(safe-area-inset-bottom))] text-center text-sm text-ink-soft lg:px-8">
          Você pode responder aqui quando a conversa for passada para a equipe.
        </p>
      )}
    </>
  );
}

function Thread({ conversation }: { conversation: ConversationDetail }) {
  const thread = buildThread(conversation.messages, conversation.turns);
  if (thread.length === 0) {
    return <p className="py-10 text-center text-ink-soft">Esta conversa ainda não tem mensagens.</p>;
  }
  const now = new Date();
  return (
    <ol className="mx-auto flex max-w-2xl flex-col gap-3">
      {thread.map((item) => {
        if (item.kind === "day") {
          return (
            <li key={`day-${item.key}`} className="py-2 text-center text-sm font-medium text-ink-soft">
              {formatDayHeading(item.at, now)}
            </li>
          );
        }
        if (item.kind === "turn") {
          return <QuietTurn key={`turn-${item.turn.id}`} turn={item.turn} />;
        }
        return <Bubble key={item.message.id} message={item.message} turn={item.turn} />;
      })}
    </ol>
  );
}

const BUBBLES: Record<Message["author"], string> = {
  customer: "bg-bubble",
  agent: "border border-line bg-surface",
  owner: "bg-accent text-accent-ink",
};

function Bubble({ message, turn }: { message: Message; turn?: Turn }) {
  const ours = message.author !== "customer";
  return (
    <li className={`flex flex-col ${ours ? "items-end" : "items-start"}`}>
      <p
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 leading-relaxed break-words whitespace-pre-wrap lg:max-w-[75%] ${BUBBLES[message.author]}`}
      >
        {message.text}
      </p>
      <p className="mt-1 px-1 text-[13px] text-ink-soft">
        {authorLabel(message.author)}, <time dateTime={message.at}>{formatClock(message.at)}</time>
      </p>
      {turn ? <TurnTimeline turn={turn} /> : null}
    </li>
  );
}

/** A turn of the agent that sent nothing to the customer, such as one that failed. */
function QuietTurn({ turn }: { turn: Turn }) {
  return (
    <li className="flex flex-col items-end">
      <p className="max-w-[85%] rounded-2xl border border-dashed border-line px-4 py-2.5 text-ink-soft lg:max-w-[75%]">
        {outcomeLabel(turn.outcome)}
      </p>
      <p className="mt-1 px-1 text-[13px] text-ink-soft">
        {authorLabel("agent")},{" "}
        <time dateTime={turn.started_at}>{formatClock(turn.started_at)}</time>
      </p>
      <TurnTimeline turn={turn} />
    </li>
  );
}

function ConversationLoading() {
  return (
    <Loading label="Carregando a conversa">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))] lg:px-8 lg:py-5">
        <BackLink />
        <div>
          <Bar className="h-4 w-40" />
          <Bar className="mt-2 h-3.5 w-56" />
        </div>
      </div>
      <div className="mx-auto flex max-w-2xl flex-col gap-4 px-4 py-6 lg:px-8">
        <Bar className="h-11 w-3/5 rounded-2xl" />
        <Bar className="h-16 w-2/3 self-end rounded-2xl" />
        <Bar className="h-11 w-1/2 rounded-2xl" />
        <Bar className="h-11 w-3/5 self-end rounded-2xl" />
      </div>
    </Loading>
  );
}
