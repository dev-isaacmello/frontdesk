import "server-only";

import { redirect } from "next/navigation";
import { cache } from "react";

import type {
  Approval,
  Usage,
  ConversationDetail,
  ConversationList,
  Rules,
} from "@/lib/panel/types";

import { callApi } from "./api";
import { closeOwnerSession, ownerToken } from "./owner-session";

export const SIGN_IN_PATH = "/painel/entrar";
/** Where a request goes when the API no longer knows its session. It clears the cookie. */
export const SESSION_ENDED_PATH = "/painel/sessao-encerrada";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DEFAULT_TIMEOUT_MS = 10_000;
// Saving the rules waits for the automatic review, which the API itself limits to 20 seconds.
const SAVE_RULES_TIMEOUT_MS = 40_000;

export type Failure = "unavailable" | "not_found" | "conflict" | "invalid";
export type Result<T> = { ok: true; value: T } | { ok: false; failure: Failure };

export type SignedIn = {
  token: string;
  expires_at: string;
  owner: { name: string };
  tenant: { slug: string; name: string };
};

type Method = "GET" | "POST" | "PUT" | "DELETE";

const unavailable = { ok: false, failure: "unavailable" } as const;

export function isUuid(value: string): boolean {
  return UUID.test(value);
}

async function send(
  method: Method,
  path: string,
  options: { body?: unknown; ownerSession?: string; timeoutMs?: number },
): Promise<Response | undefined> {
  try {
    return await callApi(method, path, {
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      ownerSession: options.ownerSession,
      signal: AbortSignal.timeout(options.timeoutMs ?? DEFAULT_TIMEOUT_MS),
    });
  } catch (error) {
    console.error("owner_api_unreachable", {
      method,
      path,
      error: error instanceof Error ? error.name : "unknown",
    });
    return undefined;
  }
}

async function detailOf(response: Response): Promise<unknown> {
  const payload = (await response.json().catch(() => undefined)) as { detail?: unknown } | undefined;
  return payload?.detail;
}

function failureOf(method: Method, path: string, response: Response): Failure {
  if (response.status === 404) {
    return "not_found";
  }
  if (response.status === 409) {
    return "conflict";
  }
  if (response.status === 422) {
    return "invalid";
  }
  console.error("owner_api_failed", { method, path, status: response.status });
  return "unavailable";
}

/**
 * Calls the API as the signed-in owner. An owner without a session, or with one the API
 * no longer knows, leaves through a redirect, so callers only see the other answers.
 */
async function asOwner(
  method: Method,
  path: string,
  options: { body?: unknown; timeoutMs?: number } = {},
): Promise<Response | undefined> {
  const token = await ownerToken();
  if (!token) {
    redirect(SIGN_IN_PATH);
  }
  const response = await send(method, path, { ...options, ownerSession: token });
  if (response?.status === 401) {
    // A signature the API rejects is a fault of this server, not an ended session.
    if ((await detailOf(response)) === "invalid signature") {
      console.error("owner_api_rejected_signature", { method, path });
      return undefined;
    }
    return endSession();
  }
  return response;
}

/**
 * The API no longer knows the session: forget it and ask the owner to sign in again.
 * A Server Action can drop the cookie right here. A page that is rendering cannot, and
 * `cookies().delete` throws there, so the page goes through the handler that can.
 */
async function endSession(): Promise<never> {
  let forgotten = false;
  try {
    await closeOwnerSession();
    forgotten = true;
  } catch {
    // Rendering: the handler at SESSION_ENDED_PATH clears the cookie instead.
  }
  redirect(forgotten ? `${SIGN_IN_PATH}?motivo=sessao` : SESSION_ENDED_PATH);
}

async function read<T>(path: string): Promise<Result<T>> {
  const response = await asOwner("GET", path);
  if (!response) {
    return unavailable;
  }
  if (!response.ok) {
    return { ok: false, failure: failureOf("GET", path, response) };
  }
  const value = (await response.json().catch(() => undefined)) as T | undefined;
  return value === undefined ? unavailable : { ok: true, value };
}

