"use client";

import Link from "next/link";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";

import type { Tenant } from "@/lib/tenants";

import { type ChatMessage, useChat } from "./use-chat";

export function Chat({ tenant }: { tenant: Tenant }) {
  const chat = useChat(tenant.slug);
  const empty = chat.messages.length === 0;

  return (
    <div className="mx-auto flex h-dvh w-full max-w-6xl lg:gap-10 lg:px-10 lg:py-10">
      {/* Desktop: the business and what to ask stay beside the conversation. */}
      <aside className="hidden w-72 shrink-0 flex-col lg:flex">
        <Link href="/" className="text-sm text-ink-soft hover:text-ink">
          Frontdesk
        </Link>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight">{tenant.name}</h1>
        <p className="mt-2 text-ink-soft">{tenant.summary}</p>
        <h2 className="mt-10 text-sm font-medium text-ink-soft">Você pode pedir</h2>
        <Suggestions tenant={tenant} onPick={chat.send} layout="list" />
        <p className="mt-auto text-sm text-ink-soft">Negócio fictício, para demonstração.</p>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col bg-surface lg:rounded-3xl lg:border lg:border-line">
        {/* Mobile: a messaging screen, with the business in the top bar. */}
        <header className="flex items-center gap-3 border-b border-line px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))] lg:hidden">
          <Link href="/" aria-label="Voltar" className="-ml-2 rounded-full p-2 text-ink-soft">
            <svg aria-hidden="true" viewBox="0 0 20 20" className="size-5">
              <path
                d="M12.5 4.5 7 10l5.5 5.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </Link>
          <div className="min-w-0">
            <h1 className="truncate font-semibold">{tenant.name}</h1>
            <p className="truncate text-sm text-ink-soft">Atendimento automático</p>
          </div>
        </header>

        <Conversation
          messages={chat.messages}
          waiting={chat.waiting}
          onRetry={chat.retry}
          empty={<Welcome tenant={tenant} onPick={chat.send} />}
        />

        {chat.reconnecting && !empty ? (
          <p role="status" className="px-4 pb-2 text-center text-sm text-ink-soft lg:px-8">
            Sem conexão. Tentando de novo.
          </p>
        ) : null}
        <Composer onSend={chat.send} />
      </section>
    </div>
  );
}

function Welcome({ tenant, onPick }: { tenant: Tenant; onPick: (text: string) => void }) {
  return (
    <div className="flex flex-1 flex-col justify-end px-4 pb-4 lg:items-center lg:justify-center lg:px-8 lg:text-center">
      <p className="text-2xl font-semibold tracking-tight">Olá. Como posso ajudar?</p>
      <p className="mt-2 text-ink-soft lg:max-w-sm">
        Pergunte preços, veja horários livres ou marque um horário na {tenant.name}.
      </p>
      {/* On a phone the suggestions sit right above the keyboard, within thumb reach. */}
      <div className="lg:hidden">
        <Suggestions tenant={tenant} onPick={onPick} layout="chips" />
      </div>
    </div>
  );
}

function Suggestions({
  tenant,
  onPick,
  layout,
}: {
  tenant: Tenant;
  onPick: (text: string) => void;
  layout: "list" | "chips";
}) {
  if (layout === "chips") {
    return (
      <ul className="-mx-4 mt-6 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
        {tenant.suggestions.map((suggestion) => (
          <li key={suggestion} className="shrink-0">
            <button
              type="button"
              onClick={() => onPick(suggestion)}
              className="rounded-full border border-line px-4 py-2 text-sm active:bg-bubble"
            >
              {suggestion}
            </button>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <ul className="mt-3 space-y-1">
      {tenant.suggestions.map((suggestion) => (
        <li key={suggestion}>
          <button
            type="button"
            onClick={() => onPick(suggestion)}
            className="-mx-3 w-[calc(100%+1.5rem)] rounded-xl px-3 py-2 text-left hover:bg-surface"
          >
            {suggestion}
          </button>
        </li>
      ))}
    </ul>
  );
}

function Conversation({
  messages,
  waiting,
  onRetry,
  empty,
}: {
  messages: ChatMessage[];
  waiting: boolean;
  onRetry: (id: string) => void;
  empty: React.ReactNode;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages.length, waiting]);

  if (messages.length === 0) {
    return empty;
  }
  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 lg:px-8" aria-live="polite">
      <ol className="mx-auto flex max-w-2xl flex-col gap-2">
        {messages.map((message) => (
          <Bubble key={message.id} message={message} onRetry={onRetry} />
        ))}
        {waiting ? (
          <li className="flex" aria-label="O atendente está respondendo">
            <span className="flex gap-1 rounded-2xl bg-bubble px-4 py-3.5">
              {[0, 1, 2].map((dot) => (
                <span
                  key={dot}
                  className="typing-dot size-1.5 rounded-full bg-ink-soft"
                  style={{ animationDelay: `${dot * 0.15}s` }}
                />
              ))}
            </span>
          </li>
        ) : null}
      </ol>
      <div ref={end} />
    </div>
  );
}

function Bubble({ message, onRetry }: { message: ChatMessage; onRetry: (id: string) => void }) {
  const mine = message.author === "customer";
  return (
    <li className={`flex flex-col ${mine ? "items-end" : "items-start"}`}>
      <p
        className={`max-w-[85%] whitespace-pre-wrap break-words rounded-2xl px-4 py-2.5 leading-relaxed lg:max-w-[75%] ${
          mine ? "bg-accent text-accent-ink" : "bg-bubble"
        } ${message.delivery === "sending" ? "opacity-60" : ""}`}
      >
        {message.text}
      </p>
      {message.delivery === "failed" ? (
        <p className="mt-1 text-sm text-danger">
          Não foi enviada.{" "}
          <button type="button" className="underline" onClick={() => onRetry(message.id)}>
            Tentar de novo
          </button>
        </p>
      ) : null}
    </li>
  );
}

function Composer({ onSend }: { onSend: (text: string) => void }) {
  const [draft, setDraft] = useState("");
  const ready = draft.trim().length > 0;

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!ready) {
      return;
    }
    onSend(draft.trim());
    setDraft("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      submit(event);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="border-t border-line px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] lg:border-0 lg:px-8 lg:pb-8"
    >
      <div className="mx-auto flex max-w-2xl items-end gap-2 rounded-3xl border border-line bg-surface py-1.5 pr-1.5 pl-4 focus-within:border-ink-soft">
        <label htmlFor="message" className="sr-only">
          Sua mensagem
        </label>
        <textarea
          id="message"
          rows={1}
          value={draft}
          maxLength={2000}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Escreva sua mensagem"
          className="max-h-32 min-h-9 flex-1 resize-none bg-transparent py-1.5 outline-none placeholder:text-ink-soft [field-sizing:content]"
        />
        <button
          type="submit"
          disabled={!ready}
          aria-label="Enviar"
          className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-accent-ink transition-opacity disabled:opacity-25"
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" className="size-5">
            <path
              d="M10 15.5v-11m0 0L5.5 9M10 4.5 14.5 9"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
    </form>
  );
}
