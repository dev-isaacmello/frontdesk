"use client";

import Link from "next/link";
import { useState, useTransition } from "react";

import { type DecisionResult, decideApprovalAction } from "../actions";
import { Notice } from "./states";

/** A waiting request, already worded for the screen by the server. */
export type ApprovalRequest = {
  id: string;
  conversationId: string;
  summary: string;
  detail: string;
};

type Outcome = Extract<DecisionResult, { ok: true }>["outcome"];

const DONE: Record<Outcome, string> = {
  approved: "Pedido aprovado. O atendente automático retoma a conversa com o cliente.",
  rejected: "Pedido recusado. O atendente automático retoma a conversa com o cliente.",
  already_decided: "Esse pedido já tinha sido resolvido. Nada mudou.",
};

/** The requests that wait for the owner, and what happened to the last one decided. */
export function ApprovalQueue({ requests }: { requests: ApprovalRequest[] }) {
  const [done, setDone] = useState<Outcome>();

  return (
    <>
      {done ? (
        <p role="status" className="mx-4 mb-2 rounded-2xl bg-bubble px-4 py-3 lg:mx-8">
          {DONE[done]}
        </p>
      ) : null}
      {requests.length === 0 ? (
        <Notice title="Nenhum pedido esperando por você">
          Quando um cliente pedir algo que depende da sua aprovação, o pedido aparece aqui.
        </Notice>
      ) : (
        <ul className="mt-2 border-t border-line">
          {requests.map((request) => (
            <Request key={request.id} request={request} onDone={setDone} />
          ))}
        </ul>
      )}
    </>
  );
}

function Request({
  request,
  onDone,
}: {
  request: ApprovalRequest;
  onDone: (outcome: Outcome) => void;
}) {
  const [choice, setChoice] = useState<boolean>();
  const [failed, setFailed] = useState(false);
  const [pending, start] = useTransition();

  function decide(approved: boolean) {
    setChoice(approved);
    setFailed(false);
    start(async () => {
      const result = await decideApprovalAction(request.id, approved);
      if (result.ok) {
        onDone(result.outcome);
      } else {
        setFailed(true);
      }
    });
  }

  return (
    // Phone: the two answers span the screen under the request. Desktop: beside it.
    <li className="border-b border-line px-4 py-6 lg:flex lg:items-center lg:justify-between lg:gap-10 lg:px-8">
      <div className="min-w-0">
        <h2 className="text-xl font-semibold tracking-tight">{request.summary}</h2>
        <p className="mt-1.5 text-ink-soft">{request.detail}</p>
        <Link
          href={`/painel/conversas/${request.conversationId}`}
          className="mt-2 inline-block font-medium underline underline-offset-4"
        >
          Ver a conversa
        </Link>
      </div>
      <div className="mt-5 lg:mt-0 lg:shrink-0">
        <div className="grid grid-cols-2 gap-2 lg:flex">
          <button
            type="button"
            disabled={pending}
            onClick={() => decide(false)}
            className="h-12 rounded-full border border-line px-6 font-medium transition-opacity disabled:opacity-50 lg:h-11"
          >
            {pending && choice === false ? "Recusando" : "Recusar"}
          </button>
          <button
            type="button"
            disabled={pending}
            onClick={() => decide(true)}
            className="h-12 rounded-full bg-accent px-6 font-medium text-accent-ink transition-opacity disabled:opacity-50 lg:h-11"
          >
            {pending && choice === true ? "Aprovando" : "Aprovar"}
          </button>
        </div>
        {failed ? (
          <p role="alert" className="mt-2 text-sm text-danger lg:text-right">
            Sua decisão não foi registrada. Tente de novo.
          </p>
        ) : null}
      </div>
    </li>
  );
}
