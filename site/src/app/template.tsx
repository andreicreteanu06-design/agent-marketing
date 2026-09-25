import type { ReactNode } from "react";
import { PageTransition } from "@/components/PageTransition";

/**
 * Remontat de Next la fiecare schimbare a primului segment (/, /servicii,
 * /cont, /login...): pagina noua intra cu fade + alunecare, peste Navbar-ul si
 * fundalurile din layout.tsx, care nu se reranda. Template-urile din
 * servicii/, cont/ si cont/seo-geo/ acopera navigarile mai adanci.
 */
export default function Template({ children }: { children: ReactNode }) {
  return <PageTransition>{children}</PageTransition>;
}
