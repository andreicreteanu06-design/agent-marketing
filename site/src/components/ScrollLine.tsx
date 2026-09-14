"use client";

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useReducedMotion } from "motion/react";

gsap.registerPlugin(ScrollTrigger);

/**
 * Linia orizontala din spatele pasilor "Cum functioneaza" se "deseneaza"
 * (scaleX 0 -> 1) pe masura ce sectiunea trece prin viewport - motivat:
 * arata vizual progresia intre pasi, nu doar decor. Statica (scaleX: 1)
 * sub prefers-reduced-motion.
 */
export function ScrollLine({ trackRef }: { trackRef: React.RefObject<HTMLDivElement | null> }) {
  const fillRef = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (reduce || !fillRef.current || !trackRef.current) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        fillRef.current,
        { scaleX: 0 },
        {
          scaleX: 1,
          ease: "none",
          scrollTrigger: {
            trigger: trackRef.current,
            start: "top 70%",
            end: "bottom 60%",
            scrub: 0.5,
          },
        }
      );
    });
    return () => ctx.revert();
  }, [reduce, trackRef]);

  return (
    <div className="pointer-events-none absolute left-0 right-0 top-6 hidden h-px bg-border-subtle md:block">
      <div
        ref={fillRef}
        className="h-full w-full origin-left"
        style={{
          background: "linear-gradient(90deg, #3fd8e8, #1450d8)",
          transform: reduce ? "scaleX(1)" : "scaleX(0)",
        }}
      />
    </div>
  );
}
