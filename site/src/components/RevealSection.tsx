"use client";

import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import { revealUp } from "@/lib/motion";

/** CSS stagger, one observer per group. Text is readable before hydration. */
export function RevealSection({ children, className, delay = 0 }: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const items = Array.from(root.querySelectorAll<HTMLElement>("h1, h2, h3, p, a, button, [data-reveal]"))
      .filter(node => node.closest(".reveal-section") === root && !node.matches(".kinetic-heading") && !(node.matches("a") && node.querySelector("h1, h2, h3, p")));
    items.forEach((node, index) => {
      node.setAttribute("data-reveal-item", "");
      node.style.setProperty("--reveal-order", String(Math.min(index, 4)));
    });
    const observer = new IntersectionObserver(([entry]) => {
      root.classList.toggle("is-visible", entry.isIntersecting);
      if (entry.isIntersecting) root.classList.add("is-in-view");
    }, { threshold: 0.06, rootMargin: "0px 0px -24px 0px" });
    observer.observe(root);
    return () => observer.disconnect();
  }, []);
  return <div ref={ref} className={`reveal-section ${className ?? ""}`} style={{ "--reveal-delay": `${Math.min(delay, 0.12)}s` } as CSSProperties}>{children}</div>;
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
