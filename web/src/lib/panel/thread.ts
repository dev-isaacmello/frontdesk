/** Puts the messages of a conversation and the turns of the agent on one line of time. */

import { dayKey } from "./format";
import type { Message, Turn } from "./types";

export type ThreadItem =
  | { kind: "day"; key: string; at: string }
  | { kind: "message"; message: Message; turn?: Turn }
  /** A turn that sent nothing, such as one that failed. */
  | { kind: "turn"; turn: Turn };

function time(iso: string | null): number {
  const value = iso ? Date.parse(iso) : Number.NaN;
  return Number.isNaN(value) ? 0 : value;
}

/**
 * Messages do not say which turn wrote them. A turn gets the first reply of the agent
 * written after the turn started and before the next turn did, so a turn that failed
 * without a reply does not take the reply of the turn after it.
 */
export function repliesByTurn(messages: readonly Message[], turns: readonly Turn[]) {
  const ordered = [...turns].sort((one, other) => time(one.started_at) - time(other.started_at));
  const replies = messages
    .filter((message) => message.author === "agent")
    .sort((one, other) => time(one.at) - time(other.at));
  const taken = new Set<string>();
  const turnOfMessage = new Map<string, Turn>();
  const withoutReply: Turn[] = [];

  ordered.forEach((turn, index) => {
    const from = time(turn.started_at);
    const next = ordered[index + 1];
    const until = next ? time(next.started_at) : Number.POSITIVE_INFINITY;
    const reply = replies.find(
      (message) => !taken.has(message.id) && time(message.at) >= from && time(message.at) < until,
    );
    if (reply) {
      taken.add(reply.id);
      turnOfMessage.set(reply.id, turn);
    } else {
      withoutReply.push(turn);
    }
  });
  return { turnOfMessage, withoutReply };
}

/** The conversation as the screen shows it: day headings, messages and turns, oldest first. */
export function buildThread(messages: readonly Message[], turns: readonly Turn[]): ThreadItem[] {
  const { turnOfMessage, withoutReply } = repliesByTurn(messages, turns);

  const entries: { at: string; item: ThreadItem }[] = messages.map((message) => ({
    at: message.at,
    item: { kind: "message", message, turn: turnOfMessage.get(message.id) },
  }));
  for (const turn of withoutReply) {
    // While a person answers, every message of the customer opens a turn that stays
    // quiet. Showing each of them would bury the conversation.
    if (turn.outcome !== "silent") {
      entries.push({ at: turn.finished_at ?? turn.started_at, item: { kind: "turn", turn } });
    }
  }
  entries.sort((one, other) => time(one.at) - time(other.at));

  const thread: ThreadItem[] = [];
  let day = "";
  for (const entry of entries) {
    const key = dayKey(new Date(time(entry.at)));
    if (key !== day) {
      day = key;
      thread.push({ kind: "day", key, at: entry.at });
    }
    thread.push(entry.item);
  }
  return thread;
}

/** How long a turn took: from its start to its end, or what its steps add up to so far. */
export function turnDurationMs(turn: Pick<Turn, "started_at" | "finished_at" | "steps">): number {
  if (turn.finished_at) {
    return Math.max(0, time(turn.finished_at) - time(turn.started_at));
  }
  return turn.steps.reduce((total, step) => total + Math.max(0, step.duration_ms), 0);
}
