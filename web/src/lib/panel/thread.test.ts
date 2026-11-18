import { describe, expect, it } from "vitest";

import { buildThread, turnDurationMs } from "./thread";
import type { Message, Turn } from "./types";

function message(id: string, author: Message["author"], at: string): Message {
  return { id, author, text: id, at };
}

function turn(id: string, started_at: string, finished_at: string | null, outcome = "replied"): Turn {
  return {
    id,
    status: finished_at ? "completed" : "awaiting_approval",
    outcome,
    started_at,
    finished_at,
    blocked_drafts: 0,
    model_calls: 1,
    cost_microusd: 100,
    steps: [],
  };
}

function shape(messages: Message[], turns: Turn[]): string[] {
  return buildThread(messages, turns).map((item) => {
    if (item.kind === "day") {
      return `day:${item.key}`;
    }
    if (item.kind === "turn") {
      return `turn:${item.turn.id}`;
    }
    return `${item.message.id}${item.turn ? `<${item.turn.id}` : ""}`;
  });
}

describe("buildThread", () => {
  it("gives each turn the reply written after it started", () => {
    const messages = [
      message("m1", "customer", "2026-11-18T01:08:29Z"),
      message("m2", "agent", "2026-11-18T01:08:38Z"),
      message("m3", "customer", "2026-11-18T01:08:38.2Z"),
      message("m4", "agent", "2026-11-18T01:08:39.7Z"),
    ];
    const turns = [
      turn("t1", "2026-11-18T01:08:30Z", "2026-11-18T01:08:38Z"),
      turn("t2", "2026-11-18T01:08:39.6Z", "2026-11-18T01:08:39.7Z", "handoff"),
    ];

    expect(shape(messages, turns)).toEqual(["day:2026-11-17", "m1", "m2<t1", "m3", "m4<t2"]);
  });

  it("does not hand a failed turn the reply of the turn after it", () => {
    const messages = [
      message("m1", "customer", "2026-11-18T12:00:00Z"),
      message("m2", "customer", "2026-11-18T12:01:00Z"),
      message("m3", "agent", "2026-11-18T12:01:10Z"),
    ];
    const turns = [
      turn("failed", "2026-11-18T12:00:01Z", "2026-11-18T12:00:05Z", "failed"),
      turn("ok", "2026-11-18T12:01:01Z", "2026-11-18T12:01:10Z"),
    ];

    expect(shape(messages, turns)).toEqual(["day:2026-11-18", "m1", "turn:failed", "m2", "m3<ok"]);
  });

  it("leaves out the quiet turns of a conversation a person is answering", () => {
    const messages = [message("m1", "customer", "2026-11-18T12:00:00Z")];
    const turns = [turn("quiet", "2026-11-18T12:00:01Z", "2026-11-18T12:00:01Z", "silent")];

    expect(shape(messages, turns)).toEqual(["day:2026-11-18", "m1"]);
  });

  it("keeps a turn that still waits for the owner with its reply", () => {
    const messages = [
      message("m1", "customer", "2026-11-18T12:00:00Z"),
      message("m2", "agent", "2026-11-18T12:00:08Z"),
      message("m3", "owner", "2026-11-18T12:05:00Z"),
    ];
    const turns = [turn("waiting", "2026-11-18T12:00:01Z", null, "awaiting_approval")];

    expect(shape(messages, turns)).toEqual(["day:2026-11-18", "m1", "m2<waiting", "m3"]);
  });

  it("opens a new day by the calendar of São Paulo", () => {
    const messages = [
      message("m1", "customer", "2026-11-18T02:59:00Z"),
      message("m2", "customer", "2026-11-18T03:01:00Z"),
    ];

    expect(shape(messages, [])).toEqual(["day:2026-11-17", "m1", "day:2026-11-18", "m2"]);
  });

  it("is empty for a conversation without messages", () => {
    expect(buildThread([], [])).toEqual([]);
  });
});

describe("turnDurationMs", () => {
  it("measures a finished turn from start to end", () => {
    expect(
      turnDurationMs({
        started_at: "2026-11-18T01:08:55.421Z",
        finished_at: "2026-11-18T01:09:06.337Z",
        steps: [],
      }),
    ).toBe(10_916);
  });

  it("adds up the steps of a turn that has not finished", () => {
    const steps = [
      { seq: 0, node: "load_context", duration_ms: 3, detail: {} },
      { seq: 1, node: "classify", duration_ms: 1477, detail: {} },
    ];
    expect(turnDurationMs({ started_at: "2026-11-18T01:09:07Z", finished_at: null, steps })).toBe(
      1480,
    );
  });
});
