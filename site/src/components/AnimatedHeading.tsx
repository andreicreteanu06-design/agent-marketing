"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { AnimatedTitle } from "./AnimatedTitle";

/** Each heading has one entrance owner; surrounding reveals never animate it again. */
export function AnimatedHeading({ text, as: Tag = "h2", className, align = "left", delay = 0, amount = .3 }: {
  text: string;
  as?: "h1" | "h2" | "h3";
  className?: string;
  align?: "left" | "center";
  delay?: number;
  amount?: number;
}) {
  const ref = useRef<HTMLHeadingElement>(null);
  const [presence, setPresence] = useState({ entered: false, visible: false });
  useLayoutEffect(() => {
    const heading = ref.current;
    if (!heading) return;
    const observer = new IntersectionObserver(([entry]) => {
      setPresence(previous => ({ entered: previous.entered || entry.isIntersecting, visible: entry.isIntersecting }));
    }, { threshold: Math.max(0, Math.min(amount, .3)), rootMargin: "0px 0px -20px 0px" });
    observer.observe(heading);
    return () => observer.disconnect();
  }, [amount]);
  return <Tag ref={ref} data-motion-heading="" aria-label={text.replace(/\n/g, " ")} className={"premium-heading kinetic-heading " + (className ?? "")} style={{ textAlign: align }}>
    <AnimatedTitle as="span" lines={text.split("\n")} active={presence.entered} playing={presence.visible} cadence="section" delay={Math.max(0, Math.min(delay, .12))} />
  </Tag>;
}
