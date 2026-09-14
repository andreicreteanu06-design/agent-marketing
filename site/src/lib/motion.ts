import type { Variants } from "motion/react";

// Curba standard folosita in tot site-ul pentru intrari pe scroll - un singur
// "simt" de miscare, nu un amestec de easing-uri diferite per sectiune.
export const EASE_OUT = [0.16, 1, 0.3, 1] as const;

export const revealUp: Variants = {
  hidden: { opacity: 0, y: 28 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.7, ease: EASE_OUT },
  },
};

export const staggerChildren = (delay = 0.08): Variants => ({
  hidden: {},
  visible: {
    transition: { staggerChildren: delay },
  },
});
