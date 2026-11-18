"use client";

import { useEffect, useRef } from "react";

/** Keeps the newest message in view when the conversation opens and when it grows. */
export function ScrollToEnd({ count }: { count: number }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [count]);
  return <div ref={end} />;
}
