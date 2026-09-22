"use client";

import { useMemo, useState } from "react";
import { CaretRight } from "@phosphor-icons/react/dist/ssr";
import type { AffectedPage, IssueGroup, IssuePillar, IssueSeverity } from "@/lib/seoGeoApi";

/**
 * Lista de probleme a unui audit, grupata pe severitate si pe tip.
 *
 * Portare a `src/client/features/audit/results/IssuesView.tsx` din
 * every-app/open-seo, inclusiv decizia lui de prezentare: gruparea se face pe
 * TIP de problema, nu pe pagina. "40 de pagini fara meta description" e o
 * singura sarcina de lucru, nu 40 de randuri identice.
 *
 * Gruparea si sortarea vin deja facute de la server (seo_geo_agent/schemas.py),
 * ca UI-ul si eventualele exporturi sa nu poata ajunge la ordini diferite.
 */

const SEVERITY_DOT: Record<IssueSeverity, string> = {
  critical: "bg-red-500",
  warning: "bg-amber-400",
  info: "bg-foreground-muted/40",
};

const SEVERITY_RULE: Record<IssueSeverity, string> = {
  critical: "border-l-red-500/60",
  warning: "border-l-amber-400/60",
  info: "border-l-border-subtle",
};

const SEVERITY_LABEL: Record<IssueSeverity, string> = {
  critical: "Critice",
  warning: "Avertismente",
  info: "Informative",
};

const PILLAR_LABEL: Record<IssuePillar, string> = {
  seo: "SEO",
  geo: "GEO",
};

/** Cate URL-uri afisam per problema inainte de "si încă N". */
const MAX_RENDERED_URLS = 25;

/** Etichete pentru valorile masurate, ca sa nu apara chei tehnice in interfață. */
const DETAIL_LABELS: Record<string, string> = {
  status_code: "status",
  length: "lungime",
  word_count: "cuvinte",
  response_time_ms: "timp răspuns (ms)",
  h1_count: "H1",
  crawl_depth: "adâncime",
  images_missing_alt: "imagini fără alt",
  images_total: "imagini",
  target_url: "ținta",
  target_status: "status țintă",
  group_size: "pagini în grup",
  other_urls: "alte URL-uri",
  canonical_url: "canonic",
  html_canonical: "canonic HTML",
  header_canonical: "canonic antet",
  hops: "salturi",
  final_url: "destinație",
  mentions: "mențiuni",
  brand: "brand",
  average_sentence_words: "cuvinte/propoziție",
  sentence_count: "propoziții",
  subheading_count: "subtitluri",
  html_bytes: "octeți HTML",
  blocked_crawlers: "crawlere blocate",
  declared_types: "tipuri declarate",
  robots_meta: "meta robots",
  x_robots_tag: "X-Robots-Tag",
};

function formatDetailValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (value === null || value === undefined) return "—";
  return String(value);
}

function DetailChips({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details).filter(([, value]) => value !== null && value !== "");
  if (entries.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-1.5">
      {entries.map(([key, value]) => (
        <span
          key={key}
          className="rounded-full bg-background-elevated px-2 py-0.5 font-mono text-[11px] text-foreground-muted"
        >
          {DETAIL_LABELS[key] ?? key}: {formatDetailValue(value)}
        </span>
      ))}
    </span>
  );
}

function AffectedList({ pages, total }: { pages: AffectedPage[]; total: number }) {
  const shown = pages.slice(0, MAX_RENDERED_URLS);
  return (
    <ul className="mt-4 space-y-2">
      {shown.map((page, index) => (
        <li
          key={`${page.page_url}-${index}`}
          className="flex flex-col gap-1 border-t border-border-subtle pt-2 first:border-t-0 first:pt-0"
        >
          <a
            href={page.page_url}
            target="_blank"
            rel="noreferrer"
            className="break-all font-mono text-xs text-brand-cyan hover:underline"
          >
            {page.page_url}
          </a>
          <DetailChips details={page.details} />
        </li>
      ))}
      {total > shown.length && (
        <li className="pt-1 text-xs text-foreground-muted">
          …și încă {total - shown.length} {total - shown.length === 1 ? "pagină" : "pagini"}.
        </li>
      )}
    </ul>
  );
}

function IssueRow({ group }: { group: IssueGroup }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`border-l-2 ${SEVERITY_RULE[group.severity]}`}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-background-elevated/60"
      >
        <CaretRight
          size={14}
          className={`shrink-0 text-foreground-muted transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="flex-1 text-sm font-medium text-foreground">{group.title}</span>
        <span className="rounded-full border border-border-subtle px-2 py-0.5 text-[11px] uppercase tracking-wider text-foreground-muted">
          {PILLAR_LABEL[group.pillar]}
        </span>
        <span className="min-w-8 text-right text-sm tabular-nums text-foreground-muted">
          {group.count}
        </span>
      </button>

      {open && (
        <div className="px-4 pb-5 pl-11">
          <p className="text-sm leading-relaxed text-foreground-muted">{group.explanation}</p>
          <div className="mt-3 rounded-xl border border-border-subtle bg-background-elevated p-4">
            <span className="text-xs font-semibold uppercase tracking-widest text-brand-cyan">
              Cum se repară
            </span>
            <p className="mt-2 text-sm leading-relaxed text-foreground">{group.how_to_fix}</p>
          </div>
          <AffectedList pages={group.affected_pages} total={group.count} />
        </div>
      )}
    </div>
  );
}

export function AuditIssuesView({ issues }: { issues: IssueGroup[] }) {
  const sections = useMemo(
    () =>
      (["critical", "warning", "info"] as const)
        .map((severity) => ({ severity, groups: issues.filter((g) => g.severity === severity) }))
        .filter((section) => section.groups.length > 0),
    [issues]
  );

  if (issues.length === 0) {
    return (
      <div className="rounded-2xl border border-border-subtle py-10 text-center">
        <p className="font-medium text-foreground">Nicio problemă găsită la paginile auditate.</p>
        <p className="mt-1 text-sm text-foreground-muted">
          Toate verificările au trecut pe paginile pe care le-am putut citi.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-border-subtle">
      {sections.map((section) => (
        <div key={section.severity}>
          <div className="flex items-center gap-2 border-y border-border-subtle bg-background-elevated px-4 py-2 first:border-t-0">
            <span className={`h-2 w-2 rounded-full ${SEVERITY_DOT[section.severity]}`} />
            <span className="text-xs font-semibold uppercase tracking-widest text-foreground-muted">
              {SEVERITY_LABEL[section.severity]}
            </span>
            <span className="text-xs tabular-nums text-foreground-muted">
              ({section.groups.reduce((total, group) => total + group.count, 0)})
            </span>
          </div>
          {section.groups.map((group) => (
            <IssueRow key={group.issue_type} group={group} />
          ))}
        </div>
      ))}
    </div>
  );
}
