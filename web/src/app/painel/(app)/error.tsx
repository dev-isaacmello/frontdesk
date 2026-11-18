"use client";

import { useEffect } from "react";

export default function PanelError({ error, retry }: { error: unknown; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div role="alert" className="px-4 py-12 lg:px-8 lg:py-16">
      <p className="text-lg font-medium">Algo deu errado nesta tela.</p>
      <p className="mt-1.5 max-w-md text-ink-soft">
        Nada do que você já salvou foi perdido. Tente abrir de novo.
      </p>
      <button
        type="button"
        onClick={() => retry()}
        className="mt-5 h-11 rounded-full border border-line px-5 font-medium"
      >
        Tentar de novo
      </button>
    </div>
  );
}
