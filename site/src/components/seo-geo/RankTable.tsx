"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, CaretDown, CaretUp, Minus } from "@phosphor-icons/react/dist/ssr";
import type { SeoKeywordRank } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatDecimal, formatMetric } from "./ui";

type SortKey = "position" | "change" | "clicks" | "impressions" | "ctr" | "search_volume";

const COLUMNS: { key: SortKey; label: string; hint: string }[] = [
  { key: "position", label: "Poziție", hint: "Poziția medie în Google, în perioada aleasă" },
  { key: "change", label: "Evoluție", hint: "Poziții câștigate sau pierdute față de perioada anterioară" },
  { key: "clicks", label: "Trafic", hint: "Clicuri din Google aduse de cuvânt" },
  { key: "impressions", label: "Afișări", hint: "De câte ori a apărut site-ul la acest cuvânt" },
  { key: "ctr", label: "CTR", hint: "Câți din cei care te-au văzut au dat click" },
  { key: "search_volume", label: "Volum lunar", hint: "Căutări pe lună, din Google Keyword Planner" },
];

/** Culoarea pozitiei, ca in rank tracker-ele cunoscute: top 3, pagina 1, pagina 2, restul. */
function positionTone(position: number): string {
  if (position <= 3.5) return "border-emerald-400/30 bg-emerald-400/10 text-emerald-300";
  if (position <= 10.5) return "border-brand-cyan/30 bg-brand-cyan/10 text-brand-cyan";
  if (position <= 20.5) return "border-amber-400/30 bg-amber-400/10 text-amber-200";
  return "border-border-subtle bg-background text-foreground-muted";
}

function Change({ row }: { row: SeoKeywordRank }) {
  if (row.trend === "new") {
    return (
      <span className="rounded-full border border-brand-blue/40 bg-brand-blue/15 px-2 py-0.5 text-xs text-brand-cyan">
        nou
      </span>
    );
  }
  if (row.trend === "stable" || row.change === null) {
    return (
      <span className="inline-flex items-center gap-1 text-foreground-muted">
        <Minus size={12} weight="bold" />
        <span className="tabular-nums">0</span>
      </span>
    );
  }
  const up = row.trend === "up";
  const Arrow = up ? ArrowUp : ArrowDown;
  return (
    <span
      className={cn("inline-flex items-center gap-1 font-medium", up ? "text-emerald-400" : "text-red-400")}
      title={row.previous_position !== null ? `Înainte: ${formatDecimal(row.previous_position)}` : undefined}
    >
      <Arrow size={12} weight="bold" />
      <span className="tabular-nums">{formatDecimal(Math.abs(row.change))}</span>
    </span>
  );
}

function sortValue(row: SeoKeywordRank, key: SortKey): number {
  if (key === "change") return row.change ?? Number.NEGATIVE_INFINITY;
  if (key === "search_volume") return row.search_volume ?? -1;
  return row[key];
}

function pathOf(url: string): string {
  try {
    return new URL(url).pathname;
  } catch {
    return url;
  }
}

/** Clasamentul cuvintelor cheie (stil Ahrefs), sortabil pe orice coloana numerica. */
export function RankTable({ rows }: { rows: SeoKeywordRank[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("clicks");
  // Pozitia e mai buna cand e mica - singura coloana sortata implicit crescator.
  const [ascending, setAscending] = useState(false);

  const sorted = useMemo(() => {
    const direction = ascending ? 1 : -1;
    return [...rows].sort((a, b) => (sortValue(a, sortKey) - sortValue(b, sortKey)) * direction);
  }, [rows, sortKey, ascending]);

  function sortBy(key: SortKey) {
    if (key === sortKey) {
      setAscending((value) => !value);
    } else {
      setSortKey(key);
      setAscending(key === "position");
    }
  }

  if (rows.length === 0) {
    return (
      <p className="px-6 py-10 text-center text-sm text-foreground-muted">
        Search Console nu are încă date pentru perioada aleasă.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-border-subtle text-left text-xs uppercase tracking-wider text-foreground-muted">
            <th className="px-6 py-3 font-medium">Cuvânt cheie</th>
            {COLUMNS.map((column) => (
              <th key={column.key} className="px-3 py-3 text-right font-medium" title={column.hint}>
                <button
                  type="button"
                  onClick={() => sortBy(column.key)}
                  className={cn(
                    "inline-flex items-center gap-1 uppercase tracking-wider transition-colors hover:text-foreground",
                    sortKey === column.key && "text-foreground"
                  )}
                >
                  {column.label}
                  {sortKey === column.key &&
                    (ascending ? <CaretUp size={11} weight="bold" /> : <CaretDown size={11} weight="bold" />)}
                </button>
              </th>
            ))}
            <th className="px-6 py-3 font-medium">URL</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr
              key={row.keyword}
              className="border-b border-border-subtle/60 transition-colors last:border-b-0 hover:bg-white/[0.02]"
            >
              <td className="max-w-64 truncate px-6 py-3 font-medium text-foreground" title={row.keyword}>
                {row.keyword}
              </td>
              <td className="px-3 py-3 text-right">
                <span
                  className={cn(
                    "inline-block min-w-12 rounded-full border px-2 py-0.5 text-center text-xs font-semibold tabular-nums",
                    positionTone(row.position)
                  )}
                >
                  {formatDecimal(row.position)}
                </span>
              </td>
              <td className="px-3 py-3 text-right">
                <Change row={row} />
              </td>
              <td className="px-3 py-3 text-right tabular-nums text-foreground">
                {formatMetric(row.clicks, "number")}
              </td>
              <td className="px-3 py-3 text-right tabular-nums text-foreground-muted">
                {formatMetric(row.impressions, "number")}
              </td>
              <td className="px-3 py-3 text-right tabular-nums text-foreground-muted">
                {formatMetric(row.ctr, "percent")}
              </td>
              <td className="px-3 py-3 text-right tabular-nums text-foreground-muted">
                {row.search_volume === null ? "—" : formatMetric(row.search_volume, "number")}
              </td>
              <td className="max-w-56 truncate px-6 py-3 font-mono text-xs text-foreground-muted" title={row.url ?? ""}>
                {row.url ? pathOf(row.url) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
