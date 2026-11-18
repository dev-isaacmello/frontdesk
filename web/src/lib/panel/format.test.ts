import { describe, expect, it } from "vitest";

import {
  formatClock,
  formatCost,
  formatCount,
  formatDayAndTime,
  formatDayHeading,
  formatDuration,
  formatListTime,
  formatMoment,
} from "./format";

// 22:30 of Tuesday 17/11/2026 in São Paulo, which is already Wednesday in UTC.
const NOW = new Date("2026-11-18T01:30:00Z");

describe("formatCost", () => {
  it("shows two digits of a cost that is a fraction of a cent", () => {
    expect(formatCost(1249)).toBe("US$ 0,0012");
    expect(formatCost(1941)).toBe("US$ 0,0019");
    expect(formatCost(175)).toBe("US$ 0,00018");
    expect(formatCost(1)).toBe("US$ 0,000001");
  });

  it("uses cents from one dollar up and for nothing at all", () => {
    expect(formatCost(0)).toBe("US$ 0,00");
    expect(formatCost(1_500_000)).toBe("US$ 1,50");
    expect(formatCost(1_234_560_000)).toBe("US$ 1.234,56");
    expect(formatCost(999_999)).toBe("US$ 1,00");
  });

  it("treats a value that is not a cost as zero", () => {
    expect(formatCost(Number.NaN)).toBe("US$ 0,00");
    expect(formatCost(-5)).toBe("US$ 0,00");
  });
});

describe("formatDuration", () => {
  it("picks the unit a person would", () => {
    expect(formatDuration(0)).toBe("menos de 1 ms");
    expect(formatDuration(3)).toBe("3 ms");
    expect(formatDuration(2320)).toBe("2,3 s");
    expect(formatDuration(10_916)).toBe("11 s");
    expect(formatDuration(65_000)).toBe("1 min 05 s");
  });
});

describe("times in São Paulo", () => {
  it("shows the clock of São Paulo, not of UTC", () => {
    expect(formatClock("2026-11-18T17:00:00Z")).toBe("14:00");
    expect(formatClock("not a date")).toBe("");
  });

  it("writes the day of a booking as people say it", () => {
    expect(formatDayAndTime("2026-11-19T17:00:00Z")).toBe("quinta 19/11 às 14:00");
    expect(formatDayAndTime("2026-11-21T12:30:00Z")).toBe("sábado 21/11 às 09:30");
  });

  it("uses the day in São Paulo to tell today from yesterday", () => {
    // 22:09 of the 17th in São Paulo, the same local day as NOW.
    expect(formatListTime("2026-11-18T01:09:14Z", NOW)).toBe("22:09");
    expect(formatListTime("2026-11-17T02:00:00Z", NOW)).toBe("ontem");
    expect(formatListTime("2026-11-14T15:00:00Z", NOW)).toBe("sábado");
    expect(formatListTime("2026-10-02T15:00:00Z", NOW)).toBe("02/10");
    expect(formatListTime("2025-10-02T15:00:00Z", NOW)).toBe("02/10/2025");
  });

  it("writes a moment as part of a sentence", () => {
    expect(formatMoment("2026-11-18T01:09:14Z", NOW)).toBe("hoje às 22:09");
    expect(formatMoment("2026-11-17T02:00:00Z", NOW)).toBe("ontem às 23:00");
    expect(formatMoment("2026-11-18T17:00:00Z", NOW)).toBe("amanhã às 14:00");
    expect(formatMoment("2026-11-12T17:00:00Z", NOW)).toBe("quinta 12/11 às 14:00");
  });

  it("names the days of a conversation", () => {
    expect(formatDayHeading("2026-11-18T01:09:14Z", NOW)).toBe("Hoje");
    expect(formatDayHeading("2026-11-17T02:00:00Z", NOW)).toBe("Ontem");
    expect(formatDayHeading("2026-11-10T15:00:00Z", NOW)).toBe("terça, 10 de novembro");
    expect(formatDayHeading("2025-11-10T15:00:00Z", NOW)).toBe("segunda, 10 de novembro de 2025");
  });
});

describe("formatCount", () => {
  it("groups thousands the Brazilian way", () => {
    expect(formatCount(1548)).toBe("1.548");
  });
});
