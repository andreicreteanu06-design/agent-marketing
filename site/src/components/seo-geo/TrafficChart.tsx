"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";
import type { SeoMetricKey, SeoMetricSummary, SeoTimeSeriesPoint } from "@/lib/api";
import { axisDay, formatMetric, longDay } from "./ui";

const CYAN = "#3fd8e8";
const MUTED = "#a1a1aa";

/** Ce arata tooltip-ul pentru o zi, in ordinea in care se citeste. */
const TOOLTIP_ROWS: { key: SeoMetricKey; label: string; format: SeoMetricSummary["format"] }[] = [
  { key: "sessions", label: "Sesiuni", format: "number" },
  { key: "pageviews", label: "Vizualizări", format: "number" },
  { key: "engagement_rate", label: "Engagement", format: "percent" },
  { key: "clicks", label: "Clicuri Google", format: "number" },
  { key: "impressions", label: "Afișări Google", format: "number" },
  { key: "ctr", label: "CTR", format: "percent" },
  { key: "position", label: "Poziție medie", format: "position" },
];

function ChartTooltip({
  active,
  payload,
  metric,
}: TooltipContentProps & { metric: SeoMetricKey }) {
  const point = payload?.[0]?.payload as SeoTimeSeriesPoint | undefined;
  if (!active || !point) return null;
  const rows = TOOLTIP_ROWS.filter((row) => point[row.key] !== null);
  return (
    <div className="min-w-52 rounded-2xl border border-border-subtle bg-[#101014]/95 px-4 py-3 shadow-2xl backdrop-blur">
      <p className="mb-2 text-xs font-medium text-foreground-muted first-letter:uppercase">
        {longDay(point.date)}
      </p>
      <dl className="space-y-1.5">
        {rows.map((row) => (
          <div key={row.key} className="flex items-center justify-between gap-6 text-sm">
            <dt className="flex items-center gap-2 text-foreground-muted">
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: row.key === metric ? CYAN : "rgba(161,161,170,0.4)" }}
              />
              {row.label}
            </dt>
            <dd
              className={
                row.key === metric
                  ? "font-semibold tabular-nums text-foreground"
                  : "tabular-nums text-foreground/80"
              }
            >
              {formatMetric(point[row.key], row.format)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/**
 * Graficul de trafic (stil Vercel / Plausible): o singura serie - indicatorul
 * ales in filele de deasupra - cu gradient sub linie si detaliile zilei la hover.
 */
export function TrafficChart({
  data,
  metric,
  format,
}: {
  data: SeoTimeSeriesPoint[];
  metric: SeoMetricKey;
  format: SeoMetricSummary["format"];
}) {
  // Pozitia: 1 e cel mai bun loc, deci sus - axa inversata, iar zona se umple
  // spre pozitiile slabe (in jos), ca pe orice grafic de ranking.
  const isPosition = metric === "position";
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="seo-traffic-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CYAN} stopOpacity={0.32} />
              <stop offset="100%" stopColor={CYAN} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="rgba(244,244,245,0.06)" />
          <XAxis
            dataKey="date"
            tickFormatter={axisDay}
            tickLine={false}
            axisLine={false}
            minTickGap={28}
            tick={{ fill: MUTED, fontSize: 12 }}
            dy={8}
          />
          <YAxis
            width={52}
            tickLine={false}
            axisLine={false}
            reversed={isPosition}
            // Pozitia: scala stransa pe datele perioadei (o pozitie rezerva, dar
            // niciodata peste locul 1) - de la 1 la 15, o miscare de 14 -> 13 nu s-ar vedea.
            domain={
              isPosition
                ? [
                    (min: number) => Math.max(1, Math.floor(min - 1)),
                    (max: number) => Math.ceil(max + 1),
                  ]
                : [0, "auto"]
            }
            allowDecimals={format !== "number"}
            tickFormatter={(value: number) => formatMetric(value, format)}
            tick={{ fill: MUTED, fontSize: 12 }}
          />
          <Tooltip
            cursor={{ stroke: "rgba(63,216,232,0.35)", strokeWidth: 1 }}
            content={(props) => <ChartTooltip {...props} metric={metric} />}
          />
          <Area
            type="monotone"
            dataKey={metric}
            stroke={CYAN}
            strokeWidth={2}
            fill="url(#seo-traffic-fill)"
            baseValue={isPosition ? "dataMax" : 0}
            connectNulls
            activeDot={{ r: 4, fill: CYAN, stroke: "#09090b", strokeWidth: 2 }}
            animationDuration={600}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
