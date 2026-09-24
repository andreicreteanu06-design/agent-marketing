"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { ClipboardText, Globe, Sparkle, Warning } from "@phosphor-icons/react/dist/ssr";
import {
  analyzeSeoGeo,
  getAuditResults,
  getAuditStatus,
  getLatestAudit,
  startAudit,
  AUDIT_POLL_INTERVAL_MS,
  type ActionableSuggestion,
  type AnalysisResponse,
  type AuditResults,
  type AuditStatusResponse,
} from "@/lib/seoGeoApi";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ResultReveal } from "@/components/RevealSection";
import { AuditIssuesView } from "./AuditIssuesView";
import { AuditMetrics, AuditScores } from "./AuditMetrics";
import { AuditPagesTable } from "./AuditPagesTable";
import { displayHost, useSeoGeoSession } from "./SeoGeoSession";
import { dateTime, primaryButton } from "./ui";

/**
 * Auditul site-ului, in modulul SEO + GEO.
 *
 * Fluxul principal e AUDITUL DETERMINIST (seo_geo_agent/audit/): un crawl real
 * al domeniului, din care ies probleme verificabile - fiecare cu URL-ul afectat
 * si valorile masurate - si doua scoruri calculate din ele. Ordinea raportului
 * e cea din every-app/open-seo, fiindca asa se lucreaza: "cat de rau e" (cifrele
 * de sus) -> "ce anume e rupt" (problemele) -> "pe care pagina".
 *
 * Analiza prin LLM ramane disponibila, dar ca al treilea tab si explicit
 * marcata ca atare: e o parere peste datele masurate, nu sursa lor.
 */

type Tab = "issues" | "pages" | "ai";

/** Un raport afisat: cel tocmai rulat (se aduce singur in ecran) sau ultimul existent. */
interface ShownReport {
  report: AuditResults;
  fresh: boolean;
}

function SuggestionCard({ suggestion }: { suggestion: ActionableSuggestion }) {
  return (
    <div className="rounded-2xl border border-border-subtle bg-background-elevated p-5">
      <span className="text-xs font-semibold uppercase tracking-widest text-brand-cyan">
        {suggestion.category}
      </span>
      <p className="mt-2 text-sm leading-relaxed text-foreground-muted">{suggestion.current_issue}</p>
      <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-xl bg-background px-4 py-3 font-mono text-xs leading-relaxed text-foreground">
        {suggestion.exact_fix}
      </pre>
    </div>
  );
}

function SuggestionColumn({ title, items }: { title: string; items: ActionableSuggestion[] }) {
  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-sm font-semibold uppercase tracking-widest text-foreground-muted">{title}</h3>
      {items.length === 0 ? (
        <p className="text-sm text-foreground-muted">Nicio sugestie aici.</p>
      ) : (
        items.map((item, i) => <SuggestionCard key={`${item.category}-${i}`} suggestion={item} />)
      )}
    </div>
  );
}

function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-200">
      <Warning size={18} weight="fill" className="mt-0.5 shrink-0" />
      <p className="leading-relaxed">{children}</p>
    </div>
  );
}

