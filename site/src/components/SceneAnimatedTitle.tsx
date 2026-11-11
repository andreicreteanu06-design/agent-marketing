"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useMotionValue } from "motion/react";
import { AnimatedTitle } from "./AnimatedTitle";

/** Read the existing engine state; animate only descendants of its heading. */
export function SceneAnimatedTitle({ heading }: { heading: HTMLHeadingElement }) {
  const [active, setActive] = useState(false);
  const progress = useMotionValue(0);
  const text = heading.getAttribute("aria-label") ?? heading.textContent ?? "";
  const lines = text.split(/(?<=\.) /);
  useEffect(() => {
    const copy = heading.closest<HTMLElement>(".sw-copy");
    if (!copy) return;
    let present = false;
    let frame = 0;
    const sync = () => {
      const opacity = Number(copy.style.opacity);
      progress.set(1 - Math.max(0, Math.min(1, opacity)));
      const next = present ? opacity > .015 : copy.style.pointerEvents === "auto";
      if (present === next) return;
      present = next;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => setActive(next));
    };
    const observer = new MutationObserver(sync);
    observer.observe(copy, { attributes: true, attributeFilter: ["style"] });
    sync();
    return () => { cancelAnimationFrame(frame); observer.disconnect(); };
  }, [heading, progress]);
  return createPortal(<AnimatedTitle as="span" lines={lines} active={active} progress={progress} />, heading);
}
