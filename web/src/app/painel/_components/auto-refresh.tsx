"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

const EVERY_MS = 30_000;

/**
 * The API has no stream for the owner, so the panel asks again from time to time while
 * it is on screen. Without it a customer's reply would only show after a reload.
 */
export function AutoRefresh() {
  const router = useRouter();
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        router.refresh();
      }
    }, EVERY_MS);
    return () => window.clearInterval(timer);
  }, [router]);
  return null;
}