export function SiteAudit() {
  const { token, me, errorMessage } = useSeoGeoSession();
  const brand = me.account.brand_name;

  const [domain, setDomain] = useState(displayHost(me.account.target_domain));
  const [status, setStatus] = useState<AuditStatusResponse | null>(null);
  const [shown, setShown] = useState<ShownReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [tab, setTab] = useState<Tab>("issues");

  // Sugestiile LLM: optionale, cerute doar cand utilizatorul deschide tabul.
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  const auditIdRef = useRef<string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Ultimul raport, ca pagina sa nu inceapa goala. Nu il suprascrie pe unul
  // pornit intre timp; o eroare aici nu blocheaza nimic - formularul merge.
  useEffect(() => {
    getLatestAudit(token)
      .then((latest) => {
        if (latest) setShown((current) => current ?? { report: latest, fresh: false });
      })
      .catch(() => undefined);
  }, [token]);

  // Oprim interogarea daca utilizatorul pleaca de pe pagina in timpul auditului.
  useEffect(
    () => () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
      auditIdRef.current = null;
    },
    []
  );

  /**
   * Interogheaza starea pana cand auditul nu mai ruleaza, apoi ia raportul.
   *
   * Bucla e scrisa iterativ, nu recursiv, exact ca sa nu avem nevoie de o
   * referinta catre ea insasi. ``auditIdRef`` e conditia de oprire: daca
   * utilizatorul porneste alt audit sau pleaca de pe pagina, bucla veche se
   * opreste singura la urmatoarea verificare si nu mai scrie in state.
   */
  const poll = useCallback(
    async (auditId: string) => {
      try {
        for (;;) {
          if (auditIdRef.current !== auditId) return;
          const next = await getAuditStatus(token, auditId);
          if (auditIdRef.current !== auditId) return;
          setStatus(next);

          if (next.status === "failed") {
            setError(next.error ?? "Auditul nu s-a putut finaliza.");
            return;
          }
          if (next.status === "completed") {
            const report = await getAuditResults(token, auditId);
            if (auditIdRef.current !== auditId) return;
            setShown({ report, fresh: true });
            return;
          }
          await new Promise<void>((resolve) => {
            pollTimerRef.current = setTimeout(resolve, AUDIT_POLL_INTERVAL_MS);
          });
        }
      } catch (err) {
        if (auditIdRef.current !== auditId) return;
        setError(errorMessage(err, "Nu am putut prelua raportul. Încearcă din nou."));
      }
    },
    [token, errorMessage]
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    setError(null);
    setShown(null);
    setAnalysis(null);
    setAnalysisError(null);
    setStatus(null);
    setTab("issues");
    setStarting(true);
    try {
      // Fara max_pages: serverul parcurge tot site-ul, pana la plafonul lui.
      const started = await startAudit(token, {
        domain: domain.trim(),
        brand: brand.trim() || undefined,
      });
      auditIdRef.current = started.audit_id;
      setStatus({
        audit_id: started.audit_id,
        status: "running",
        crawled: 0,
        queued: 0,
        max_pages: 0, // necunoscut pana la prima interogare de stare
        error: null,
      });
      void poll(started.audit_id);
    } catch (err) {
      setError(errorMessage(err, "Ceva nu a mers bine. Încearcă din nou."));
    } finally {
      setStarting(false);
    }
  }

  async function runAiSuggestions() {
    if (!shown) return;
    setAnalysisError(null);
    setAnalysing(true);
    try {
      setAnalysis(await analyzeSeoGeo(token, { domain: shown.report.domain }));
    } catch (err) {
      setAnalysisError(errorMessage(err, "Sugestiile AI nu au putut fi generate."));
    } finally {
      setAnalysing(false);
    }
  }

  const running = status?.status === "running";
  // Cat stim ca are site-ul: paginile citite plus cele descoperite, fara sa
  // depaseasca plafonul serverului. Raportat la plafon, un site de 12 pagini
  // ar sta la 12% si apoi ar sari direct la final.
  const discovered = status ? status.crawled + status.queued : 0;
  const expectedPages =
    status && status.max_pages > 0 ? Math.min(status.max_pages, discovered) : discovered;
  const progressPct =
    status && expectedPages > 0
      ? Math.min(100, Math.round((status.crawled / expectedPages) * 100))
      : 0;

  const report = shown?.report;
  const results = report ? (
    <div className="space-y-6">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-semibold text-foreground">{displayHost(report.start_url)}</h2>
          <Badge variant="success">Finalizat</Badge>
        </div>
        <p className="mt-1 text-sm text-foreground-muted">
          Audit site · {dateTime(report.summary.finished_at)}
        </p>
      </div>

      <AuditMetrics results={report} />
      <AuditScores results={report} />

      {!report.summary.completed && (
        <Notice>
          Raportul e <strong>parțial</strong>: crawl-ul s-a oprit la limita de pagini sau de
          timp. Verificările care au nevoie de harta completă a site-ului (paginile orfane) nu
          au rulat, ca să nu raporteze date lipsă drept probleme.
        </Notice>
      )}
      {report.summary.blocked_pages > 0 && (
        <Notice>
          {report.summary.blocked_pages} pagini ne-au blocat crawler-ul (protecție anti-bot). Nu
          le-am putut audita - pune user-agent-ul
          <span className="font-mono"> SeoGeoAgent-Audit </span>
          pe lista albă și rulează din nou.
        </Notice>
      )}
      {report.summary.rate_limited_pages > 0 && (
        <Notice>
          {report.summary.rate_limited_pages} pagini au răspuns 429 (prea multe cereri): site-ul
          a limitat crawler-ul. Încearcă din nou peste câteva minute.
        </Notice>
      )}

      <Card className="p-2 sm:p-4">
        <div className="flex flex-wrap gap-2 border-b border-border-subtle px-2">
          {(
            [
              ["issues", `Probleme (${report.issues.length})`],
              ["pages", `Pagini (${report.pages.length})`],
              ["ai", "Sugestii AI"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={cn(
                "-mb-px border-b-2 px-3 py-2.5 text-sm font-medium transition-colors",
                tab === key
                  ? "border-brand-cyan text-foreground"
                  : "border-transparent text-foreground-muted hover:text-foreground"
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="p-2 pt-4">
          {tab === "issues" && <AuditIssuesView issues={report.issues} />}
          {tab === "pages" && <AuditPagesTable pages={report.pages} />}
          {tab === "ai" && (
            <div className="space-y-6">
              <p className="text-sm text-foreground-muted">
                Sugestii generate de un model AI pornind de la domeniu. Sunt o interpretare, nu
                măsurători - problemele verificate rămân cele din tabul <strong>Probleme</strong>.
              </p>
              {!analysis && (
                <button
                  type="button"
                  onClick={() => void runAiSuggestions()}
                  disabled={analysing}
                  className="rounded-full border border-border-subtle px-5 py-2.5 text-sm font-medium text-foreground transition-colors hover:border-brand-cyan disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {analysing ? "Se generează..." : "Generează sugestii AI"}
                </button>
              )}
              {analysisError && (
                <p role="alert" className="rounded-xl bg-red-500/10 px-4 py-3 text-sm text-red-400">
                  {analysisError}
                </p>
              )}
              {analysis && (
                <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
                  <SuggestionColumn title="Sugestii SEO" items={analysis.seo_suggestions} />
                  <SuggestionColumn title="Sugestii GEO" items={analysis.geo_suggestions} />
                </div>
              )}
            </div>
          )}
        </div>
      </Card>
    </div>
  ) : null;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Audit site</h1>
        <p className="mt-2 max-w-2xl text-base text-foreground-muted">
          Crawlăm site-ul ca un motor de căutare și verificăm fiecare regulă pe rând - pentru
          Google (SEO) și pentru citarea de către modele AI (GEO). Fiecare problemă vine cu URL-ul
          afectat și valorile măsurate.
        </p>
      </header>

      <Card>
        <form onSubmit={handleSubmit} className="space-y-4 p-6">
          <div className="flex flex-col gap-3 sm:flex-row">
            <label htmlFor="audit-domain" className="sr-only">
              Domeniu
            </label>
            <div className="relative flex-1">
              <Globe
                size={16}
                className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-foreground-muted"
              />
              <input
                id="audit-domain"
                type="text"
                value={domain}
                onChange={(event) => setDomain(event.target.value)}
                placeholder="exemplu.ro"
                required
                disabled={running || starting}
                className="h-11 w-full rounded-full border border-border-subtle bg-background pl-10 pr-4 text-sm text-foreground outline-none transition-colors placeholder:text-foreground-muted/60 focus:border-brand-cyan disabled:cursor-not-allowed disabled:opacity-60"
              />
            </div>
            <Button
              type="submit"
              disabled={running || starting}
              className={cn(primaryButton, "h-11 gap-2 px-5")}
            >
              <Sparkle size={16} weight="fill" />
              {running || starting ? "Se auditează..." : "Rulează auditul"}
            </Button>
          </div>

          <p className="text-xs leading-relaxed text-foreground-muted">
            Parcurgem automat tot site-ul: robots.txt, sitemap și fiecare pagină. Brandul pentru
            verificările GEO:{" "}
            <span className="text-foreground">{brand || "dedus din domeniu"}</span> ·{" "}
            <Link href="/cont/seo-geo/setari" className="text-brand-cyan hover:underline">
              schimbă în Setări
            </Link>
          </p>

          {running && status && (
            <div className="space-y-2">
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-background">
                <div
                  className="h-full rounded-full bg-brand-cyan transition-[width] duration-500"
                  style={{ width: `${Math.max(progressPct, 4)}%` }}
                />
              </div>
              <p className="text-xs text-foreground-muted">
                {status.crawled} pagini citite, {status.queued} în coadă.
              </p>
            </div>
          )}

          {error && (
            <p role="alert" className="rounded-xl bg-red-500/10 px-4 py-3 text-sm text-red-400">
              {error}
            </p>
          )}
        </form>
      </Card>

      {shown?.fresh && results && (
        <ResultReveal key={shown.report.audit_id} className="space-y-6">
          {results}
        </ResultReveal>
      )}
      {shown && !shown.fresh && results}

      {!shown && !running && !starting && (
        <Card className="flex flex-col items-center gap-3 px-6 py-12 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-blue/15 text-brand-cyan">
            <ClipboardText size={22} weight="duotone" />
          </span>
          <p className="font-medium text-foreground">Niciun audit încă</p>
          <p className="max-w-md text-sm text-foreground-muted">
            Pornește primul audit mai sus. Durează de obicei sub un minut și îți arată exact ce
            pagini au probleme și cum le repari.
          </p>
        </Card>
      )}
    </div>
  );
}
