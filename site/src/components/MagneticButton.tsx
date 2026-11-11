"use client";

import { motion, useMotionValue, useSpring, useReducedMotion } from "motion/react";
import type { ReactNode, MouseEvent } from "react";

/**
 * Buton cu tragere magnetica usoara spre cursor. Foloseste motion values (nu
 * useState) ca sa nu re-randeze arborele React la fiecare miscare de mouse -
 * vezi regula din taste-skill 3.B.
 */
export function MagneticButton({
  href,
  children,
  className,
  target,
  rel,
}: {
  href: string;
  children: ReactNode;
  className?: string;
  target?: string;
  rel?: string;
}) {
  const reduce = useReducedMotion();
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const springX = useSpring(x, { stiffness: 360, damping: 34, mass: 0.6 });
  const springY = useSpring(y, { stiffness: 360, damping: 34, mass: 0.6 });

  function handleMove(e: MouseEvent<HTMLAnchorElement>) {
    if (reduce || !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    const rect = e.currentTarget.getBoundingClientRect();
    x.set(Math.max(-4, Math.min(4, (e.clientX - rect.left - rect.width / 2) * 0.09)));
    y.set(Math.max(-4, Math.min(4, (e.clientY - rect.top - rect.height / 2) * 0.09)));
  }

  function handleLeave() {
    x.set(0);
    y.set(0);
  }

  return (
    <motion.a
      href={href}
      target={target}
      rel={rel}
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
      style={reduce ? undefined : { x: springX, y: springY }}
      whileTap={reduce ? undefined : { scale: 0.98 }}
      className={className}
    >
      {children}
    </motion.a>
  );
}
