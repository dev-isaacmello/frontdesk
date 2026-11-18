import { describe, expect, it } from "vitest";

import {
  beforeAndAfter,
  categoryLabel,
  latestPerModel,
  meanPassed,
  passedPerRun,
  ratio,
  type Comparison,
  type ComparisonEntry,
} from "./models";

function entry(overrides: Partial<ComparisonEntry>): ComparisonEntry {
  return {
    model: "small",
    prompt_version: "p1",
    runs: 3,
    last_run_at: "2026-11-18T01:00:00+00:00",
    cases: 32,
    passed_per_run: [28, 29, 27],
    passed_mean: 28,
    cost_per_conversation_microusd: 1217,
    model_ms_per_turn_p50: 7219,
    blocked_drafts_mean: 1,
    by_category: {},
    always_failing: [],
    unstable: [],
    ...overrides,
  };
}

const comparison: Comparison = {
  golden_version: "v1",
  excluded: [],
  entries: [
    entry({}),
    entry({
      prompt_version: "p2",
      last_run_at: "2026-11-18T03:00:00+00:00",
      passed_per_run: [31, 32, 30],
      passed_mean: 31,
      cost_per_conversation_microusd: 1322,
    }),
    entry({
      model: "open",
      prompt_version: "p2",
      last_run_at: "2026-11-18T03:10:00+00:00",
      passed_per_run: [31, 31, 31],
      passed_mean: 31,
      cost_per_conversation_microusd: 613,
    }),
    entry({ model: "open", prompt_version: "p1", runs: 1, passed_per_run: [31], passed_mean: 31 }),
  ],
};

describe("the comparison of models", () => {
  it("shows each model once, with its newest instructions, the best first", () => {
    const shown = latestPerModel(comparison);

    // The same score, so the cheaper one comes first.
    expect(shown.map((each) => [each.model, each.prompt_version])).toEqual([
      ["open", "p2"],
      ["small", "p2"],
    ]);
  });

  it("pairs a model with itself before a change of instructions", () => {
    const pair = beforeAndAfter(comparison, "small");

    expect([pair?.before.passed_mean, pair?.after.passed_mean]).toEqual([28, 31]);
  });

  it("does not pair measurements with a different number of rounds", () => {
    expect(beforeAndAfter(comparison, "open")).toBeUndefined();
  });

  it("writes the rounds and the mean the way a person reads them", () => {
    const small = latestPerModel(comparison)[1];

    expect(passedPerRun(small)).toBe("31, 32 e 30 de 32");
    expect(meanPassed(small)).toBe("31,0");
  });

  it("compares a value with a reference in plain words", () => {
    expect(ratio(613, 1322)).toBe("2,2 vezes menos");
    expect(ratio(1322, 613)).toBe("2,2 vezes mais");
    expect(ratio(0, 613)).toBe("");
  });

  it("names a kind of test in words an owner knows", () => {
    expect(categoryLabel("injection")).toBe("Tentativas de enganar o atendente");
    expect(categoryLabel("something-new")).toBe("Outros testes");
  });
});
