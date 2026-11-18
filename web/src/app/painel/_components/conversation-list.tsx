"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

import { formatCount } from "@/lib/panel/format";
import type { ConversationRow } from "@/lib/panel/types";

import { olderConversationsAction } from "../actions";

type Filter = "all" | "attention";

export function ConversationList({
  rows,
  attention,
  total,
}: {
  /** The newest conversations, as the server last read them. */
  rows: ConversationRow[];
  /** Every conversation a person answers or that waits for an approval. */
  attention: ConversationRow[];
  total: number;
}) {
  const open = useParams<{ id?: string }>().id;
  const [filter, setFilter] = useState<Filter>("all");
  const [older, setOlder] = useState<ConversationRow[]>([]);
  const [failed, setFailed] = useState(false);
  const [loading, startLoading] = useTransition();

  // A fresh read of the newest rows wins over what was loaded before it.
  const all = useMemo(() => {
    const fresh = new Set(rows.map((row) => row.id));
    return [...rows, ...older.filter((row) => !fresh.has(row.id))];
  }, [rows, older]);
  const shown = filter === "all" ? all : attention;

  function loadOlder() {
    setFailed(false);
    startLoading(async () => {
      const result = await olderConversationsAction(all.length);
      if (!result.ok) {
        setFailed(true);
        return;
      }
      setOlder((current) => {
        const known = new Set(current.map((row) => row.id));
        return [...current, ...result.rows.filter((row) => !known.has(row.id))];
      });
    });
  }

  return (
    <>
      {attention.length > 0 || filter === "attention" ? (
        <div className="flex gap-1 px-3 pb-2 lg:px-4">
          <FilterButton current={filter === "all"} onClick={() => setFilter("all")}>
            Todas
          </FilterButton>
          <FilterButton current={filter === "attention"} onClick={() => setFilter("attention")}>
            Precisam de você
            <span className="ml-1.5 text-ink-soft">{attention.length}</span>
          </FilterButton>
        </div>
      ) : null}

      {shown.length === 0 ? (
        <p className="px-4 py-10 text-ink-soft lg:px-5">Nenhuma conversa precisa de você agora.</p>
      ) : (
        <ul className="border-t border-line">
          {shown.map((row) => (
            <li key={row.id}>
              <Row row={row} current={row.id === open} />
            </li>
          ))}
        </ul>
      )}

      {filter === "all" && all.length < total ? (
        <div className="px-4 py-6 lg:px-5">
          <p className="text-sm text-ink-soft">
            Mostrando as {formatCount(all.length)} conversas mais recentes de {formatCount(total)}.
          </p>
          {failed ? (
            <p role="alert" className="mt-2 text-sm text-danger">
              Não foi possível carregar mais conversas.
            </p>
          ) : null}
          <button
            type="button"
            onClick={loadOlder}
            disabled={loading}
            className="mt-3 h-11 rounded-full border border-line px-5 font-medium transition-opacity disabled:opacity-50"
          >
            {loading ? "Carregando" : failed ? "Tentar de novo" : "Mostrar mais antigas"}
          </button>
        </div>
      ) : null}
    </>
  );
}

function FilterButton({
  current,
  onClick,
  children,
}: {
  current: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={current}
      onClick={onClick}
      className={`h-9 rounded-full px-3.5 text-[15px] ${
        current ? "bg-bubble font-medium" : "text-ink-soft hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

function Row({ row, current }: { row: ConversationRow; current: boolean }) {
  return (
    <Link
      href={`/painel/conversas/${row.id}`}
      // A hundred rows would each ask the server for the same shell.
      prefetch={false}
      aria-current={current ? "page" : undefined}
      className={`block border-b border-line px-4 py-3.5 lg:px-5 lg:py-3 ${
        current ? "lg:bg-bubble" : "hover:bg-canvas active:bg-bubble"
      }`}
    >
      <span className="flex items-baseline justify-between gap-3">
        <span className={`truncate ${row.named ? "font-semibold" : "font-medium"}`}>{row.name}</span>
        <span className="shrink-0 text-sm text-ink-soft">{row.when}</span>
      </span>
      <span className="mt-0.5 line-clamp-2 text-[15px] leading-snug text-ink-soft lg:line-clamp-1">
        {row.preview}
      </span>
      {row.handoff || row.pendingApproval ? (
        <span className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm font-medium">
          {row.handoff ? <Mark className="text-ink">Em atendimento humano</Mark> : null}
          {row.pendingApproval ? (
            <Mark className="text-attention">Espera a sua aprovação</Mark>
          ) : null}
        </span>
      ) : null}
    </Link>
  );
}

function Mark({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
      {children}
    </span>
  );
}
