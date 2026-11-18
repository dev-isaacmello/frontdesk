"use client";

import { useState, useTransition } from "react";

import { returnToAgentAction } from "../actions";

/** Ends the handoff: the agent answers the customer's next message again. */
export function ReturnButton({ conversationId }: { conversationId: string }) {
  const [failed, setFailed] = useState(false);
  const [pending, start] = useTransition();

  function giveBack() {
    setFailed(false);
    start(async () => {
      const result = await returnToAgentAction(conversationId);
      setFailed(!result.ok);
    });
  }

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <button
        type="button"
        onClick={giveBack}
        disabled={pending}
        className="h-10 shrink-0 rounded-full border border-line bg-surface px-4 text-[15px] font-medium transition-opacity disabled:opacity-50"
      >
        {pending ? "Devolvendo" : "Devolver ao atendente automático"}
      </button>
      {failed ? (
        <p role="alert" className="text-sm text-danger">
          Não foi possível devolver a conversa. Tente de novo.
        </p>
      ) : null}
    </div>
  );
}
