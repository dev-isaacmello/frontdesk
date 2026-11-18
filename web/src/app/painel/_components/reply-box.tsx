"use client";

import { type FormEvent, type KeyboardEvent, useState, useTransition } from "react";

import { type ReplyResult, sendMessageAction } from "../actions";
import { MAX_MESSAGE } from "../limits";

type ReplyError = Extract<ReplyResult, { ok: false }>["error"];

const ERRORS: Record<ReplyError, string> = {
  empty: "Escreva uma mensagem antes de enviar.",
  not_yours:
    "Esta conversa voltou para o atendente automático, então sua mensagem não foi enviada.",
  failed: "Sua mensagem não foi enviada. Tente de novo.",
};

/** Where the owner answers the customer while a person is in charge of the conversation. */
export function ReplyBox({ conversationId }: { conversationId: string }) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<ReplyError>();
  const [sending, startSending] = useTransition();
  const ready = draft.trim().length > 0 && !sending;

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!ready) {
      return;
    }
    const text = draft.trim();
    setError(undefined);
    startSending(async () => {
      const result = await sendMessageAction(conversationId, text);
      if (result.ok) {
        setDraft("");
      } else {
        // The draft stays, so nothing the owner wrote is lost.
        setError(result.error);
      }
    });
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      submit(event);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="border-t border-line px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] lg:border-0 lg:px-8 lg:pb-6"
    >
      {error ? (
        <p role="alert" className="mx-auto mb-2 max-w-2xl px-1 text-sm text-danger">
          {ERRORS[error]}
        </p>
      ) : null}
      <div className="mx-auto flex max-w-2xl items-end gap-2 rounded-3xl border border-line bg-surface py-1.5 pr-1.5 pl-4 focus-within:border-ink-soft">
        <label htmlFor="reply" className="sr-only">
          Sua resposta ao cliente
        </label>
        <textarea
          id="reply"
          rows={1}
          value={draft}
          maxLength={MAX_MESSAGE}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Responda ao cliente"
          className="max-h-32 min-h-9 flex-1 resize-none bg-transparent py-1.5 outline-none placeholder:text-ink-soft [field-sizing:content]"
        />
        <button
          type="submit"
          disabled={!ready}
          aria-label={sending ? "Enviando" : "Enviar"}
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
