import "server-only";

import { sign } from "./signing";

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not set`);
  }
  return value;
}

/** Calls the API as the panel's server. The secret never leaves this process. */
export function callApi(
  method: "GET" | "POST",
  path: string,
  options: { body?: string; signal?: AbortSignal } = {},
): Promise<Response> {
  const body = options.body ?? "";
  return fetch(`${required("FRONTDESK_API_URL")}${path}`, {
    method,
    body: method === "POST" ? body : undefined,
    signal: options.signal,
    cache: "no-store",
    headers: {
      ...sign(required("FRONTDESK_WEBCHAT_SECRET"), new Date(), method, path, body),
      ...(method === "POST" ? { "Content-Type": "application/json" } : {}),
    },
  });
}
