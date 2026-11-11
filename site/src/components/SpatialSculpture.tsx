"use client";

import Image from "next/image";
import { useRef, type CSSProperties, type PointerEvent } from "react";
import { motion, useInView, useMotionValue, useReducedMotion, useSpring } from "motion/react";

const SCULPTURES = {
  relay: "/sculptures/titanium-relay.webp",
  gateway: "/sculptures/optical-gateway.webp",
} as const;

/** Decorative studio renders. Pointer physics move the presentation, not the page. */
export function SpatialSculpture({ variant, className = "" }: {
  variant: keyof typeof SCULPTURES;
  className?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  const inView = useInView(root, { amount: 0.12 });
  const reduce = useReducedMotion();
  const pitch = useMotionValue(0);
  const yaw = useMotionValue(0);
  const rotateX = useSpring(pitch, { stiffness: 130, damping: 24, mass: 0.9 });
  const rotateY = useSpring(yaw, { stiffness: 130, damping: 24, mass: 0.9 });

  function track(event: PointerEvent<HTMLDivElement>) {
    if (!inView || reduce || event.pointerType !== "mouse") return;
    const bounds = event.currentTarget.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    pitch.set(-((event.clientY - bounds.top) / bounds.height - 0.5) * 8);
    yaw.set(((event.clientX - bounds.left) / bounds.width - 0.5) * 12);
  }
  function reset() { pitch.set(0); yaw.set(0); }

  return <div ref={root} className={`spatial-sculpture spatial-sculpture--${variant} ${className}`} aria-hidden="true"
    data-sculpture-active={inView && !reduce ? "true" : "false"}
    style={{ "--sculpture-play": inView && !reduce ? "running" : "paused" } as CSSProperties}
    onPointerMove={track} onPointerLeave={reset} onPointerCancel={reset}>
    <span className="spatial-sculpture__ambient" />
    <span className="spatial-sculpture__shadow" />
    <motion.div className="spatial-sculpture__gimbal" style={reduce ? undefined : { rotateX, rotateY }}>
      <div className="spatial-sculpture__float">
        <Image src={SCULPTURES[variant]} alt="" fill sizes="(max-width: 600px) 90vw, 560px" className="spatial-sculpture__render" />
        <span className="spatial-sculpture__reflection" />
      </div>
    </motion.div>
  </div>;
}
