"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

export function RetryButton() {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <button
      type="button"
      disabled={pending}
      onClick={() => start(() => router.refresh())}
      className="h-11 rounded-full border border-line px-5 font-medium transition-opacity disabled:opacity-50"
    >
      {pending ? "Tentando" : "Tentar de novo"}
    </button>
  );
}
