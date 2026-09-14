"use client";

import { motion, useScroll, useSpring } from "motion/react";

/**
 * Bara subtire de progres al scroll-ului, sus de tot. useScroll (nu
 * window.addEventListener('scroll')) - vezi regula din taste-skill 5.D.
 */
export function ScrollProgress() {
  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, {
    stiffness: 260,
    damping: 30,
    restDelta: 0.001,
  });

  return (
    <motion.div
      className="fixed left-0 right-0 top-0 z-[70] h-[2px] origin-left"
      style={{
        scaleX,
        background: "linear-gradient(90deg, #3fd8e8, #1450d8)",
      }}
    />
  );
}
