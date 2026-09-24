"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, Info, WarningCircle } from "@phosphor-icons/react/dist/ssr";
import {
  getSeoIntelligence,
  type SeoIntelligence,
  type SeoMetricKey,
  type SeoMetricSummary,
  type SeoSourceStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { InsightsPanel } from "./InsightsPanel";
import { RankTable } from "./RankTable";
import { useSeoGeoSession } from "./SeoGeoSession";
import { TrafficChart } from "./TrafficChart";
import { formatDecimal, formatMetric, shortDate } from "./ui";

type Period = 7 | 28 | 90;

const PERIODS: { days: Period; label: string }[] = [
  { days: 7, label: "7 zile" },
  { days: 28, label: "28 de zile" },
  { days: 90, label: "3 luni" },
];

/** Filele de deasupra graficului, in ordinea "ce fac vizitatorii" -> "cum te vede Google". */
const TAB_KEYS: SeoMetricKey[] = [
  "sessions",
  "pageviews",
  "engagement_rate",
  "clicks",
  "impressions",
  "position",
];

const STATUS: Record<SeoSourceStatus, { label: string; variant: "success" | "warning" | "neutral" }> = {
  live: { label: "live", variant: "success" },
  demo: { label: "demo", variant: "warning" },
  unavailable: { label: "indisponibil", variant: "warning" },
  not_connected: { label: "neconectat", variant: "neutral" },
};

function ChangeBadge({ metric }: { metric: SeoMetricSummary }) {
  if (metric.change_pct === null) {
    return <span className="text-xs text-foreground-muted">fără comparație</span>;
  }
  const change = metric.change_pct;
  // La pozitie, o scadere e o veste buna - culoarea urmeaza sensul, nu semnul.
  const good = metric.better_when === "up" ? change > 0 : change < 0;
  const Arrow = change >= 0 ? ArrowUp : ArrowDown;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium tabular-nums",
        change === 0 ? "text-foreground-muted" : good ? "text-emerald-400" : "text-red-400"
      )}
    >
      <Arrow size={11} weight="bold" />
      {formatDecimal(Math.abs(change))}%
    </span>
  );
}

function PeriodPicker({ value, onChange }: { value: Period; onChange: (days: Period) => void }) {
  return (
    <div className="inline-flex rounded-full border border-border-subtle bg-background-elevated p-1">
      {PERIODS.map((period) => (
        <button
          key={period.days}
          type="button"
          onClick={() => onChange(period.days)}
          aria-pressed={value === period.days}
          className={cn(
            "rounded-full px-3.5 py-1.5 text-sm transition-colors",
            value === period.days
              ? "bg-brand-blue text-white"
              : "text-foreground-muted hover:text-foreground"
          )}
        >
          {period.label}
        </button>
      ))}
    </div>
  );
}