async function write(
  method: Method,
  path: string,
  options: { body?: unknown; timeoutMs?: number } = {},
): Promise<Result<Response>> {
  const response = await asOwner(method, path, options);
  if (!response) {
    return unavailable;
  }
  return response.ok
    ? { ok: true, value: response }
    : { ok: false, failure: failureOf(method, path, response) };
}

/** "invalid" here means the e-mail and the password do not match an owner. */
export async function signIn(email: string, password: string): Promise<Result<SignedIn>> {
  const path = "/owner/sessions";
  const response = await send("POST", path, { body: { email, password } });
  if (!response) {
    return unavailable;
  }
  if (response.status === 401 && (await detailOf(response)) === "invalid credentials") {
    return { ok: false, failure: "invalid" };
  }
  if (!response.ok) {
    console.error("owner_api_failed", { method: "POST", path, status: response.status });
    return unavailable;
  }
  const value = (await response.json().catch(() => undefined)) as SignedIn | undefined;
  return value?.token ? { ok: true, value } : unavailable;
}

/** Ends the session in the API. The caller forgets the cookie whatever the answer is. */
export async function signOut(token: string): Promise<void> {
  await send("DELETE", "/owner/sessions", { ownerSession: token });
}

/** Whether the API still knows this session. Undefined when the API did not answer. */
export async function sessionIsKnown(token: string): Promise<boolean | undefined> {
  const response = await send("GET", "/owner/rules", { ownerSession: token });
  if (response?.ok) {
    return true;
  }
  if (response?.status === 401 && (await detailOf(response)) !== "invalid signature") {
    return false;
  }
  return undefined;
}

// One render asks for the same list from a layout and from a page: `cache` makes it one call.
export const listConversations = cache(() => read<ConversationList>("/owner/conversations"));

export const listApprovals = cache(async (): Promise<Result<Approval[]>> => {
  const result = await read<{ approvals: Approval[] }>("/owner/approvals");
  return result.ok ? { ok: true, value: result.value.approvals } : result;
});

export async function getConversation(id: string): Promise<Result<ConversationDetail>> {
  // The id goes into the path of an upstream request, so only a UUID passes.
  if (!isUuid(id)) {
    return { ok: false, failure: "not_found" };
  }
  return read<ConversationDetail>(`/owner/conversations/${id}`);
}

export async function sendOwnerMessage(id: string, text: string): Promise<Result<null>> {
  if (!isUuid(id)) {
    return { ok: false, failure: "not_found" };
  }
  const result = await write("POST", `/owner/conversations/${id}/messages`, { body: { text } });
  return result.ok ? { ok: true, value: null } : result;
}

export async function returnToAgent(id: string): Promise<Result<null>> {
  if (!isUuid(id)) {
    return { ok: false, failure: "not_found" };
  }
  const result = await write("POST", `/owner/conversations/${id}/return`);
  return result.ok ? { ok: true, value: null } : result;
}

export async function decideApproval(id: string, approved: boolean): Promise<Result<null>> {
  if (!isUuid(id)) {
    return { ok: false, failure: "not_found" };
  }
  const result = await write("POST", `/owner/approvals/${id}/decision`, { body: { approved } });
  return result.ok ? { ok: true, value: null } : result;
}

export function getUsage(): Promise<Result<Usage>> {
  return read<Usage>("/owner/usage");
}

export function getRules(): Promise<Result<Rules>> {
  return read<Rules>("/owner/rules");
}

export async function saveRules(body: string): Promise<Result<Rules>> {
  const result = await write("PUT", "/owner/rules", {
    body: { body },
    timeoutMs: SAVE_RULES_TIMEOUT_MS,
  });
  if (!result.ok) {
    return result;
  }
  const value = (await result.value.json().catch(() => undefined)) as Rules | undefined;
  return value === undefined ? unavailable : { ok: true, value };
}
