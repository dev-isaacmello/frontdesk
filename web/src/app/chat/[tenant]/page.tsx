import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { findTenant, TENANTS } from "@/lib/tenants";

import { Chat } from "./chat";

export function generateStaticParams() {
  return TENANTS.map((tenant) => ({ tenant: tenant.slug }));
}

export async function generateMetadata(props: PageProps<"/chat/[tenant]">): Promise<Metadata> {
  const tenant = findTenant((await props.params).tenant);
  return { title: tenant ? `${tenant.name} · Frontdesk` : "Frontdesk" };
}

export default async function ChatPage(props: PageProps<"/chat/[tenant]">) {
  const tenant = findTenant((await props.params).tenant);
  if (!tenant) {
    notFound();
  }
  return <Chat tenant={tenant} />;
}
