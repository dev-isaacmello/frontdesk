"use client";

import { type FormEvent, useState, useTransition } from "react";

import { formatCount } from "@/lib/panel/format";
import { clauseExplanation } from "@/lib/panel/labels";
import type { Rules } from "@/lib/panel/types";

import { saveRulesAction, type SaveRulesResult } from "../actions";
import { MAX_RULES } from "../limits";

type SaveError = Extract<SaveRulesResult, { ok: false }>["error"];

const ERRORS: Record<SaveError, string> = {
  too_long: `O texto passou de ${formatCount(MAX_RULES)} caracteres. Encurte e salve de novo.`,
  unconfirmed:
    "Não foi possível confirmar se as regras foram salvas. Recarregue a página antes de tentar de novo.",
};

export function RulesEditor({ initial, initialSavedAt }: { initial: Rules; initialSavedAt: string }) {
  const [saved, setSaved] = useState(initial);
  const [savedAt, setSavedAt] = useState(initialSavedAt);
  const [text, setText] = useState(initial.body);
  const [error, setError] = useState<SaveError>();
  const [justSaved, setJustSaved] = useState(false);
  const [saving, startSaving] = useTransition();

  const changed = text.trim() !== saved.body;
  const tooLong = text.length > MAX_RULES;

  function save(event: FormEvent) {
    event.preventDefault();
    setError(undefined);
    setJustSaved(false);
    startSaving(async () => {
      const result = await saveRulesAction(text);
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setSaved(result.rules);
      setSavedAt(result.savedAt);
      setText(result.rules.body);
      setJustSaved(true);
    });
  }

  return (
    // Phone: what will not work comes under the text. Desktop: beside it, both in view.
    <div className="px-4 pt-2 lg:grid lg:grid-cols-[minmax(0,1fr)_24rem] lg:gap-12 lg:px-8">
      <form onSubmit={save}>
        <label htmlFor="rules" className="block font-medium">
          Suas regras
        </label>
        <textarea
          id="rules"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setJustSaved(false);
          }}
          placeholder="Por exemplo: avise que atrasos de mais de 15 minutos perdem o horário. Crianças só com o Caio."
          className="mt-2 block min-h-44 w-full resize-none rounded-2xl border border-line bg-surface px-4 py-3 leading-relaxed outline-none placeholder:text-ink-soft focus:border-ink-soft lg:min-h-80 [field-sizing:content]"
        />
        <p className={`mt-1.5 text-sm tabular-nums ${tooLong ? "text-danger" : "text-ink-soft"}`}>
          {formatCount(text.length)} de {formatCount(MAX_RULES)} caracteres
        </p>

        {error ? (
          <p role="alert" className="mt-3 text-sm text-danger">
            {ERRORS[error]}
          </p>
        ) : null}
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-5">
          <button
            type="submit"
            disabled={saving || tooLong || !(changed || saved.checked_by_model === false)}
            className="h-12 rounded-full bg-accent px-7 font-medium text-accent-ink transition-opacity disabled:opacity-40"
          >
            {saving ? "Salvando e revisando" : "Salvar regras"}
          </button>
          <p role="status" className="text-sm text-ink-soft">
            {saving
              ? "A revisão automática pode levar alguns segundos."
              : justSaved
                ? "Regras salvas. Já estão valendo."
                : changed
                  ? "Você tem mudanças que ainda não foram salvas."
                  : savedAt
                    ? `Salvas ${savedAt}.`
                    : ""}
          </p>
        </div>
      </form>

      <section aria-labelledby="findings" className="mt-10 lg:mt-0">
        <h2 id="findings" className="font-medium">
          O que não está valendo
        </h2>
        <Findings rules={saved} changed={changed} />
      </section>
    </div>
  );
}

function Findings({ rules, changed }: { rules: Rules; changed: boolean }) {
  const unfinished = rules.checked_by_model === false;
  const stale = changed ? (
    <p className="mt-3 text-sm text-ink-soft">
      Esta lista é da versão salva. Salve para revisar o que você mudou.
    </p>
  ) : null;

  if (rules.body.length === 0) {
    return (
      <>
        <p className="mt-2 text-ink-soft">
          Você ainda não tem regras salvas. O atendente automático segue o cadastro de serviços,
          preços e horários.
        </p>
        {stale}
      </>
    );
  }

  return (
    <>
      {unfinished ? (
        <p className="mt-2 rounded-2xl bg-bubble px-4 py-3 text-[15px]">
          A revisão automática não terminou. Só a conferência básica foi feita, então pode haver
          outros trechos sem efeito que não aparecem aqui. Salve de novo para repetir a revisão.
        </p>
      ) : null}

      {rules.findings.length === 0 ? (
        <p className="mt-2 text-ink-soft">
          {unfinished
            ? "A conferência básica não encontrou trechos sem efeito."
            : "Nenhum trecho sem efeito foi encontrado na versão salva."}
        </p>
      ) : (
        <>
          <p className="mt-2 text-ink-soft">
            {rules.findings.length === 1
              ? "O trecho abaixo foi salvo, mas NÃO está valendo. O atendente automático vai ignorar esse trecho."
              : "Os trechos abaixo foram salvos, mas NÃO estão valendo. O atendente automático vai ignorar cada um deles."}
          </p>
          <ul className="mt-4 space-y-5">
            {rules.findings.map((finding, index) => (
              <li key={`${index}-${finding.clause}`} className="border-l-2 border-attention pl-4">
                <p className="text-sm font-medium text-attention">Não está valendo</p>
                <blockquote className="mt-1 break-words whitespace-pre-wrap">
                  “{finding.excerpt}”
                </blockquote>
                <p className="mt-1.5 text-[15px] text-ink-soft">{clauseExplanation(finding.clause)}</p>
              </li>
            ))}
          </ul>
        </>
      )}
      {stale}
    </>
  );
}
