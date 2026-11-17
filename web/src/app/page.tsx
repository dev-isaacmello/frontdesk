import Link from "next/link";

import { TENANTS } from "@/lib/tenants";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-full w-full max-w-xl flex-col justify-center px-6 py-16">
      <h1 className="text-4xl font-semibold tracking-tight">Frontdesk</h1>
      <p className="mt-3 text-lg text-ink-soft">
        Atendimento e agendamento por mensagem. Escolha um negócio e converse como um cliente.
      </p>

      <ul className="mt-10 divide-y divide-line border-y border-line">
        {TENANTS.map((tenant) => (
          <li key={tenant.slug}>
            <Link
              href={`/chat/${tenant.slug}`}
              className="group flex items-center justify-between gap-6 py-5 outline-none"
            >
              <span>
                <span className="block text-lg font-medium group-hover:underline group-focus-visible:underline">
                  {tenant.name}
                </span>
                <span className="mt-1 block text-ink-soft">{tenant.summary}</span>
              </span>
              <svg
                aria-hidden="true"
                viewBox="0 0 20 20"
                className="size-5 shrink-0 text-ink-soft transition-transform group-hover:translate-x-0.5"
              >
                <path
                  d="M7.5 4.5 13 10l-5.5 5.5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </Link>
          </li>
        ))}
      </ul>

      <p className="mt-8 text-sm text-ink-soft">
        Os dois negócios são fictícios. Nada do que você agendar aqui existe de verdade.
      </p>
    </main>
  );
}
