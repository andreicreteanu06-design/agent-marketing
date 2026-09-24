"use client";

import type { Icon } from "@phosphor-icons/react";
import { Info, Lightbulb, Sparkle, WarningCircle } from "@phosphor-icons/react/dist/ssr";
import type { SeoInsight } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const KIND: Record<SeoInsight["kind"], { icon: Icon; tone: string }> = {
  alert: { icon: WarningCircle, tone: "bg-red-500/10 text-red-400" },
  opportunity: { icon: Lightbulb, tone: "bg-brand-blue/15 text-brand-cyan" },
  info: { icon: Info, tone: "bg-white/[0.05] text-foreground-muted" },
};

const PRIORITY: Record<SeoInsight["priority"], { label: string; tone: string }> = {
  high: { label: "Urgent", tone: "border-red-400/30 bg-red-500/10 text-red-300" },
  medium: { label: "Important", tone: "border-amber-400/30 bg-amber-400/10 text-amber-200" },
  low: { label: "De urmărit", tone: "border-border-subtle bg-background text-foreground-muted" },
};

function InsightRow({ insight }: { insight: SeoInsight }) {
  const kind = KIND[insight.kind];
  const priority = PRIORITY[insight.priority];
  const KindIcon = kind.icon;
  return (
    <li className="flex gap-4 border-t border-border-subtle px-6 py-5 first:border-t-0">
      <span className={cn("mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl", kind.tone)}>
        <KindIcon size={18} weight="duotone" />
      </span>
      <div className="min-w-0 flex-1 space-y-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium text-foreground">{insight.title}</p>
          <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", priority.tone)}>
            {priority.label}
          </span>
        </div>
        <p className="text-sm leading-relaxed text-foreground-muted">{insight.detail}</p>
        <div className="rounded-xl border border-border-subtle bg-background px-4 py-3">
          <span className="text-xs font-semibold uppercase tracking-widest text-brand-cyan">Ce faci</span>
          <p className="mt-1.5 text-sm leading-relaxed text-foreground">{insight.action}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(insight.evidence).map(([label, value]) => (
            <span
              key={label}
              className="rounded-full bg-background px-2.5 py-1 font-mono text-[11px] text-foreground-muted"
            >
              {label}: <span className="text-foreground">{value}</span>
            </span>
          ))}
        </div>
      </div>
    </li>
  );
}

/** Recomandarile agentului: reguli verificabile peste GA4, Search Console si Keyword Planner. */
export function InsightsPanel({ insights }: { insights: SeoInsight[] }) {
  return (
    <Card>
      <CardHeader className="block">
        <div className="flex items-center gap-2">
          <Sparkle size={16} weight="fill" className="text-brand-cyan" />
          <CardTitle className="text-lg">Recomandări inteligente</CardTitle>
        </div>
        <CardDescription className="mt-1">
          Generate din GA4, Search Console și Keyword Planner după reguli verificabile - fiecare vine
          cu cifrele care au declanșat-o.
        </CardDescription>
      </CardHeader>
      {insights.length === 0 ? (
        <p className="px-6 py-10 text-center text-sm text-foreground-muted">
          Nicio problemă și nicio oportunitate clară în perioada aleasă.
        </p>
      ) : (
        <ul>
          {insights.map((insight) => (
            <InsightRow key={insight.id} insight={insight} />
          ))}
        </ul>
      )}
    </Card>
  );
}
