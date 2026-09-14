"use client";

import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { revealUp } from "@/lib/motion";

/**
 * Intrare pe scroll (o singura data, whileInView) - varianta usoara, fara
 * GSAP ScrollTrigger, pentru sectiuni care doar trebuie sa apara la scroll
 * (nu sa se ancoreze/pineze). Vezi StickyStack/HorizontalPan pentru pin.
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
