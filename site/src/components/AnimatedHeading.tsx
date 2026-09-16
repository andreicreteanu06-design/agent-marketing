"use client";

import { motion, useReducedMotion, type Variants } from "motion/react";
import { useEffect, useRef } from "react";
import { EASE_OUT } from "@/lib/motion";

const MOTION_TAGS = { h1: motion.h1, h2: motion.h2, h3: motion.h3 } as const;

// Container-ul (h1/h2/h3 in sine) e cel observat de whileInView - nu are
// overflow-hidden si nu e transformat, deci IntersectionObserver ii poate
// calcula corect raportul de intersectie. Cuvintele copil doar mostenesc
// starea prin variants (propagare Motion), fara observer propriu - un
// observer plasat direct pe un cuvant translatat+cliupuit ramane la raport 0
// pentru totdeauna, pentru ca ascunderea lui initiala IL scoate din zona
// vizibila calculata de browser fata de parintele cu overflow-hidden.
const container: Variants = {
  hidden: {},
  visible: (delay: number) => ({
    transition: { staggerChildren: 0.045, delayChildren: delay },
  }),
};

const word: Variants = {
  hidden: { y: "110%", opacity: 0 },
  visible: { y: "0%", opacity: 1, transition: { duration: 0.7, ease: EASE_OUT } },
};

/**
 * Titlu cu reveal cuvant-cu-cuvant la scroll (whileInView, o singura data) -
 * acelasi "simt" ca AnimatedTitleFM din Hero, dar declansat de viewport in
 * loc de prop-ul `open`, pentru sectiunile de mai jos in pagina.
 */
export function AnimatedHeading({
  text,
  as = "h2",
  className,
  align = "left",
  delay = 0,
  amount = 0.5,
}: {
  text: string;
  as?: keyof typeof MOTION_TAGS;
  className?: string;
  align?: "left" | "center";
  delay?: number;
  amount?: number;
}) {
  const reduce = useReducedMotion();
  const words = text.split(" ");
  const ref = useRef<HTMLHeadingElement>(null);

  // Glow-ul (.heading-glow) si gradientul pe cuvinte (.heading-gradient-word)
  // ruleaza in bucla infinita prin text-shadow/background-position - paint,
  // nu compositor, deci fara asta ar repicta la nesfarsit orice titlu deja
  // scrolat departe. .is-paused (vezi globals.css) le opreste cat timp
  // titlul e in afara viewport-ului; vizualul cand E vizibil nu se schimba.
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const io = new IntersectionObserver(
      ([entry]) => node.classList.toggle("is-paused", !entry.isIntersecting),
      { rootMargin: "200px 0px" },
    );
    io.observe(node);
    return () => io.disconnect();
  }, []);

  if (reduce) {
    const PlainTag = as;
    return (
      <PlainTag className={`heading-glow heading-gradient-word ${className ?? ""}`}>
        {text}
      </PlainTag>
    );
  }

  const Tag = MOTION_TAGS[as];

  return (
    <Tag
      ref={ref}
      className={`heading-glow flex flex-wrap gap-x-[0.28em] ${align === "center" ? "justify-center" : "justify-start"} ${className ?? ""}`}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, amount }}
      variants={container}
      custom={delay}
    >
      {words.map((w, i) => (
        <span key={`${w}-${i}`} className="overflow-hidden py-1">
          <motion.span
            className="heading-gradient-word inline-block"
            variants={word}
            style={{ animationDelay: `${i * -0.15}s` }}
          >
            {w}
          </motion.span>
        </span>
      ))}
    </Tag>
  );
}
