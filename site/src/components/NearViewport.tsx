"use client";

import { useRef, type ReactNode } from "react";
import { useInView } from "motion/react";

type Margin = NonNullable<Parameters<typeof useInView>[1]>["margin"];

/**
 * Monteaza `children` abia cand containerul ajunge la `margin` de ecran - si
 * il lasa montat dupa aceea. Pentru ce e greu si sta mult sub fold (iframe-ul
 * Cal.com, video-uri): nu mai concureaza la incarcarea paginii cu ce se vede
 * de fapt in primul ecran. Containerul ramane mereu in pagina, cu dimensiunea
 * data de `className`, deci nu apare layout shift cand continutul real preia locul.
 */
export function NearViewport({
  children,
  fallback = null,
  margin = "800px 0px",
  className,
}: {
  children: ReactNode;
  fallback?: ReactNode;
  margin?: Margin;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const near = useInView(ref, { once: true, margin });
  return (
    <div ref={ref} className={className}>
      {near ? children : fallback}
    </div>
  );
}
