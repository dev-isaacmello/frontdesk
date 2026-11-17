import { findTenant } from "@/lib/tenants";
import { callApi } from "@/server/api";
import { chatSession } from "@/server/session";

const MAX_TEXT = 2000;
const MAX_ID = 64;

type Outgoing = { message_id: string; text: string };

function parse(payload: unknown): Outgoing | undefined {
  if (typeof payload !== "object" || payload === null) {
    return undefined;
  }
  const { message_id, text } = payload as Record<string, unknown>;
  if (typeof message_id !== "string" || message_id.length === 0 || message_id.length > MAX_ID) {
    return undefined;
  }
  if (typeof text !== "string" || text.trim().length === 0 || text.length > MAX_TEXT) {
    return undefined;
  }
  return { message_id, text: text.trim() };
}

export async function POST(request: Request, context: RouteContext<"/api/chat/[tenant]/messages">) {
  const { tenant: slug } = await context.params;
  // The slug goes into the path of an upstream request, so only known tenants pass.
  const tenant = findTenant(slug);
  if (!tenant) {
    return Response.json({ error: "unknown_tenant" }, { status: 404 });
  }
  const message = parse(await request.json().catch(() => undefined));
  if (!message) {
    return Response.json({ error: "invalid_message" }, { status: 422 });
  }

  const session = await chatSession();
  const upstream = await callApi("POST", `/channels/webchat/${tenant.slug}/messages`, {
    body: JSON.stringify({ session_id: session, ...message }),
  }).catch(() => undefined);
  if (!upstream?.ok) {
    return Response.json({ error: "unavailable" }, { status: 502 });
  }
  const { conversation_id } = (await upstream.json()) as { conversation_id: string };
  return Response.json({ conversation_id }, { status: 202 });
}
