"use client";

import { averageResponseMs, type AuditResults } from "@/lib/seoGeoApi";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { CircleProgress } from "@/components/ui/circle-progress";

const SEO_COLOR = (ratio: number): string => {
  if (ratio >= 0.7) return "var(--brand-cyan)";
  if (ratio >= 0.4) return "#f5a623";
  return "#f5424a";
};

function Metric({ label, value, children }: { label: string; value: string; children?: React.ReactNode }) {
  return (
    <div className="px-6 py-5">
      <p className="text-xs font-medium uppercase tracking-widest text-foreground-muted">{label}</p>
      <p className="mt-2 text-3xl font-semibold tabular-nums text-foreground">{value}</p>
      {children && <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-foreground-muted">{children}</div>}
    </div>
  );
}

function SeverityCount({ count, label, dot }: { count: number; label: string; dot: string }) {
  if (count === 0) return null;
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn("h-1.5 w-1.5 rounded-full", dot)} />
      <span className="tabular-nums">{count}</span> {label}
    </span>
  );
}

/** Randul de sus al raportului: cat s-a citit, cate probleme, cat de repede raspunde site-ul. */
export function AuditMetrics({ results }: { results: AuditResults }) {
  const { summary } = results;
  const issues = summary.critical_count + summary.warning_count + summary.info_count;
  const avgMs = averageResponseMs(results.pages);

  return (
    <Card className="grid grid-cols-1 divide-y divide-border-subtle sm:grid-cols-3 sm:divide-x sm:divide-y-0">
      <Metric label="Pagini crawlate" value={String(summary.pages_crawled)}>
        <span>{summary.completed ? "tot site-ul" : "raport parțial"}</span>
      </Metric>
      <Metric label="Probleme găsite" value={String(issues)}>
        <SeverityCount count={summary.critical_count} label="critice" dot="bg-red-500" />
        <SeverityCount count={summary.warning_count} label="avertismente" dot="bg-amber-400" />
        <SeverityCount count={summary.info_count} label="informative" dot="bg-foreground-muted/60" />
      </Metric>
      <Metric label="Timp mediu de răspuns" value={avgMs === null ? "—" : `${avgMs} ms`}>
        <span>pe paginile citite</span>
      </Metric>
    </Card>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-border-subtle py-2.5 text-sm first:border-t-0">
      <span className="text-foreground-muted">{label}</span>
      <span className="font-medium tabular-nums text-foreground">{value}</span>
    </div>
  );
}

/** Cele doua scoruri, plus fisierele site-ului pe care le citesc motoarele de cautare si AI. */
export function AuditScores({ results }: { results: AuditResults }) {
  return (
    <Card className="grid grid-cols-1 gap-8 p-6 md:grid-cols-[auto_1fr] md:items-center md:gap-12 md:p-8">
      <div className="flex items-center justify-center gap-10 sm:gap-14">
        <div className="flex flex-col items-center gap-2">
          <CircleProgress value={results.seo.score} label="SEO" getColor={SEO_COLOR} />
          <span className="text-xs text-foreground-muted">
            {results.seo.checks_failed} din {results.seo.checks_run} verificări picate
          </span>
        </div>
        <div className="flex flex-col items-center gap-2">
          <CircleProgress value={results.geo.score} label="GEO" useGradient />
          <span className="text-xs text-foreground-muted">
            {results.geo.checks_failed} din {results.geo.checks_run} verificări picate
          </span>
        </div>
      </div>
      <div>
        <Fact label="robots.txt" value={results.summary.robots_txt_found ? "da" : "nu"} />
        <Fact label="llms.txt (pentru modele AI)" value={results.summary.llms_txt_found ? "da" : "nu"} />
        <Fact
          label="URL-uri în sitemap"
          value={results.summary.sitemap_urls_found > 0 ? String(results.summary.sitemap_urls_found) : "niciunul"}
        />
      </div>
    </Card>
  );
}
