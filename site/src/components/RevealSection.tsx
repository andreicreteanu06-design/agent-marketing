"use client";

import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, type ReactNode } from "react";
import { revealUp } from "@/lib/motion";

/**
 * Intrare pe scroll (o singura data, whileInView) - varianta usoara, fara
 * GSAP ScrollTrigger, pentru sectiuni care doar trebuie sa apara la scroll
 * (nu sa se ancoreze/pineze). Vezi StickyStack/HorizontalPan pentru pin.
 *
 * Doar pentru continut care exista de la incarcarea paginii. Pentru ce apare
 * ca raspuns la o actiune, vezi ``ResultReveal``.
 */
export function RevealSection({
  children,
  className,
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : "hidden"}
      whileInView="visible"
      viewport={{ once: true, amount: 0.3 }}
      variants={revealUp}
      transition={{ delay }}
    >
      {children}
    </motion.div>
  );
}

/**
 * Intrare pentru continut aparut ca raspuns la o actiune (raportul unui audit,
 * pasul urmator al unui formular): animatia porneste la montare, nu la scroll,
 * iar blocul se aduce singur in ecran.
 *
 * Cu ``RevealSection``, un rezultat montat sub marginea ecranului ramane
 * invizibil (opacity 0) pana cand utilizatorul deruleaza - iar el nu are de
 * unde sti ca a aparut ceva: sub formular pare ca nu e nimic.
 */
export function ResultReveal({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);

  // O singura data, la montare: blocul apare o data per actiune. Preferinta de
  // miscare se citeste aici direct, nu din hook, ca efectul sa nu mai ruleze
  // (si sa nu mai traga pagina) cand hook-ul isi termina initializarea.
  useEffect(() => {
    const instant = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    ref.current?.scrollIntoView({ behavior: instant ? "auto" : "smooth", block: "start" });
  }, []);

  return (
    <motion.div
      ref={ref}
      // scroll-mt: sa nu ajunga sub navbar-ul fix.
      className={`scroll-mt-28 ${className ?? ""}`}
      initial={reduce ? false : "hidden"}
      animate="visible"
      variants={revealUp}
    >
      {children}
    </motion.div>
  );
}
