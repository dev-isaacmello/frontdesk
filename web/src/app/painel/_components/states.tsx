import type { ReactNode } from "react";

import { RetryButton } from "./retry-button";

/** Something the owner should read in place of the content: nothing here yet, or a failure. */
export function Notice({
  title,
  children,
  action,
  className = "px-4 lg:px-8",
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`py-12 lg:py-16 ${className}`}>
      <p className="text-lg font-medium">{title}</p>
      {children ? <p className="mt-1.5 max-w-md text-ink-soft">{children}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function LoadFailed({ what, className }: { what: string; className?: string }) {
  return (
    <div role="alert">
      <Notice
        title={`Não foi possível carregar ${what}.`}
        action={<RetryButton />}
        className={className}
      >
        O painel não conseguiu falar com o servidor. Tente de novo em instantes.
      </Notice>
    </div>
  );
}

/** A grey bar standing in for a line of text while the real one loads. */
export function Bar({ className }: { className: string }) {
  return <span className={`block rounded-full bg-bubble motion-safe:animate-pulse ${className}`} />;
}

export function Loading({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="status" aria-label={label}>
      {children}
    </div>
  );
}
