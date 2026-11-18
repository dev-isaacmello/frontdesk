import Link from "next/link";
import { Suspense } from "react";

import { formatCost, formatCount } from "@/lib/panel/format";
import type { DayUsage, Usage } from "@/lib/panel/types";
import {
  answeredAlone,
  averageCost,
  budgetStatus,
  costPerConversation,
  formatUsageDay,
} from "@/lib/panel/usage";
import { getUsage } from "@/server/owner-api";

import { PageHeader } from "../../_components/page-header";
import { Bar, Loading, LoadFailed, Notice } from "../../_components/states";

export default function UsagePage() {
  return (
    <div className="pb-24 lg:h-full lg:overflow-y-auto lg:pb-10">
      <div className="max-w-5xl">
        <PageHeader
          title="Uso e custos"
          lead="O que o atendente automático fez nos últimos 30 dias e quanto custou a IA por trás dele."
        />
        <Suspense fallback={<UsageLoading />}>
          <UsageView />
        </Suspense>
      </div>
    </div>
  );
}

async function UsageView() {
  const result = await getUsage();
  if (!result.ok) {
    return <LoadFailed what="o uso" />;
  }
  const usage = result.value;
  return (
    <>
      <Summary usage={usage} />
      {usage.days.length === 0 ? (
        <Notice title="Nenhuma conversa nos últimos 30 dias.">
          Quando um cliente escrever, o dia aparece aqui com as respostas e o custo.
        </Notice>
      ) : (
        <>
          <DaysOnPhone days={usage.days} />
          <DaysOnDesktop days={usage.days} />
        </>
      )}
      <p className="px-4 pt-8 lg:px-8">
        <Link href="/painel/modelos" className="underline underline-offset-4">
          Ver a comparação entre os modelos de IA
        </Link>
      </p>
    </>
  );
}

function Summary({ usage }: { usage: Usage }) {
  const budget = budgetStatus(usage);
  const { alone, total } = answeredAlone(usage.days);
  return (
    <dl className="mt-2 grid gap-px border-y border-line bg-line sm:grid-cols-3">
      <div className="bg-canvas px-4 py-5 lg:px-8">
        <dt className="text-sm text-ink-soft">Custo da IA</dt>
        <dd className="mt-1 text-xl font-semibold tracking-tight">{budget.title}</dd>
        <dd className={`mt-1 text-sm ${budget.warn ? "text-attention" : "text-ink-soft"}`}>
          {budget.detail} Plano {usage.plan === "pro" ? "Pro" : "Básico"}.
        </dd>
      </div>
      <div className="bg-canvas px-4 py-5 lg:px-8">
        <dt className="text-sm text-ink-soft">Respostas sem ajuda da equipe</dt>
        <dd className="mt-1 text-xl font-semibold tracking-tight">
          {total === 0 ? "Nenhuma ainda" : `${formatCount(alone)} de ${formatCount(total)}`}
        </dd>
        <dd className="mt-1 text-sm text-ink-soft">
          {total === 0
            ? "Aparece aqui quando um cliente escrever."
            : "As outras foram passadas para a equipe."}
        </dd>
      </div>
      <div className="bg-canvas px-4 py-5 lg:px-8">
        <dt className="text-sm text-ink-soft">Conversas em 30 dias</dt>
        <dd className="mt-1 text-xl font-semibold tracking-tight">
          {formatCount(usage.conversations)}
        </dd>
        <dd className="mt-1 text-sm text-ink-soft">{averageCost(usage)}</dd>
      </div>
    </dl>
  );
}

/** One block per day, the newest first, to be read with a thumb. */
function DaysOnPhone({ days }: { days: DayUsage[] }) {
  return (
    <ul className="divide-y divide-line border-b border-line lg:hidden">
      {days.map((day) => (
        <li key={day.day} className="px-4 py-5">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="font-semibold capitalize">{formatUsageDay(day.day)}</h2>
            <p className="font-medium">{formatCost(day.cost_microusd)}</p>
          </div>
          <p className="mt-1 text-ink-soft">
            {conversations(day.conversations)}. {answers(day)}
          </p>
          {day.blocked_drafts > 0 ? (
            <p className="mt-1 text-sm text-ink-soft">{blocked(day.blocked_drafts)}</p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** The days as lines of a table, one column per thing counted. */
function DaysOnDesktop({ days }: { days: DayUsage[] }) {
  return (
    <div className="hidden px-8 lg:block">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-line text-sm text-ink-soft">
            <th className="py-3 font-normal">Dia</th>
            <th className="py-3 pl-6 font-normal">Conversas</th>
            <th className="py-3 pl-6 font-normal">Respostas</th>
            <th className="py-3 pl-6 font-normal">Fora do assunto</th>
            <th className="py-3 pl-6 font-normal">Para a equipe</th>
            <th className="py-3 pl-6 font-normal">Respostas refeitas</th>
            <th className="py-3 pl-6 font-normal">Custo</th>
            <th className="py-3 pl-6 font-normal">Por conversa</th>
          </tr>
        </thead>
        <tbody>
          {days.map((day) => (
            <tr key={day.day} className="border-b border-line">
              <th scope="row" className="py-3 font-medium capitalize">
                {formatUsageDay(day.day)}
              </th>
              <td className="py-3 pl-6">{formatCount(day.conversations)}</td>
              <td className="py-3 pl-6">{formatCount(day.replied)}</td>
              <td className="py-3 pl-6">{formatCount(day.refused)}</td>
              <td className="py-3 pl-6">{formatCount(day.handed_off)}</td>
              <td className="py-3 pl-6">{formatCount(day.blocked_drafts)}</td>
              <td className="py-3 pl-6">{formatCost(day.cost_microusd)}</td>
              <td className="py-3 pl-6 text-ink-soft">{costPerConversation(day)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function conversations(count: number): string {
  return count === 1 ? "1 conversa" : `${formatCount(count)} conversas`;
}

function answers(day: DayUsage): string {
  const parts = [day.replied === 1 ? "1 resposta" : `${formatCount(day.replied)} respostas`];
  if (day.refused > 0) {
    parts.push(`${formatCount(day.refused)} fora do assunto`);
  }
  if (day.handed_off > 0) {
    parts.push(`${formatCount(day.handed_off)} para a equipe`);
  }
  return `${parts.join(", ")}.`;
}

function blocked(count: number): string {
  return count === 1
    ? "1 resposta foi refeita antes de ser enviada."
    : `${formatCount(count)} respostas foram refeitas antes de serem enviadas.`;
}

function UsageLoading() {
  return (
    <Loading label="Carregando o uso">
      <div className="mt-2 border-y border-line px-4 py-6 lg:px-8">
        <Bar className="h-6 w-3/5 lg:w-1/3" />
        <Bar className="mt-3 h-4 w-4/5 lg:w-1/2" />
        <Bar className="mt-8 h-4 w-full" />
        <Bar className="mt-3 h-4 w-11/12" />
      </div>
    </Loading>
  );
}
