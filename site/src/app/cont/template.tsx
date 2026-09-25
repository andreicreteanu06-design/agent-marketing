import type { ReactNode } from "react";
import { PageTransition } from "@/components/PageTransition";

/**
 * /cont -> /cont/seo-geo sau /cont/produse-chatgpt: acelasi prim segment, deci
 * template-ul radacina nu se remonteaza.
 */
export default function Template({ children }: { children: ReactNode }) {
  return <PageTransition>{children}</PageTransition>;
}
