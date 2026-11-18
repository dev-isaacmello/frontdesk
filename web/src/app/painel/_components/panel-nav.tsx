"use client";

import { usePathname } from "next/navigation";

import { NavItems } from "./nav-items";

export function PanelNav({ variant, waiting }: { variant: "side" | "tabs"; waiting: number }) {
  return <NavItems variant={variant} waiting={waiting} pathname={usePathname()} />;
}
