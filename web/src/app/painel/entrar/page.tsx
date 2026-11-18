import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { SignInForm } from "./sign-in-form";

export const metadata: Metadata = { title: "Entrar · Painel Frontdesk" };

const REASONS: Record<string, string> = {
  sessao: "Sua sessão terminou. Entre de novo para continuar.",
  indisponivel: "Não foi possível confirmar sua sessão agora. Tente entrar de novo.",
};

export default function SignInPage(props: PageProps<"/painel/entrar">) {
  return (
    // Phone: the form starts near the top, clear of the keyboard. Desktop: centered.
    <main className="mx-auto flex min-h-full w-full max-w-sm flex-col px-6 pt-[max(3.5rem,env(safe-area-inset-top))] pb-10 lg:justify-center lg:pt-10">
      <Link href="/" className="text-sm text-ink-soft hover:text-ink">
        Frontdesk
      </Link>
      <h1 className="mt-6 text-3xl font-semibold tracking-tight">Painel do negócio</h1>
      <p className="mt-2 text-ink-soft">
        Acompanhe as conversas, responda seus clientes e decida os pedidos que dependem de você.
      </p>
      <Suspense>
        <Reason searchParams={props.searchParams} />
      </Suspense>
      <SignInForm />
    </main>
  );
}

async function Reason({ searchParams }: Pick<PageProps<"/painel/entrar">, "searchParams">) {
  const { motivo } = await searchParams;
  const text = typeof motivo === "string" ? REASONS[motivo] : undefined;
  if (!text) {
    return null;
  }
  return (
    <p role="status" className="mt-6 rounded-2xl bg-bubble px-4 py-3 text-sm">
      {text}
    </p>
  );
}
