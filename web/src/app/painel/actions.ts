"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";

import { formatMoment } from "@/lib/panel/format";
import { conversationRow } from "@/lib/panel/labels";
import type { ConversationRow, Rules } from "@/lib/panel/types";
import {
  decideApproval,
  isUuid,
  listConversations,
  returnToAgent,
  saveRules,
  sendOwnerMessage,
  SIGN_IN_PATH,
  signIn,
  signOut,
} from "@/server/owner-api";
import { closeOwnerSession, openOwnerSession, ownerToken } from "@/server/owner-session";

import { CONVERSATIONS_PAGE, MAX_MESSAGE, MAX_RULES } from "./limits";

const MAX_CREDENTIAL = 200;

export type SignInState = { error?: "missing" | "invalid" | "unavailable"; email?: string };

export async function signInAction(_previous: SignInState, form: FormData): Promise<SignInState> {
  const email = String(form.get("email") ?? "").trim();
  const password = String(form.get("password") ?? "");
  if (email.length < 3 || email.length > MAX_CREDENTIAL) {
    return { error: "missing", email: email.slice(0, MAX_CREDENTIAL) };
  }
  if (password.length < 1 || password.length > MAX_CREDENTIAL) {
    return { error: "missing", email };
  }

  const result = await signIn(email, password);
  if (!result.ok) {
    return { error: result.failure === "invalid" ? "invalid" : "unavailable", email };
  }
  const { token, expires_at, owner, tenant } = result.value;
  const expiresAt = new Date(expires_at);
  if (Number.isNaN(expiresAt.getTime())) {
    return { error: "unavailable", email };
  }
  await openOwnerSession(token, expiresAt, { owner: owner.name, tenant: tenant.name });
  redirect("/painel");
}

export async function signOutAction(): Promise<void> {
  const token = await ownerToken();
  if (token) {
    await signOut(token);
  }
  await closeOwnerSession();
  redirect(SIGN_IN_PATH);
}

export type ReplyResult = { ok: true } | { ok: false; error: "empty" | "not_yours" | "failed" };

export async function sendMessageAction(conversationId: string, text: string): Promise<ReplyResult> {
  const message = typeof text === "string" ? text.trim() : "";
  if (typeof conversationId !== "string" || !isUuid(conversationId)) {
    return { ok: false, error: "failed" };
  }
  if (message.length === 0 || message.length > MAX_MESSAGE) {
    return { ok: false, error: "empty" };
  }
  const result = await sendOwnerMessage(conversationId, message);
  if (result.ok) {
    refresh();
    return { ok: true };
  }
  if (result.failure === "conflict") {
    // The conversation went back to the agent in the meantime. The screen has to show it.
    refresh();
    return { ok: false, error: "not_yours" };
  }
  return { ok: false, error: "failed" };
}

export type ReturnResult = { ok: true } | { ok: false };

export async function returnToAgentAction(conversationId: string): Promise<ReturnResult> {
  if (typeof conversationId !== "string" || !isUuid(conversationId)) {
    return { ok: false };
  }
  const result = await returnToAgent(conversationId);
  // A conflict means the agent already has the conversation, which is what was asked.
  if (result.ok || result.failure === "conflict") {
    refresh();
    return { ok: true };
  }
  return { ok: false };
}

export type DecisionResult =
  | { ok: true; outcome: "approved" | "rejected" | "already_decided" }
  | { ok: false };

export async function decideApprovalAction(
  approvalId: string,
  approved: boolean,
): Promise<DecisionResult> {
  if (typeof approvalId !== "string" || !isUuid(approvalId) || typeof approved !== "boolean") {
    return { ok: false };
  }
  const result = await decideApproval(approvalId, approved);
  if (result.ok) {
    console.info("owner_decided_approval", { approved });
    // The queue, the count beside it and the list of conversations all change.
    refresh();
    return { ok: true, outcome: approved ? "approved" : "rejected" };
  }
  if (result.failure === "not_found") {
    // Someone decided it first, or it is gone. The queue on screen is out of date.
    refresh();
    return { ok: true, outcome: "already_decided" };
  }
  return { ok: false };
}

export type SaveRulesResult =
  | { ok: true; rules: Rules; savedAt: string }
  | { ok: false; error: "too_long" | "unconfirmed" };

export async function saveRulesAction(text: string): Promise<SaveRulesResult> {
  // A textarea sends line breaks as CRLF, which would count twice against the limit.
  const body = typeof text === "string" ? text.replace(/\r\n?/g, "\n").trim() : "";
  if (body.length > MAX_RULES) {
    return { ok: false, error: "too_long" };
  }
  const result = await saveRules(body);
  if (!result.ok) {
    return { ok: false, error: result.failure === "invalid" ? "too_long" : "unconfirmed" };
  }
  const rules = result.value;
  return {
    ok: true,
    rules,
    savedAt: rules.saved_at ? formatMoment(rules.saved_at, new Date()) : "",
  };
}

export type OlderConversations = { ok: true; rows: ConversationRow[] } | { ok: false };

/** The next page of the list, counted from how many rows the screen already shows. */
export async function olderConversationsAction(shown: number): Promise<OlderConversations> {
  if (!Number.isSafeInteger(shown) || shown < 0) {
    return { ok: false };
  }
  const result = await listConversations();
  if (!result.ok) {
    return { ok: false };
  }
  const now = new Date();
  return {
    ok: true,
    rows: result.value.conversations
      .slice(shown, shown + CONVERSATIONS_PAGE)
      .map((conversation) => conversationRow(conversation, now)),
  };
}
