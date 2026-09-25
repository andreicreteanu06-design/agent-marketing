import type { ReactNode } from "react";
import { PageTransition } from "@/components/PageTransition";

/** De la un serviciu la altul (/servicii/a -> /servicii/b) template-ul radacina nu se remonteaza. */
export default function Template({ children }: { children: ReactNode }) {
  return <PageTransition>{children}</PageTransition>;
}
