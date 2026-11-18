import type { Metadata } from "next";
import Link from "next/link";
import { type ReactNode, Suspense } from "react";

import { listApprovals } from "@/server/owner-api";

import { AutoRefresh } from "../_components/auto-refresh";
import { NavItems } from "../_components/nav-items";
import { TenantName } from "../_components/page-header";
import { PanelNav } from "../_components/panel-nav";
import { SignOut } from "../_components/sign-out";
import { Bar } from "../_components/states";

export const metadata: Metadata = { title: "Painel · Frontdesk" };

async function Nav({ variant }: { variant: "side" | "tabs" }) {
  const approvals = await listApprovals();
  return <PanelNav variant={variant} waiting={approvals.ok ? approvals.value.length : 0} />;
}

export default function PanelLayout({ children }: { children: ReactNode }) {
  return (
    <div className="group/shell min-h-dvh bg-surface lg:grid lg:h-dvh lg:grid-cols-[15rem_minmax(0,1fr)] lg:bg-canvas">
      {/* Desktop: the business, the three places and the way out stay on the side. */}
      <aside className="hidden flex-col px-6 py-8 lg:flex">
        <Link href="/" className="text-sm text-ink-soft hover:text-ink">
          Frontdesk
        </Link>
        <p className="mt-1 text-lg font-semibold tracking-tight">
          <Suspense fallback={<Bar className="mt-2 h-5 w-36" />}>
            <TenantName />
          </Suspense>
        </p>
        <nav aria-label="Painel" className="mt-8">
          <Suspense fallback={<NavItems variant="side" />}>
            <Nav variant="side" />
          </Suspense>
        </nav>
        <div className="mt-auto">
          <SignOut className="py-1" />
        </div>
      </aside>

      <div className="min-w-0 lg:h-dvh lg:overflow-hidden lg:border-l lg:border-line lg:bg-surface">
        {children}
      </div>

      {/* Phone: tabs at the thumb. An open conversation takes the whole screen instead. */}
      <nav
        aria-label="Painel"
        className="fixed inset-x-0 bottom-0 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] group-has-[[data-thread]]/shell:hidden lg:hidden"
      >
        <div className="-mt-px">
          <Suspense fallback={<NavItems variant="tabs" />}>
            <Nav variant="tabs" />
          </Suspense>
        </div>
      </nav>
      <AutoRefresh />
    </div>
  );
}
