import { describe, expect, it } from "vitest";

import type { DayUsage, Usage } from "./types";
import {
  answeredAlone,
  averageCost,
  budgetStatus,
  costPerConversation,
  formatUsageDay,
  totalCost,
} from "./usage";

function day(overrides: Partial<DayUsage>): DayUsage {
  return {
    day: "2026-11-17",
    conversations: 0,
    replied: 0,
    refused: 0,
    handed_off: 0,
    blocked_drafts: 0,
    model_calls: 0,
    cost_microusd: 0,
    ...overrides,
  };
}

function usage(overrides: Partial<Usage>): Usage {
  return {
    plan: "basic",
    monthly_budget_microusd: 5_000_000,
    spent_this_month_microusd: 420_000,
    level: "normal",
    conversations: 0,
    days: [],
    ...overrides,
  };
}

describe("the owner's view of usage", () => {
  it("writes a calendar day without shifting it by a time zone", () => {
    expect(formatUsageDay("2026-11-17")).toBe("ter., 17/11");
    expect(formatUsageDay("not-a-day")).toBe("not-a-day");
  });

  it("says where the business stands against its monthly limit", () => {
    expect(budgetStatus(usage({}))).toEqual({
      title: "US$ 0,42 de US$ 5,00 neste mês",
      detail: "Dentro do limite do mês.",
      warn: false,
    });
    expect(budgetStatus(usage({ level: "economy" })).warn).toBe(true);
    expect(budgetStatus(usage({ level: "exhausted" })).detail).toContain("parou");
    expect(budgetStatus(usage({ monthly_budget_microusd: null })).detail).toBe(
      "Não há limite mensal definido.",
    );
  });

  it("counts what the agent answered by itself against what went to a person", () => {
    const days = [day({ replied: 7, refused: 2, handed_off: 1 }), day({ replied: 3 })];

    expect(answeredAlone(days)).toEqual({ alone: 12, total: 13 });
  });

  it("adds up the cost of a period and divides a day by its conversations", () => {
    const days = [
      day({ cost_microusd: 3000, conversations: 2 }),
      day({ cost_microusd: 1200, conversations: 0 }),
    ];

    expect(totalCost(days)).toBe(4200);
    expect(averageCost(usage({ conversations: 3, days }))).toBe("US$ 0,0014 por conversa, em média.");
    expect(averageCost(usage({ days }))).toBe("Nenhuma conversa no período.");
    expect(costPerConversation(days[0])).toBe("US$ 0,0015");
    expect(costPerConversation(days[1])).toBe("");
  });
});
