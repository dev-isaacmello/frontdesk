import "server-only";

import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";

const COOKIE = "frontdesk_session";
const ONE_MONTH_SECONDS = 60 * 60 * 24 * 30;

/**
 * The visitor's chat session. It lives in a cookie the page's scripts cannot read, and
 * it is the identity the API knows the visitor by.
 */
export async function chatSession(): Promise<string> {
  const jar = await cookies();
  const existing = jar.get(COOKIE)?.value;
  if (existing) {
    return existing;
  }
  const session = randomUUID();
  jar.set(COOKIE, session, {
    httpOnly: true,
    sameSite: "lax",
    // Off only for plain HTTP on a developer machine, where a secure cookie is dropped.
    secure: process.env.FRONTDESK_INSECURE_COOKIES !== "true",
    path: "/",
    maxAge: ONE_MONTH_SECONDS,
  });
  return session;
}

export async function existingChatSession(): Promise<string | undefined> {
  return (await cookies()).get(COOKIE)?.value;
}
