import { findTenant } from "@/lib/tenants";
import { callApi } from "@/server/api";
import { existingChatSession } from "@/server/session";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Relays the reply stream of the visitor's own conversation. The API checks that the
 * conversation belongs to the session, which comes from the cookie and not from the page.
 */
export async function GET(request: Request, context: RouteContext<"/api/chat/[tenant]/events">) {
  const { tenant: slug } = await context.params;
  const tenant = findTenant(slug);
  const session = await existingChatSession();
  const query = new URL(request.url).searchParams;
  const conversation = query.get("conversation_id") ?? "";
  if (!tenant || !session || !UUID.test(conversation)) {
    return new Response(null, { status: 404 });
  }

  // A reconnecting EventSource says where it stopped in a header.
  const cursor = request.headers.get("Last-Event-ID") ?? query.get("after") ?? "";
  const upstreamQuery = new URLSearchParams({ session_id: session });
  if (UUID.test(cursor)) {
    upstreamQuery.set("after", cursor);
  }
  const upstream = await callApi(
    "GET",
    `/channels/webchat/${tenant.slug}/conversations/${conversation}/events?${upstreamQuery}`,
    { signal: request.signal },
  ).catch(() => undefined);
  if (!upstream?.ok || !upstream.body) {
    return new Response(null, { status: upstream?.status === 404 ? 404 : 502 });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
