import type { ReactNode } from "react";
import { PageTransition } from "@/components/PageTransition";

/**
 * Intre paginile modulului intra doar continutul din <main>: meniul lateral
 * (in layout.tsx, deasupra template-ului) ramane pe loc.
 */
export default function Template({ children }: { children: ReactNode }) {
  return <PageTransition>{children}</PageTransition>;
}
