"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { MagnifyingGlass, Sparkle } from "@phosphor-icons/react/dist/ssr";
import { getToken, clearToken } from "@/lib/auth";
import {
  analyzeSeoGeo,
  SeoGeoApiError,
  type ActionableSuggestion,
  type AnalysisResponse,
} from "@/lib/seoGeoApi";
import { RevealSection } from "./RevealSection";
import { CircleProgress } from "./ui/circle-progress";

const SEO_COLOR = (ratio: number): string => {
  if (ratio >= 0.7) return "var(--brand-cyan)";
  if (ratio >= 0.4) return "#f5a623";
  return "#f5424a";
};

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
        <p className="text-sm text-foreground-muted">Nicio sugestie - raportul nu arată probleme aici.</p>
      ) : (
        items.map((item, i) => <SuggestionCard key={`${item.category}-${i}`} suggestion={item} />)
      )}
    </div>
  );
}

/**
 * Unealta premium SEO+GEO - trimite domeniul + rapoartele lipite catre
 * seo_geo_agent (agent AI separat, vezi lib/seoGeoApi.ts) si arata scorurile
 * + sugestiile primite. Acelasi tipar de protectie ca AccountDashboard: fara
 * token, redirectioneaza spre /login (verificat client-side, nu exista inca
 * sesiune de server).
 */
export function SeoGeoDashboard() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(true);

  const [domain, setDomain] = useState("");
  const [clientReports, setClientReports] = useState("");
  const [targetAudience, setTargetAudience] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResponse | null>(null);

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
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCheckingAuth(false);
  }, [router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    setError(null);
    setResult(null);
    setSubmitting(true);
    try {
      const response = await analyzeSeoGeo(token, {
        domain: domain.trim(),
        client_reports: clientReports.trim(),
        target_audience: targetAudience.trim() || undefined,
      });
      setResult(response);
    } catch (err) {
      if (err instanceof SeoGeoApiError && err.status === 401) {
        clearToken();
        router.replace("/login");
        return;
      }
      setError(
        err instanceof SeoGeoApiError ? err.message : "Ceva nu a mers bine. Încearcă din nou."
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (checkingAuth) {
    return <p className="text-sm text-foreground-muted">Se încarcă...</p>;
  }

  return (
    <div className="space-y-8">
      <RevealSection>
        <form
          onSubmit={handleSubmit}
          className="space-y-5 rounded-3xl border border-border-subtle bg-background-elevated p-6 md:p-8"
        >
          <div className="flex items-center gap-2">
            <MagnifyingGlass size={16} className="text-brand-cyan" />
            <h2 className="text-lg font-semibold text-foreground">Analiză SEO + GEO</h2>
          </div>
          <p className="text-sm text-foreground-muted">
            Lipește rapoarte brute din Ahrefs, Semrush sau Google Search Console -
            sugestiile sunt generate strict din datele reale de mai jos, nu din
            presupuneri generice.
          </p>

          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-foreground">Domeniu</label>
            <input
              type="text"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="exemplu.ro"
              required
              disabled={submitting}
              className="rounded-xl border border-border-subtle bg-background px-4 py-3 text-sm text-foreground placeholder:text-foreground-muted/60 outline-none transition-colors focus:border-brand-cyan disabled:cursor-not-allowed disabled:opacity-60"
            />
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-foreground">Rapoarte client</label>
            <textarea
              value={clientReports}
              onChange={(e) => setClientReports(e.target.value)}
              placeholder="Lipește aici text din Ahrefs, Semrush, GSC etc."
              required
              rows={8}
              disabled={submitting}
              className="rounded-xl border border-border-subtle bg-background px-4 py-3 font-mono text-sm text-foreground placeholder:text-foreground-muted/60 outline-none transition-colors focus:border-brand-cyan disabled:cursor-not-allowed disabled:opacity-60"
            />
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-foreground">
              Public țintă <span className="text-foreground-muted">(opțional)</span>
            </label>
            <input
              type="text"
              value={targetAudience}
              onChange={(e) => setTargetAudience(e.target.value)}
              placeholder="Ex. proprietari de magazine online, B2B SaaS..."
              disabled={submitting}
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
            disabled={submitting}
            className="flex w-full items-center justify-center gap-2 rounded-full bg-brand-blue px-6 py-3.5 text-sm font-semibold text-white transition-transform hover:scale-[1.01] active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Sparkle size={16} weight="fill" />
            {submitting ? "Se analizează..." : "Analizează"}
          </button>
        </form>
      </RevealSection>

      {result && (
        <RevealSection className="space-y-10">
          <div className="flex flex-col items-center justify-center gap-10 rounded-3xl border border-border-subtle bg-background-elevated p-8 sm:flex-row sm:gap-16">
            <CircleProgress value={result.seo_score} label="SEO" getColor={SEO_COLOR} />
            <CircleProgress value={result.geo_score} label="GEO" useGradient />
          </div>

          <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
            <SuggestionColumn title="Sugestii SEO" items={result.seo_suggestions} />
            <SuggestionColumn title="Sugestii GEO" items={result.geo_suggestions} />
          </div>
        </RevealSection>
      )}
    </div>
  );
}
