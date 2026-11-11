"use client";

import { useRef, type ComponentPropsWithoutRef, type CSSProperties, type PointerEvent } from "react";
import { motion, useInView, useMotionValue, useReducedMotion, useSpring } from "motion/react";

type Props = Pick<ComponentPropsWithoutRef<"div">,
  "children" | "className" | "id" | "role" | "aria-label" | "aria-labelledby">;

/** Lighting layers only: content, text choreography and layout stay in place. */
export function MaterialSurface({ children, className = "", ...props }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { amount: 0.12 });
  const reduce = useReducedMotion();
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const spring = { stiffness: 190, damping: 30, mass: 0.65 };
  const lightX = useSpring(x, spring);
  const lightY = useSpring(y, spring);

  function track(event: PointerEvent<HTMLDivElement>) {
    if (reduce || event.pointerType !== "mouse" || !inView) return;
    const box = event.currentTarget.getBoundingClientRect();
    if (!box.width || !box.height) return;
    // The landing scene scales its children; keep light coordinates local.
    x.set(((event.clientX - box.left) / box.width - 0.5) * event.currentTarget.clientWidth * 0.8);
    y.set(((event.clientY - box.top) / box.height - 0.5) * event.currentTarget.clientHeight * 0.8);
  }
  function reset() { x.set(0); y.set(0); }

  return <div ref={ref} {...props} className={`material-surface ${className}`}
    data-material-active={inView && !reduce ? "true" : "false"}
    style={{ "--material-play": inView && !reduce ? "running" : "paused" } as CSSProperties}
    onPointerMove={track} onPointerLeave={reset} onPointerCancel={reset}>
    <span className="material-surface__optics" aria-hidden="true">
      <span className="material-surface__caustic" />
      <motion.span className="material-surface__cursor" style={reduce ? undefined : { x: lightX, y: lightY }} />
      <span className="material-surface__rim" />
    </span>
    {children}
  </div>;
}
