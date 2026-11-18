import "server-only";

import { sign } from "./signing";

export const OWNER_SESSION_HEADER = "X-Frontdesk-Owner-Session";

type Method = "GET" | "POST" | "PUT" | "DELETE";

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not set`);
  }
  return value;
}

/** Calls the API as the panel's server. The secret never leaves this process. */
export function callApi(
  method: Method,
  path: string,
  options: { body?: string; signal?: AbortSignal; ownerSession?: string } = {},
): Promise<Response> {
  const sendsBody = method === "POST" || method === "PUT";
  // The signature covers the body that is actually sent, which is none for GET and DELETE.
  const body = sendsBody ? (options.body ?? "") : "";
  return fetch(`${required("FRONTDESK_API_URL")}${path}`, {
    method,
    body: sendsBody ? body : undefined,
    signal: options.signal,
    cache: "no-store",
    headers: {
      ...sign(required("FRONTDESK_WEBCHAT_SECRET"), new Date(), method, path, body),
      ...(sendsBody ? { "Content-Type": "application/json" } : {}),
      ...(options.ownerSession ? { [OWNER_SESSION_HEADER]: options.ownerSession } : {}),
    },
  });
}
