"use client";

import { useEffect, useRef, type PointerEvent, type ReactNode } from "react";

/** Pointer work is event-driven and applied directly to the moving layers. */
export function SpotlightCard({ children, className }: { children: ReactNode; className?: string }) {
  const frame = useRef(0);
  const light = useRef<HTMLSpanElement>(null);
  const point = useRef({ x: 0, y: 0 });
  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  function trackLight(event: PointerEvent<HTMLDivElement>) {
    if (event.pointerType === "touch" || !window.matchMedia("(hover:hover) and (pointer:fine) and (prefers-reduced-motion:no-preference)").matches) return;
    const card = event.currentTarget;
    point.current = { x: event.clientX, y: event.clientY };
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => {
      // One geometry read per frame. Correct for the sticky deck's CSS scale.
      const rect = card.getBoundingClientRect();
      const width = card.clientWidth;
      const height = card.clientHeight;
      if (!rect.width || !rect.height || !width || !height) { frame.current = 0; return; }
      const x = (point.current.x - rect.left) * width / rect.width;
      const y = (point.current.y - rect.top) * height / rect.height;
      const dx = x / width - 0.5;
      const dy = y / height - 0.5;
      if (light.current) light.current.style.transform = `translate3d(${x - 220}px,${y - 220}px,0)`;
      card.style.setProperty("--spotlight-x", `${x}px`);
      card.style.setProperty("--spotlight-y", `${y}px`);
      card.dataset.pointerLit = "true";
      const art = card.querySelector<HTMLElement>(".service-card__art");
      if (art) art.style.transform = `perspective(900px) rotateX(${-dy * 7}deg) rotateY(${dx * 10}deg) translate3d(${dx * 13}px,${dy * 10}px,0)`;
      frame.current = 0;
    });
  }

  function reset(event: PointerEvent<HTMLDivElement>) {
    cancelAnimationFrame(frame.current);
    frame.current = 0;
    delete event.currentTarget.dataset.pointerLit;
    event.currentTarget.querySelector<HTMLElement>(".service-card__art")?.style.removeProperty("transform");
  }

  return <div onPointerEnter={trackLight} onPointerMove={trackLight} onPointerLeave={reset} onPointerCancel={reset} className={`spotlight-card group ${className ?? ""}`}>
    <span className="spotlight-card__light" ref={light} aria-hidden="true" />
    <span className="spotlight-card__refraction" aria-hidden="true" />
    {children}
  </div>;
}
