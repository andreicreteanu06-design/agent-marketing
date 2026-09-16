"use client";

import { useId } from "react";
import { motion, useReducedMotion } from "motion/react";
import { EASE_OUT } from "@/lib/motion";

/**
 * Inel de progres animat (SVG, nu un progress bar generic) - randat o singura
 * data la reveal (nu whileInView, scorul apare cand parintele decide, ex. dupa
 * ce raspunsul analizei soseste), cu acelasi EASE_OUT folosit in tot site-ul.
 */
export interface CircleProgressProps {
  value: number;
  maxValue?: number;
  size?: number;
  strokeWidth?: number;
  label?: string;
  useGradient?: boolean;
  gradientColors?: readonly [string, string];
  getColor?: (ratio: number) => string;
  className?: string;
}

const DEFAULT_COLOR = (ratio: number): string => {
  if (ratio >= 0.7) return "var(--brand-cyan)";
  if (ratio >= 0.4) return "#f5a623";
  return "#f5424a";
};

export function CircleProgress({
  value,
  maxValue = 100,
  size = 160,
  strokeWidth = 10,
  label,
  useGradient = false,
  gradientColors = ["var(--brand-blue)", "var(--brand-cyan)"] as const,
  getColor = DEFAULT_COLOR,
  className,
}: CircleProgressProps) {
  const reduce = useReducedMotion();
  const reactId = useId();
  const gradientId = `circle-progress-gradient-${reactId}`;

  const ratio = Math.max(0, Math.min(1, maxValue > 0 ? value / maxValue : 0));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - ratio);
  const strokeColor = useGradient ? `url(#${gradientId})` : getColor(ratio);

  return (
    <div className={`flex flex-col items-center gap-3 ${className ?? ""}`}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
          {useGradient && (
            <defs>
              <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor={gradientColors[0]} />
                <stop offset="100%" stopColor={gradientColors[1]} />
              </linearGradient>
            </defs>
          )}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="var(--border-subtle)"
            strokeWidth={strokeWidth}
          />
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={strokeColor}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            initial={{ strokeDashoffset: reduce ? offset : circumference }}
            animate={{ strokeDashoffset: offset }}
            transition={{ duration: 1.1, ease: EASE_OUT }}
          />
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <motion.span
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.4, ease: EASE_OUT }}
            className="text-3xl font-bold text-foreground"
          >
            {Math.round(value)}
          </motion.span>
          <span className="text-xs text-foreground-muted">/ {maxValue}</span>
        </div>
      </div>
      {label && <p className="text-sm font-semibold text-foreground-muted">{label}</p>}
    </div>
  );
}
