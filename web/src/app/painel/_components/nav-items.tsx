import Link from "next/link";

const ITEMS = [
  { href: "/painel", label: "Conversas", short: "Conversas" },
  { href: "/painel/aprovacoes", label: "Aprovações", short: "Aprovações" },
  { href: "/painel/regras", label: "Regras da casa", short: "Regras" },
  { href: "/painel/uso", label: "Uso e custos", short: "Uso" },
] as const;

function isCurrent(href: string, pathname: string | undefined): boolean {
  if (!pathname) {
    return false;
  }
  if (href === "/painel") {
    return pathname === "/painel" || pathname.startsWith("/painel/conversas");
  }
  // The comparison of models is reached from the usage screen and belongs to it.
  if (href === "/painel/uso" && pathname.startsWith("/painel/modelos")) {
    return true;
  }
  return pathname.startsWith(href);
}

function Count({ value }: { value: number }) {
  if (value <= 0) {
    return null;
  }
  return (
    <span className="grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1.5 text-xs font-semibold text-accent-ink">
      {value}
      <span className="sr-only"> esperando você</span>
    </span>
  );
}

/** The four places of the panel: a list on the side of a desktop, tabs at the foot of a phone. */
export function NavItems({
  variant,
  pathname,
  waiting = 0,
}: {
  variant: "side" | "tabs";
  pathname?: string;
  waiting?: number;
}) {
  if (variant === "tabs") {
    return (
      <ul className="grid grid-cols-4">
        {ITEMS.map((item) => {
          const current = isCurrent(item.href, pathname);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={current ? "page" : undefined}
                className={`flex h-14 items-center justify-center gap-1 border-t-2 text-sm ${
                  current ? "border-ink font-semibold" : "border-transparent text-ink-soft"
                }`}
              >
                {item.short}
                {item.href === "/painel/aprovacoes" ? <Count value={waiting} /> : null}
              </Link>
            </li>
          );
        })}
      </ul>
    );
  }
  return (
    <ul className="space-y-1">
      {ITEMS.map((item) => {
        const current = isCurrent(item.href, pathname);
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              aria-current={current ? "page" : undefined}
              className={`-mx-3 flex items-center justify-between gap-3 rounded-xl px-3 py-2 ${
                current ? "bg-surface font-medium" : "text-ink-soft hover:text-ink"
              }`}
            >
              {item.label}
              {item.href === "/painel/aprovacoes" ? <Count value={waiting} /> : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
