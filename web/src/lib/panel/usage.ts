import { formatCost } from "./format";
import type { DayUsage, Usage } from "./types";

const dayFormat = new Intl.DateTimeFormat("pt-BR", {
  weekday: "short",
  day: "2-digit",
  month: "2-digit",
  timeZone: "UTC",
});

/** "ter., 17/11" for a calendar day that arrives as 2026-11-17. */
export function formatUsageDay(day: string): string {
  const at = new Date(`${day}T12:00:00Z`);
  return Number.isNaN(at.getTime()) ? day : dayFormat.format(at);
}

/** What the business is told about where it stands against its monthly limit. */
export function budgetStatus(usage: Usage): { title: string; detail: string; warn: boolean } {
  const spent = formatCost(usage.spent_this_month_microusd);
  if (usage.monthly_budget_microusd === null) {
    return { title: `${spent} neste mês`, detail: "Não há limite mensal definido.", warn: false };
  }
  const limit = formatCost(usage.monthly_budget_microusd);
  const title = `${spent} de ${limit} neste mês`;
  if (usage.level === "exhausted") {
    return {
      title,
      detail:
        "O limite do mês foi ultrapassado. O atendente automático parou e as conversas estão indo para a equipe.",
      warn: true,
    };
  }
  if (usage.level === "economy") {
    return {
      title,
      detail:
        "O limite do mês foi atingido. O atendente automático passou a usar um modelo mais barato.",
      warn: true,
    };
  }
  return { title, detail: "Dentro do limite do mês.", warn: false };
}

/** How many of the answers of a period the agent gave by itself, as "9 de 10". */
export function answeredAlone(days: DayUsage[]): { alone: number; total: number } {
  const alone = days.reduce((sum, day) => sum + day.replied + day.refused, 0);
  const total = alone + days.reduce((sum, day) => sum + day.handed_off, 0);
  return { alone, total };
}

export function totalCost(days: DayUsage[]): number {
  return days.reduce((sum, day) => sum + day.cost_microusd, 0);
}

/** What a conversation of the period cost on average, as a sentence, or nothing to say. */
export function averageCost(usage: Usage): string {
  if (usage.conversations === 0) {
    return "Nenhuma conversa no período.";
  }
  const each = formatCost(Math.round(totalCost(usage.days) / usage.conversations));
  return `${each} por conversa, em média.`;
}

/** The cost of one conversation on a day, or nothing when there was none. */
export function costPerConversation(day: DayUsage): string {
  return day.conversations > 0 ? formatCost(Math.round(day.cost_microusd / day.conversations)) : "";
}
