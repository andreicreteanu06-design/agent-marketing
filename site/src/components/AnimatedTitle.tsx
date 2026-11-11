"use client";

import { useLayoutEffect, useRef, type CSSProperties } from "react";
import { motion, useAnimationControls, useReducedMotion, useMotionValue, useSpring, useTransform, type MotionValue, type Variants } from "motion/react";

const SPRING = { type: "spring" as const, mass: 1.9, stiffness: 90, damping: 24 };
const SECTION_SPRING = { type: "spring" as const, mass: 1.6, stiffness: 112, damping: 26 };
const REST = "translate3d(0em,0em,0px) rotateX(0deg) rotateY(0deg) rotateZ(0deg) scale(1)";
const POSES = [
  "translate3d(-1.05em,-.85em,-90px) rotateX(28deg) rotateY(-32deg) rotateZ(-11deg) scale(.96)",
  "translate3d(-.7em,-.55em,-70px) rotateX(22deg) rotateY(-24deg) rotateZ(-7deg) scale(.97)",
  "translate3d(1.05em,-.3em,-100px) rotateX(-18deg) rotateY(38deg) rotateZ(9deg) scale(.96)",
  "translate3d(0em,.9em,-95px) rotateX(72deg) rotateY(-5deg) rotateZ(-2deg) scale(.97)",
  "translate3d(.25em,.7em,-75px) rotateX(58deg) rotateY(8deg) rotateZ(2deg) scale(.98)",
  "translate3d(.25em,.15em,-240px) rotateX(24deg) rotateY(-28deg) rotateZ(5deg) scale(.92)",
];

/** The caller owns scene activation. Only the word descendants own Motion transforms. */
export function AnimatedTitle({ lines, active, playing = active, delay = 0, cadence = "scene", progress, as: Tag = "h2", className = "" }: {
  lines: readonly string[];
  active: boolean;
  playing?: boolean;
  delay?: number;
  cadence?: "scene" | "section";
  progress?: MotionValue<number>;
  as?: "h1" | "h2" | "h3" | "span";
  className?: string;
}) {
  const root = useRef<HTMLHeadingElement & HTMLSpanElement>(null);
  const controls = useAnimationControls();
  const reduce = useReducedMotion();
  const compact = useRef(false);
  // Section headings settle sooner; cinematic scenes keep their approved weight.
  const section = cadence === "section";
  const wordDelay = (index: number) => delay + Math.min(index, section ? 6 : 8) * (section ? .05 : .075);
  const staticProgress = useMotionValue(0);
  const depth = useSpring(progress ?? staticProgress, { stiffness: 170, damping: 30, mass: .8 });
  // Scroll transforms live on the lines; entrance transforms live on the words.
  const firstLine = useTransform(depth, value => {
    const p = reduce ? 0 : value * (compact.current ? .45 : 1);
    return "translate3d(" + (-.65 * p) + "em," + (-.12 * p) + "em," + (-80 * p) + "px) rotateY(" + (-16 * p) + "deg) rotateZ(" + (-3 * p) + "deg)";
  });
  const secondLine = useTransform(depth, value => {
    const p = reduce ? 0 : value * (compact.current ? .45 : 1);
    return "translate3d(" + (.5 * p) + "em," + (.12 * p) + "em," + (-45 * p) + "px) rotateX(" + (12 * p) + "deg) rotateZ(" + (2.5 * p) + "deg)";
  });

  const variants: Variants = {
    hidden: (index: number) => ({
      opacity: 0,
      transform: compact.current
        ? "translate3d(" + (index % 2 ? .25 : -.25) + "em,.45em,-45px) rotateX(" + (index < 3 ? -25 : 40) + "deg) rotateY(0deg) rotateZ(" + (index % 2 ? 3 : -3) + "deg) scale(.96)"
        : POSES[index % POSES.length],
    }),
    visible: (index: number) => ({
      opacity: 1, transform: REST,
      transition: reduce ? { duration: 0 } : {
        transform: { ...(section ? SECTION_SPRING : SPRING), delay: wordDelay(index) },
        opacity: { duration: .24, delay: wordDelay(index) },
      },
    }),
  };

  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    let cancelled = false;
    element.dataset.settled = "false";
    element.dataset.lit = "false";
    compact.current = window.matchMedia("(max-width: 860px)").matches;
    // Prepare before the first paint, including while the engine fades a scene in.
    if (!active) controls.set(reduce ? "visible" : "hidden");
    if (active) {
      if (!reduce) controls.set("hidden");
      void controls.start("visible").then(() => {
        if (!cancelled) element.dataset.settled = "true";
      });
    }
    return () => { cancelled = true; controls.stop(); };
  }, [active, controls, reduce, delay, cadence]);

  useLayoutEffect(() => {
    const element = root.current;
    if (!element || !active || !playing || reduce) return;
    const pointer = window.matchMedia("(hover: hover) and (pointer: fine)");
    let frame = 0;
    let x = 0;
    let y = 0;
    const words = Array.from(element.querySelectorAll<HTMLElement>(".motion-title__word"));
    const move = (event: PointerEvent) => {
      if (!pointer.matches || element.dataset.settled !== "true") return;
      x = event.clientX; y = event.clientY;
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const boxes = words.map(word => word.getBoundingClientRect());
        words.forEach((word, i) => {
          word.style.setProperty("--light-x", (x - boxes[i].left) + "px");
          word.style.setProperty("--light-y", (y - boxes[i].top) + "px");
        });
        element.dataset.lit = "true";
      });
    };
    const leave = () => { cancelAnimationFrame(frame); frame = 0; element.dataset.lit = "false"; };
    element.addEventListener("pointermove", move, { passive: true });
    element.addEventListener("pointerleave", leave);
    const pageVisibility = () => { element.dataset.pageHidden = String(document.hidden); leave(); };
    pageVisibility();
    document.addEventListener("visibilitychange", pageVisibility);
    return () => {
      leave();
      element.removeEventListener("pointermove", move);
      element.removeEventListener("pointerleave", leave);
      document.removeEventListener("visibilitychange", pageVisibility);
    };
  }, [active, playing, reduce]);

  let order = 0;
  return <Tag ref={root} className={"motion-title " + className} aria-label={lines.join(" ")} aria-hidden={Tag === "span" ? true : undefined} data-active={active} data-playing={playing} data-cadence={cadence}>
    {lines.map((line, lineIndex) => <motion.span className="motion-title__line" key={lineIndex} aria-hidden="true" style={{ transform: lineIndex % 2 ? secondLine : firstLine }}>
      {line.split(" ").map((word, wordIndex) => {
        const index = order++;
        return <span key={wordIndex}>{wordIndex > 0 ? " " : null}<motion.span
          className="motion-title__word" custom={index} variants={variants} initial={false} animate={controls}
          style={{ "--word-phase": (section ? lineIndex * -.6 : index * -.32) + "s" } as CSSProperties}>
          <span className="motion-title__ink">{word}</span>
          <span className="motion-title__glow" aria-hidden="true">{word}</span>
        </motion.span></span>;
      })}{lineIndex < lines.length - 1 ? " " : null}
    </motion.span>)}
  </Tag>;
}
