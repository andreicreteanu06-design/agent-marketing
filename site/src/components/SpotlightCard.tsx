"use client";

import { motion, useMotionTemplate, useMotionValue, useSpring, useTransform } from "motion/react";
import type { MouseEvent, ReactNode } from "react";

const TILT_RANGE = 8; // grade maxime de inclinare - suficient sa se simta 3D, nu de circ

/**
 * Card cu inclinare 3D pe cursor (perspective + rotateX/rotateY) plus un glow
 * radial care il urmareste pe aceeasi pozitie - amandoua pe motion values
 * (nu useState), vezi taste-skill 3.B despre valori continue din input.
 */
export function SpotlightCard({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);
  // Procent 0..1 in card, pentru inclinare - separat de mouseX/Y (pixeli, pt glow).
  const px = useMotionValue(0.5);
  const py = useMotionValue(0.5);
  const springConfig = { stiffness: 200, damping: 20, mass: 0.5 };
  const rotateX = useSpring(useTransform(py, [0, 1], [TILT_RANGE, -TILT_RANGE]), springConfig);
  const rotateY = useSpring(useTransform(px, [0, 1], [-TILT_RANGE, TILT_RANGE]), springConfig);

  function handleMove(e: MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    mouseX.set(e.clientX - rect.left);
    mouseY.set(e.clientY - rect.top);
    px.set((e.clientX - rect.left) / rect.width);
    py.set((e.clientY - rect.top) / rect.height);
  }

  function handleLeave() {
    px.set(0.5);
    py.set(0.5);
  }

  const spotlight = useMotionTemplate`radial-gradient(260px circle at ${mouseX}px ${mouseY}px, rgba(63,216,232,0.14), transparent 70%)`;

  return (
    <motion.div
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
      whileHover={{ y: -4 }}
      transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
      style={{ perspective: 900 }}
      className="group relative h-full"
    >
      {/* Randul care se inclina e cel cu bordura/fundal (className-ul primit) -
          altfel continutul s-ar inclina separat de propria lui bordura. */}
      <motion.div
        style={{ rotateX, rotateY, transformStyle: "preserve-3d" }}
        className={`relative h-full overflow-hidden ${className ?? ""}`}
      >
        <motion.div
          className="pointer-events-none absolute inset-0 z-10 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
          style={{ background: spotlight }}
        />
        {children}
      </motion.div>
    </motion.div>
  );
}
