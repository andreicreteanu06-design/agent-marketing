"use client";

import { useMemo, useState } from "react";
import type { AuditPageRow, PageFetchClass } from "@/lib/seoGeoApi";

/**
 * Tabelul paginilor crawlate - portare a
 * `src/client/features/audit/results/PagesTable.tsx` din every-app/open-seo.
 *
 * Exista ca sa poti VERIFICA raportul: fiecare problema din lista de mai sus
 * trimite la un URL care apare si aici, cu valorile masurate pe el. Un audit
 * care iti da doar concluzii, fara datele din care au iesit, nu e verificabil.
 */

const FETCH_CLASS_LABEL: Record<PageFetchClass, string> = {
  ok: "OK",
  blocked: "Blocat",
  rate_limited: "Limitat",
  error: "Eroare",
};

function statusClass(page: AuditPageRow): string {
  if (page.fetch_class !== "ok") return "text-amber-400";
  if (page.status_code >= 400) return "text-red-400";
  if (page.status_code >= 300) return "text-foreground-muted";
  return "text-brand-cyan";
}

type SortKey = "url" | "issues" | "words" | "speed";

export function AuditPagesTable({ pages }: { pages: AuditPageRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("issues");

  const sorted = useMemo(() => {
    const copy = [...pages];
    switch (sortKey) {
      case "issues":
        return copy.sort((a, b) => b.issue_count - a.issue_count || a.url.localeCompare(b.url));
      case "words":
        return copy.sort((a, b) => a.word_count - b.word_count);
      case "speed":
        return copy.sort((a, b) => b.response_time_ms - a.response_time_ms);
      default:
        return copy.sort((a, b) => a.url.localeCompare(b.url));
    }
  }, [pages, sortKey]);

  if (pages.length === 0) {
    return (
      <p className="rounded-2xl border border-border-subtle py-10 text-center text-sm text-foreground-muted">
        Nicio pagină crawlată.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-foreground-muted">Sortează după:</span>
        {(
          [
            ["issues", "probleme"],
            ["words", "cuvinte"],
            ["speed", "timp răspuns"],
            ["url", "URL"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setSortKey(key)}
            className={`rounded-full border px-3 py-1 transition-colors ${
              sortKey === key
                ? "border-brand-cyan/50 bg-brand-cyan/10 text-brand-cyan"
                : "border-border-subtle text-foreground-muted hover:text-foreground"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-2xl border border-border-subtle">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="bg-background-elevated text-xs uppercase tracking-wider text-foreground-muted">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">URL</th>
              <th scope="col" className="px-3 py-3 font-medium">Status</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">Cuvinte</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">H1</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">Linkuri</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">ms</th>
              <th scope="col" className="px-3 py-3 text-center font-medium">JSON-LD</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">Probleme</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((page) => (
              <tr key={page.url} className="border-t border-border-subtle align-top">
                <td className="max-w-[320px] px-4 py-3">
                  <a
                    href={page.url}
                    target="_blank"
                    rel="noreferrer"
                    className="block break-all font-mono text-xs text-brand-cyan hover:underline"
                  >
                    {page.url}
                  </a>
                  {page.title && (
                    <span className="mt-1 block truncate text-xs text-foreground-muted">
                      {page.title}
                    </span>
                  )}
                </td>
                <td className={`px-3 py-3 font-mono text-xs ${statusClass(page)}`}>
                  {page.status_code || "—"}
                  {page.fetch_class !== "ok" && (
                    <span className="block text-[11px]">{FETCH_CLASS_LABEL[page.fetch_class]}</span>
                  )}
                </td>
                <td className="px-3 py-3 text-right tabular-nums text-foreground-muted">
                  {page.word_count}
                </td>
                <td className="px-3 py-3 text-right tabular-nums text-foreground-muted">
                  {page.h1_count}
                </td>
                <td className="px-3 py-3 text-right tabular-nums text-foreground-muted">
                  {page.internal_links}
                </td>
                <td className="px-3 py-3 text-right tabular-nums text-foreground-muted">
                  {page.response_time_ms}
                </td>
                <td className="px-3 py-3 text-center text-foreground-muted">
                  {page.has_structured_data ? "da" : "—"}
                </td>
                <td className="px-3 py-3 text-right tabular-nums text-foreground">
                  {page.issue_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
