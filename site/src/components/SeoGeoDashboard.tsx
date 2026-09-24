"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { MagnifyingGlass, Sparkle, Warning } from "@phosphor-icons/react/dist/ssr";
import { getToken, clearToken } from "@/lib/auth";
import {
  analyzeSeoGeo,
  getAuditResults,
  getAuditStatus,
  startAudit,
  SeoGeoApiError,
  AUDIT_POLL_INTERVAL_MS,
  type ActionableSuggestion,
  type AnalysisResponse,
  type AuditResults,
  type AuditStatusResponse,
} from "@/lib/seoGeoApi";
import { ResultReveal, RevealSection } from "./RevealSection";
import { CircleProgress } from "./ui/circle-progress";
import { AuditIssuesView } from "./seo-geo/AuditIssuesView";
import { AuditPagesTable } from "./seo-geo/AuditPagesTable";

/**
 * Unealta SEO+GEO a contului.
 *
 * Fluxul principal e AUDITUL DETERMINIST (seo_geo_agent/audit/): un crawl real
 * al domeniului, din care ies probleme verificabile - fiecare cu URL-ul afectat
 * si valorile masurate - si doua scoruri calculate din ele. Structura
 * (scoruri -> rezumat -> probleme grupate pe severitate -> tabel de pagini) e
 * cea din every-app/open-seo, fiindca acolo e ordinea in care se lucreaza:
 * "cat de rau e" -> "ce anume e rupt" -> "pe care pagina".
 *
 * Analiza prin LLM ramane disponibila, dar ca al treilea tab si explicit
 * marcata ca atare: e o parere peste datele masurate, nu sursa lor.
 */

const SEO_COLOR = (ratio: number): string => {
  if (ratio >= 0.7) return "var(--brand-cyan)";
  if (ratio >= 0.4) return "#f5a623";
  return "#f5424a";
};

type Tab = "issues" | "pages" | "ai";

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

function SummaryStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-border-subtle bg-background px-4 py-3">
      <span className="block text-xs uppercase tracking-wider text-foreground-muted">{label}</span>
      <span className="mt-1 block text-lg font-semibold tabular-nums text-foreground">{value}</span>
    </div>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-200">
      <Warning size={18} weight="fill" className="mt-0.5 shrink-0" />
      <p className="leading-relaxed">{children}</p>
    </div>
  );
}

