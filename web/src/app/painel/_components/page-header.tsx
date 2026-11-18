import { Suspense } from "react";

import { ownerProfile } from "@/server/owner-session";

import { SignOut } from "./sign-out";

export async function TenantName() {
  return (await ownerProfile())?.tenant ?? "Painel";
}

/**
 * The top of a screen. On a phone it carries the business and the way out, which on a
 * desktop live in the side bar.
 */
export function PageHeader({
  title,
  lead,
  className = "px-4 lg:px-8",
}: {
  title: string;
  lead?: string;
  className?: string;
}) {
  return (
    <header className={`pt-[max(1.25rem,env(safe-area-inset-top))] pb-3 lg:pt-8 lg:pb-4 ${className}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-sm text-ink-soft lg:hidden">
            <Suspense fallback={" "}>
              <TenantName />
            </Suspense>
          </p>
          <h1 className="text-3xl font-semibold tracking-tight lg:text-2xl">{title}</h1>
        </div>
        <SignOut className="-mr-2 px-2 py-1 lg:hidden" />
      </div>
      {lead ? <p className="mt-2 max-w-2xl text-ink-soft">{lead}</p> : null}
    </header>
  );
}
