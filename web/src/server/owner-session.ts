import "server-only";

import { cookies } from "next/headers";

const TOKEN_COOKIE = "frontdesk_owner";
const PROFILE_COOKIE = "frontdesk_owner_profile";
// The panel is the only place that needs the session, so the browser sends it nowhere else.
const COOKIE_PATH = "/painel";

export type OwnerProfile = { owner: string; tenant: string };

function cookieOptions(expiresAt: Date) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    // Off only for plain HTTP on a developer machine, where a secure cookie is dropped.
    secure: process.env.FRONTDESK_INSECURE_COOKIES !== "true",
    path: COOKIE_PATH,
    expires: expiresAt,
  };
}

/** Keeps the owner signed in. Only a Server Action or a Route Handler may call this. */
export async function openOwnerSession(
  token: string,
  expiresAt: Date,
  profile: OwnerProfile,
): Promise<void> {
  const jar = await cookies();
  jar.set(TOKEN_COOKIE, token, cookieOptions(expiresAt));
  // Names for the screen only. Nothing is decided from this cookie.
  jar.set(PROFILE_COOKIE, JSON.stringify(profile), cookieOptions(expiresAt));
}

/** Forgets the session. Only a Server Action or a Route Handler may call this. */
export async function closeOwnerSession(): Promise<void> {
  const jar = await cookies();
  jar.delete({ name: TOKEN_COOKIE, path: COOKIE_PATH });
  jar.delete({ name: PROFILE_COOKIE, path: COOKIE_PATH });
}

export async function ownerToken(): Promise<string | undefined> {
  return (await cookies()).get(TOKEN_COOKIE)?.value || undefined;
}

export async function ownerProfile(): Promise<OwnerProfile | undefined> {
  const raw = (await cookies()).get(PROFILE_COOKIE)?.value;
  if (!raw) {
    return undefined;
  }
  try {
    const { owner, tenant } = JSON.parse(raw) as Record<string, unknown>;
    return typeof owner === "string" && typeof tenant === "string" ? { owner, tenant } : undefined;
  } catch {
    return undefined;
  }
}