export function SeoGeoDashboard() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(true);

  const [domain, setDomain] = useState("");
  const [brand, setBrand] = useState("");

  const [status, setStatus] = useState<AuditStatusResponse | null>(null);
  const [results, setResults] = useState<AuditResults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [tab, setTab] = useState<Tab>("issues");

  // Sugestiile LLM: optionale, cerute doar cand utilizatorul deschide tabul.
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  const auditIdRef = useRef<string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // La fel ca AccountDashboard: verificarea tokenului e client-side (nu exista
  // inca sesiune de server), o singura data la montare.
  useEffect(() => {
    const existing = getToken();
    if (!existing) {
      router.replace("/login");
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(existing);
    setCheckingAuth(false);
  }, [router]);

  // Oprim interogarea daca utilizatorul pleaca de pe pagina in timpul auditului.
  useEffect(
    () => () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
      auditIdRef.current = null;
    },
    []
  );

  const handleApiError = useCallback(
    (err: unknown, fallback: string): string => {
      if (err instanceof SeoGeoApiError && err.status === 401) {
        clearToken();
        router.replace("/login");
        return "";
      }
      return err instanceof SeoGeoApiError ? err.message : fallback;
    },
    [router]
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
    async (activeToken: string, auditId: string) => {
      try {
        for (;;) {
          if (auditIdRef.current !== auditId) return;
          const next = await getAuditStatus(activeToken, auditId);
          if (auditIdRef.current !== auditId) return;
          setStatus(next);

          if (next.status === "failed") {
            setError(next.error ?? "Auditul nu s-a putut finaliza.");
            return;
          }
          if (next.status === "completed") {
            const report = await getAuditResults(activeToken, auditId);
            if (auditIdRef.current !== auditId) return;
            setResults(report);
            return;
          }
          await new Promise<void>((resolve) => {
            pollTimerRef.current = setTimeout(resolve, AUDIT_POLL_INTERVAL_MS);
          });
        }
      } catch (err) {
        if (auditIdRef.current !== auditId) return;
        setError(handleApiError(err, "Nu am putut prelua raportul. Încearcă din nou."));
      }
    },
    [handleApiError]
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    setError(null);
    setResults(null);
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
      void poll(token, started.audit_id);
    } catch (err) {
      setError(handleApiError(err, "Ceva nu a mers bine. Încearcă din nou."));
    } finally {
      setStarting(false);
    }
  }

  async function runAiSuggestions() {
    if (!token || !results) return;
    setAnalysisError(null);
    setAnalysing(true);
    try {
      setAnalysis(await analyzeSeoGeo(token, { domain: results.domain }));
    } catch (err) {
      setAnalysisError(handleApiError(err, "Sugestiile AI nu au putut fi generate."));
    } finally {
      setAnalysing(false);
    }
  }

  if (checkingAuth) {
    return <p className="text-sm text-foreground-muted">Se încarcă...</p>;
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

  return (
    <div className="space-y-8">
      <RevealSection>
        <form
          onSubmit={handleSubmit}
          className="space-y-5 rounded-3xl border border-border-subtle bg-background-elevated p-6 md:p-8"
        >
          <div className="flex items-center gap-2">
            <MagnifyingGlass size={16} className="text-brand-cyan" />
            <h2 className="text-lg font-semibold text-foreground">Audit SEO + GEO</h2>
          </div>
          <p className="text-sm text-foreground-muted">
            Îți crawlăm site-ul ca un motor de căutare: citim robots.txt și
            sitemap-ul, descărcăm automat toate paginile și verificăm fiecare
            regulă pe rând. Primești problemele exacte, cu URL-ul și valorile
            măsurate - nu păreri.
          </p>

          <div className="flex flex-col gap-2">
            <label htmlFor="audit-domain" className="text-sm font-medium text-foreground">
              Domeniu
            </label>
            <input
              id="audit-domain"
              type="text"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="exemplu.ro"
              required
              disabled={running || starting}
              className="rounded-xl border border-border-subtle bg-background px-4 py-3 text-sm text-foreground placeholder:text-foreground-muted/60 outline-none transition-colors focus:border-brand-cyan disabled:cursor-not-allowed disabled:opacity-60"
            />
          </div>

          <div className="flex flex-col gap-2">
            <label htmlFor="audit-brand" className="text-sm font-medium text-foreground">
              Numele brandului <span className="text-foreground-muted">(opțional)</span>
            </label>
            <p className="text-xs text-foreground-muted">
              Folosit la verificarea GEO de entity salience - cât de des apare
              brandul explicit în text. Gol înseamnă că îl deducem din domeniu.
            </p>
            <input
              id="audit-brand"
              type="text"
              value={brand}
              onChange={(e) => setBrand(e.target.value)}
              placeholder="Ex. AC Media Marketing"
              disabled={running || starting}
              className="rounded-xl border border-border-subtle bg-background px-4 py-3 text-sm text-foreground placeholder:text-foreground-muted/60 outline-none transition-colors focus:border-brand-cyan disabled:cursor-not-allowed disabled:opacity-60"
            />
          </div>

          {error && (
            <p role="alert" className="rounded-xl bg-red-500/10 px-4 py-3 text-sm text-red-400">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={running || starting}
            className="flex w-full items-center justify-center gap-2 rounded-full bg-brand-blue px-6 py-3.5 text-sm font-semibold text-white transition-transform hover:scale-[1.01] active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Sparkle size={16} weight="fill" />
            {running || starting ? "Se auditează..." : "Rulează auditul"}
          </button>

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
        </form>
      </RevealSection>

      {results && (
        <ResultReveal className="space-y-8">
          <div className="flex flex-col items-center justify-center gap-10 rounded-3xl border border-border-subtle bg-background-elevated p-8 sm:flex-row sm:gap-16">
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

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <SummaryStat label="Pagini" value={results.summary.pages_crawled} />
            <SummaryStat label="Critice" value={results.summary.critical_count} />
            <SummaryStat label="Avertismente" value={results.summary.warning_count} />
            <SummaryStat label="Informative" value={results.summary.info_count} />
            <SummaryStat label="robots.txt" value={results.summary.robots_txt_found ? "da" : "nu"} />
            <SummaryStat label="llms.txt" value={results.summary.llms_txt_found ? "da" : "nu"} />
          </div>

          {!results.summary.completed && (
            <Notice>
              Raportul e <strong>parțial</strong>: crawl-ul s-a oprit la limita de
              pagini sau de timp. Verificările care au nevoie de harta completă a
              site-ului (paginile orfane) nu au rulat, ca să nu raporteze date
              lipsă drept probleme.
            </Notice>
          )}

          {results.summary.blocked_pages > 0 && (
            <Notice>
              {results.summary.blocked_pages} pagini ne-au blocat crawler-ul
              (protecție anti-bot). Nu le-am putut audita - pune user-agent-ul
              <span className="font-mono"> SeoGeoAgent-Audit </span>
              pe lista albă și rulează din nou.
            </Notice>
          )}

          {results.summary.rate_limited_pages > 0 && (
            <Notice>
              {results.summary.rate_limited_pages} pagini au răspuns 429 (prea
              multe cereri): site-ul a limitat crawler-ul. Încearcă din nou peste
              câteva minute.
            </Notice>
          )}

          <div className="flex flex-wrap gap-2 border-b border-border-subtle">
            {(
              [
                ["issues", `Probleme (${results.issues.length})`],
                ["pages", `Pagini (${results.pages.length})`],
                ["ai", "Sugestii AI"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
                  tab === key
                    ? "border-brand-cyan text-foreground"
                    : "border-transparent text-foreground-muted hover:text-foreground"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === "issues" && <AuditIssuesView issues={results.issues} />}
          {tab === "pages" && <AuditPagesTable pages={results.pages} />}
          {tab === "ai" && (
            <div className="space-y-6">
              <p className="text-sm text-foreground-muted">
                Sugestii generate de un model AI pornind de la domeniu. Sunt o
                interpretare, nu măsurători - problemele verificate rămân cele din
                tabul <strong>Probleme</strong>.
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
        </ResultReveal>
      )}
    </div>
  );
}
