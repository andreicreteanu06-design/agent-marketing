"use client";

// Componenta lipsea din specificatia primita (demo.tsx o importa, dar sursa
// ei nu a fost data) - construita aici ca sa completeze integrarea: titlu cu
// reveal pe cuvinte, orchestrat de prop-ul `open` (nu de whileInView), ca sa
// porneasca sincron cu GlowHorizonFM cand ambele sunt montate in acelasi hero.
import { motion } from "motion/react";

const EASE = [0.16, 1, 0.3, 1] as const;

export interface AnimatedTitleFMProps {
  open: boolean;
  title?: string;
  subtitle?: string;
  align?: "left" | "center";
  className?: string;
  titleClassName?: string;
}

export function AnimatedTitleFM({
  open,
  title = "Bugetul de reclame, realocat automat.",
  subtitle,
  align = "center",
  className,
  titleClassName,
}: AnimatedTitleFMProps) {
  const words = title.split(" ");
  const isCenter = align === "center";

  return (
    <div className={`relative z-10 ${isCenter ? "text-center" : "text-left"} ${className ?? ""}`}>
      <h1
        className={
          `flex flex-wrap gap-x-3 text-4xl font-bold leading-[1.1] tracking-tight text-white md:text-6xl ` +
          (isCenter ? "justify-center " : "justify-start ") +
          (titleClassName ?? "")
        }
      >
        {words.map((word, i) => (
          <span key={`${word}-${i}`} className="overflow-hidden py-1">
            <motion.span
              className="inline-block"
              initial={{ y: "110%", opacity: 0 }}
              animate={open ? { y: "0%", opacity: 1 } : undefined}
              transition={{ duration: 0.9, ease: EASE, delay: 0.5 + i * 0.07 }}
            >
              {word}
            </motion.span>
          </span>
        ))}
      </h1>
      {subtitle && (
        <motion.p
          className={`mt-5 max-w-lg text-base text-white/60 md:text-lg ${isCenter ? "mx-auto" : ""}`}
          initial={{ opacity: 0, y: 16 }}
          animate={open ? { opacity: 1, y: 0 } : undefined}
          transition={{ duration: 0.8, ease: EASE, delay: 0.5 + words.length * 0.07 + 0.2 }}
        >
          {subtitle}
        </motion.p>
      )}
    </div>
  );
}

export default AnimatedTitleFM;
