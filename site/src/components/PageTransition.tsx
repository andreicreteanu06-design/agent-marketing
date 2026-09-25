"use client";

import {
  createContext,
  useContext,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { usePathname } from "next/navigation";
import { motion, useReducedMotion } from "motion/react";
import { EASE_OUT } from "@/lib/motion";

/**
 * true cat timp un PageTransition parinte isi ruleaza intrarea. Template-urile
 * imbricate se monteaza deodata cand se schimba mai multe segmente (ex. / ->
 * /cont/seo-geo/trafic monteaza template-urile din app/, cont/ si
 * cont/seo-geo/): doar cel mai de sus anima, altfel opacitatile s-ar inmulti,
 * iar alunecarile s-ar aduna (30px in loc de 10px).
 */
const ParentEntering = createContext(false);

const noSubscription = () => () => {};

/**
 * Rute cu straturi `position: fixed; inset: 0` in pagina (scroll-world de pe
 * homepage). Un `transform` pe un stramos devine containing block pentru
 * elementele fixed: cat ar dura alunecarea, straturile s-ar intinde pe toata
 * inaltimea paginii (~11 ecrane) in loc de ecran. Acolo intrarea e doar fade.
 */
const FADE_ONLY_ROUTES = new Set(["/"]);

/**
 * Intrarea paginii la navigare: fade + alunecare de 10px in 0.3s. Folosit din
 * template.tsx, pe care Next il remonteaza la fiecare schimbare a segmentului
 * lui - layout-urile de deasupra (Navbar, meniul lateral) raman pe loc.
 *
 * Prima incarcare NU se animeaza: HTML-ul venit de la server e vizibil din
 * primul cadru, fara sa astepte JavaScript-ul (altfel pagina ar sta la
 * opacity 0 pana la hidratare). La fel sub prefers-reduced-motion.
 */
export function PageTransition({ children }: { children: ReactNode }) {
  const parentEntering = useContext(ParentEntering);
  const reduceMotion = useReducedMotion();
  const pathname = usePathname();
  // false pe server si la hidratare, true la orice montare de dupa - adica la
  // navigarile client-side.
  const hydrated = useSyncExternalStore(noSubscription, () => true, () => false);
  // Decis o data, la montare: template-ul primeste o instanta noua la fiecare navigare.
  const [animate] = useState(() => hydrated && !parentEntering && !reduceMotion);
  const [entering, setEntering] = useState(animate);
  const slide = !FADE_ONLY_ROUTES.has(pathname);

  return (
    <ParentEntering.Provider value={entering}>
      <motion.div
        initial={animate ? { opacity: 0, y: slide ? 10 : 0 } : false}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: EASE_OUT }}
        onAnimationComplete={() => setEntering(false)}
      >
        {children}
      </motion.div>
    </ParentEntering.Provider>
  );
}
