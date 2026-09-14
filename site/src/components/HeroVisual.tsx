"use client";

import { motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

const NODES = [
  { key: "google", label: "Google Ads", x: 56, y: 56, color: "#3fd8e8" },
  { key: "meta", label: "Meta Ads", x: 210, y: 30, color: "#1450d8" },
  { key: "tiktok", label: "TikTok Ads", x: 314, y: 64, color: "#7c8cf8" },
] as const;

const CORE = { x: 185, y: 250 };

const PATHS = NODES.map(
  (n) => `M ${n.x} ${n.y} Q ${(n.x + CORE.x) / 2} ${CORE.y - 40} ${CORE.x} ${CORE.y}`
);

const ALLOCATION_STATES = [
  [34, 33, 33],
  [52, 28, 20],
  [31, 46, 23],
  [45, 22, 33],
];

export function HeroVisual() {
  const reduce = useReducedMotion();
  const [stateIndex, setStateIndex] = useState(0);

  useEffect(() => {
    if (reduce) return;
    const id = setInterval(() => setStateIndex((i) => (i + 1) % ALLOCATION_STATES.length), 2800);
    return () => clearInterval(id);
  }, [reduce]);

  const shares = ALLOCATION_STATES[reduce ? 0 : stateIndex];

  return (
    <div className="relative w-full max-w-sm">
      <div
        className="pointer-events-none absolute inset-0 scale-125 rounded-full opacity-40 blur-[80px]"
        style={{ background: "radial-gradient(circle, #1450d8, transparent 70%)" }}
      />
      <svg viewBox="0 0 370 300" className="relative w-full" aria-hidden="true">
        <defs>
          <linearGradient id="flow-gradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="currentColor" stopOpacity="0" />
            <stop offset="0.5" stopColor="currentColor" stopOpacity="1" />
            <stop offset="1" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
          <filter id="core-glow" x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="8" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {NODES.map((node, i) => (
          <g key={node.key}>
            <path
              id={`path-${node.key}`}
              d={PATHS[i]}
              fill="none"
              stroke={node.color}
              strokeOpacity="0.25"
              strokeWidth="1.5"
            />
            {/* offset-path animat prin CSS pur (nu motion.circle) - framer-
                motion incearca sa gestioneze `r` ca motion value si produce
                un atribut invalid cand e combinat cu offset-path/offset-rotate
                pe un <circle>; CSS simplu (--animate-flow-particle din
                globals.css) e mai potrivit oricum pentru un offset-path static. */}
            {!reduce && (
              <circle
                r={3}
                fill={node.color}
                className="animate-flow-particle"
                style={{
                  offsetPath: `path("${PATHS[i]}")`,
                  offsetRotate: "0deg",
                  animationDelay: `${i * 0.5}s`,
                }}
              />
            )}
          </g>
        ))}

        {NODES.map((node, i) => (
          <g key={`node-${node.key}`}>
            <circle cx={node.x} cy={node.y} r="20" fill={node.color} fillOpacity="0.12" />
            <circle cx={node.x} cy={node.y} r="7" fill={node.color} />
            <text
              x={node.x}
              y={node.y - 30}
              textAnchor="middle"
              className="fill-current text-foreground-muted"
              fontSize="10"
            >
              {node.label}
            </text>
            <text
              x={node.x}
              y={node.y + 34}
              textAnchor="middle"
              className="fill-current font-mono text-foreground"
              fontSize="13"
              fontWeight="600"
            >
              {shares[i]}%
            </text>
          </g>
        ))}

        {/* Puls prin `scale` (transform), nu prin `r` direct - motion/react
            are probleme cunoscute animand atribute SVG numerice ca `r`
            direct, plus taste-skill cere transform/opacity, nu alte
            proprietati, pentru animatii ieftine pe GPU. */}
        <motion.circle
          cx={CORE.x}
          cy={CORE.y}
          r={26}
          fill="#0a0a0f"
          stroke="#3fd8e8"
          strokeWidth="1.5"
          filter="url(#core-glow)"
          style={{ transformOrigin: `${CORE.x}px ${CORE.y}px` }}
          animate={reduce ? undefined : { scale: [1, 1.12, 1] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
        />
        <text
          x={CORE.x}
          y={CORE.y + 4}
          textAnchor="middle"
          className="fill-current text-foreground"
          fontSize="9"
          fontWeight="600"
        >
          AC AI
        </text>
      </svg>

      <p className="relative -mt-2 text-center text-xs leading-relaxed text-foreground-muted">
        Thompson Sampling recalculează zilnic, pe date reale de conversie.
      </p>
    </div>
  );
}