export function TrafficPositions() {
  const { token, errorMessage } = useSeoGeoSession();
  const [days, setDays] = useState<Period>(28);
  const [data, setData] = useState<SeoIntelligence | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<SeoMetricKey>("sessions");

  useEffect(() => {
    let active = true;
    getSeoIntelligence(token, days)
      .then((response) => {
        if (!active) return;
        setData(response);
        setError(null);
      })
      .catch((err: unknown) => {
        if (active) setError(errorMessage(err, "Nu am putut încărca datele de trafic."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token, days, errorMessage]);

  function changePeriod(next: Period) {
    if (next === days) return;
    setLoading(true);
    setDays(next);
  }

  const tabs = useMemo(
    () =>
      TAB_KEYS.map((key) => data?.summary.find((item) => item.key === key)).filter(
        (item): item is SeoMetricSummary => item !== undefined
      ),
    [data]
  );
  // Indicatorul ales poate lipsi (sursa lui a picat) - atunci primul disponibil.
  const selected = tabs.find((tab) => tab.key === metric) ?? tabs[0];
  const statusOf = (source: "ga4" | "gsc") =>
    data?.sources.find((item) => item.key === source)?.status;
  const demoSources = data?.sources.filter((source) => source.status === "demo") ?? [];

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Trafic &amp; Poziții</h1>
          <p className="mt-2 max-w-2xl text-base text-foreground-muted">
            Ce fac vizitatorii (GA4), cum te vede Google (Search Console) și cât se caută
            (Keyword Planner) - în același loc, cu recomandările agentului.
          </p>
        </div>
        <PeriodPicker value={days} onChange={changePeriod} />
      </header>

      {error && <p className="text-sm text-red-400">{error}</p>}
      {!data && !error && <p className="text-sm text-foreground-muted">Se încarcă...</p>}

      {data && (
        <div className={cn("space-y-8 transition-opacity", loading && "opacity-60")}>
          {data.is_demo && (
            <div className="flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-amber-400/30 bg-amber-400/10 px-5 py-4">
              <div className="flex items-start gap-3">
                <Info size={18} weight="fill" className="mt-0.5 shrink-0 text-amber-200" />
                <div className="space-y-1 text-sm">
                  <p className="font-medium text-amber-100">Date demonstrative</p>
                  <p className="leading-relaxed text-amber-100/80">
                    {demoSources.map((source) => source.label).join(", ")}{" "}
                    {demoSources.length === 1 ? "nu e conectat" : "nu sunt conectate"}, așa că
                    graficul, clasamentul și recomandările folosesc date simulate - ca să vezi ce
                    face agentul. Conectează-le ca să vezi datele reale ale site-ului.
                  </p>
                </div>
              </div>
              <Link
                href="/cont/seo-geo/integrari"
                className="shrink-0 rounded-full bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-blue/90"
              >
                Conectează conturile
              </Link>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 text-xs text-foreground-muted">
            <span>
              {shortDate(data.period.start)} - {shortDate(data.period.end)}, față de perioada
              anterioară ·
            </span>
            {data.sources.map((source) => (
              <span key={source.key} title={source.note ?? undefined}>
                <Badge variant={STATUS[source.status].variant}>
                  {source.label}: {STATUS[source.status].label}
                </Badge>
              </span>
            ))}
          </div>

          <Card className="overflow-hidden">
            {tabs.length > 0 && selected ? (
              <>
                <div className="grid grid-cols-2 border-b border-border-subtle sm:grid-cols-3 xl:grid-cols-6">
                  {tabs.map((tab) => {
                    const active = tab.key === selected.key;
                    const demo = statusOf(tab.source) === "demo";
                    return (
                      <button
                        key={tab.key}
                        type="button"
                        onClick={() => setMetric(tab.key)}
                        aria-pressed={active}
                        className={cn(
                          "flex flex-col items-start gap-1 border-b-2 px-5 py-4 text-left transition-colors",
                          active
                            ? "border-brand-cyan bg-white/[0.03]"
                            : "border-transparent hover:bg-white/[0.02]"
                        )}
                      >
                        <span className="flex items-center gap-1.5 text-xs text-foreground-muted">
                          {tab.label}
                          <span className="rounded bg-background px-1 py-px text-[10px] uppercase tracking-wider">
                            {tab.source === "ga4" ? "GA4" : "GSC"}
                            {demo ? " · demo" : ""}
                          </span>
                        </span>
                        <span className="text-2xl font-semibold tabular-nums text-foreground">
                          {formatMetric(tab.value, tab.format)}
                        </span>
                        <ChangeBadge metric={tab} />
                      </button>
                    );
                  })}
                </div>
                <div className="px-2 pb-4 pt-6 sm:px-4">
                  <TrafficChart data={data.timeseries} metric={selected.key} format={selected.format} />
                </div>
              </>
            ) : (
              <p className="px-6 py-12 text-center text-sm text-foreground-muted">
                Nu există date de trafic pentru perioada aleasă.
              </p>
            )}
          </Card>

          <Card className="overflow-hidden">
            <CardHeader className="block">
              <CardTitle className="text-lg">Cuvinte cheie</CardTitle>
              <CardDescription className="mt-1">
                Pozițiile din Google pe cuvintele care îți aduc vizitatori, față de perioada
                anterioară, cu volumul lunar de căutări din Keyword Planner.
              </CardDescription>
            </CardHeader>
            <RankTable rows={data.keywords} />
          </Card>

          <InsightsPanel insights={data.ai_recommendations} />

          {data.data_gaps.length > 0 && (
            <div className="flex items-start gap-3 rounded-2xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-200">
              <WarningCircle size={18} weight="fill" className="mt-0.5 shrink-0" />
              <div>
                <p className="font-medium">Unele date lipsesc</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-amber-200/80">
                  {data.data_gaps.map((gap) => (
                    <li key={gap}>{gap}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
