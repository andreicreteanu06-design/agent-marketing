"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { Icon } from "@phosphor-icons/react";
import {
  CaretDown,
  CaretRight,
  ChartLineUp,
  CheckCircle,
  ClipboardText,
  Globe,
  MagnifyingGlass,
} from "@phosphor-icons/react/dist/ssr";
import { getIntegrations, type IntegrationsStatus } from "@/lib/api";
import { getLatestAudit, type AuditResults, type IssueSeverity } from "@/lib/seoGeoApi";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { IntegrationSummaryCard } from "./Integrations";
import { displayHost, useSeoGeoSession } from "./SeoGeoSession";
import { countLabel, outlineButton, primaryButton, shortDate } from "./ui";

const SEVERITY_DOT: Record<IssueSeverity, string> = {
  critical: "bg-red-500",
  warning: "bg-amber-400",
  info: "bg-foreground-muted/50",
};

/** Cate probleme arata cardul de audit - restul sunt la un click, in pagina auditului. */
const TOP_ISSUES = 5;

interface Step {
  title: string;
  description: string;
  href: string;
  icon: Icon;
  done: boolean;
}

function StepRow({ step }: { step: Step }) {
  const StepIcon = step.icon;
  return (
    <Link
      href={step.href}
      className="group flex items-center gap-4 border-t border-border-subtle px-6 py-4 transition-colors first:border-t-0 hover:bg-white/[0.02]"
    >
      <span
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-border-subtle",
          step.done ? "text-emerald-400" : "text-foreground-muted group-hover:text-brand-cyan"
        )}
      >
        {step.done ? <CheckCircle size={18} weight="fill" /> : <StepIcon size={18} />}
      </span>
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            "block text-sm font-medium",
            step.done ? "text-foreground-muted line-through decoration-foreground-muted/40" : "text-foreground"
          )}
        >
          {step.title}
        </span>
        <span className="block text-sm text-foreground-muted">{step.description}</span>
      </span>
      <CaretRight size={16} className="shrink-0 text-foreground-muted transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
}

function GetStarted({ steps }: { steps: Step[] }) {
  const [showDone, setShowDone] = useState(false);
  const open = steps.filter((step) => !step.done);
  const done = steps.filter((step) => step.done);

  return (
    <Card>
      <CardHeader className="block">
        <CardTitle className="text-lg">Primii pași</CardTitle>
        <CardDescription>
          {open.length > 0
            ? "Configurează site-ul, rulează primul audit și conectează-ți conturile Google."
            : "Totul e configurat. Agentul lucrează cu datele reale ale site-ului."}
        </CardDescription>
      </CardHeader>
      <div>
        {open.map((step) => (
          <StepRow key={step.title} step={step} />
        ))}
        {done.length > 0 && (
          <>
            <button
              type="button"
              onClick={() => setShowDone((value) => !value)}
              aria-expanded={showDone}
              className={cn(
                "flex w-full items-center gap-2 px-6 py-3.5 text-left text-sm text-foreground-muted transition-colors hover:text-foreground",
                open.length > 0 && "border-t border-border-subtle"
              )}
            >
              <CheckCircle size={16} weight="fill" className="text-emerald-400" />
              <span className="flex-1">
                {done.length === 1 ? "1 pas finalizat" : `${done.length} pași finalizați`}
              </span>
              <CaretDown size={14} className={cn("transition-transform", showDone && "rotate-180")} />
            </button>
            {showDone && done.map((step) => <StepRow key={step.title} step={step} />)}
          </>
        )}
      </div>
    </Card>
  );
}

function AuditSummaryCard({ audit, error }: { audit: AuditResults | null | undefined; error: string | null }) {
  const detailsLink = cn(buttonVariants({ variant: "outline" }), outlineButton);
  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-blue/15 text-brand-cyan">
            <ClipboardText size={20} weight="duotone" />
          </span>
          <CardTitle>Audit site</CardTitle>
        </div>
        {audit && (
          <Link href="/cont/seo-geo/audit" className="shrink-0 text-sm font-medium text-brand-cyan hover:underline">
            Vezi detalii
          </Link>
        )}
      </CardHeader>

      <CardContent className="flex-1">
        {audit === undefined && !error && <CardDescription>Se încarcă...</CardDescription>}
        {error && <p className="text-sm text-amber-200">{error}</p>}
        {audit === null && !error && (
          <CardDescription>
            Nu ai rulat încă niciun audit. Durează de obicei sub un minut și îți arată exact ce
            pagini au probleme.
          </CardDescription>
        )}
        {audit && audit.issues.length === 0 && (
          <CardDescription>Nicio problemă găsită la paginile auditate.</CardDescription>
        )}
        {audit && audit.issues.length > 0 && (
          <ul className="space-y-2.5">
            {audit.issues.slice(0, TOP_ISSUES).map((issue) => (
              <li key={issue.issue_type} className="flex items-center gap-3 text-sm">
                <span className={cn("h-2 w-2 shrink-0 rounded-full", SEVERITY_DOT[issue.severity])} />
                <span className="min-w-0 flex-1 truncate text-foreground">{issue.title}</span>
                <span className="shrink-0 tabular-nums text-foreground-muted">
                  {countLabel(issue.count, "pagină", "pagini")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>

      <CardFooter className="justify-between">
        {audit ? (
          <p className="text-xs text-foreground-muted">
            {displayHost(audit.start_url)} · {countLabel(audit.summary.pages_crawled, "pagină", "pagini")}{" "}
            crawlate · {shortDate(audit.summary.finished_at)} · SEO {audit.seo.score} · GEO{" "}
            {audit.geo.score}
          </p>
        ) : (
          <Link href="/cont/seo-geo/audit" className={cn(buttonVariants(), primaryButton, "inline-flex")}>
            Rulează primul audit
          </Link>
        )}
        {audit && (
          <Link href="/cont/seo-geo/audit" className={detailsLink}>
            Rulează din nou
          </Link>
        )}
      </CardFooter>
    </Card>
  );
}

export function SeoGeoOverview() {
  const { token, me, errorMessage } = useSeoGeoSession();
  const [integrations, setIntegrations] = useState<IntegrationsStatus | null>(null);
  const [integrationsError, setIntegrationsError] = useState<string | null>(null);
  // undefined = inca se incarca; null = nu exista niciun audit terminat.
  const [audit, setAudit] = useState<AuditResults | null | undefined>(undefined);
  const [auditError, setAuditError] = useState<string | null>(null);

  useEffect(() => {
    getIntegrations(token)
      .then(setIntegrations)
      .catch((err: unknown) =>
        setIntegrationsError(errorMessage(err, "Nu am putut încărca integrările."))
      );
    getLatestAudit(token)
      .then(setAudit)
      .catch((err: unknown) =>
        setAuditError(errorMessage(err, "Serverul de audit nu răspunde acum."))
      );
  }, [token, errorMessage]);

  const host = displayHost(me.account.target_domain);
  const steps: Step[] = [
    {
      title: "Setează site-ul și brandul",
      description: "Domeniul pe care îl auditezi și pe care îl urmărește agentul.",
      href: "/cont/seo-geo/setari",
      icon: Globe,
      done: Boolean(me.account.target_domain),
    },
    {
      title: "Rulează un audit al site-ului",
      description: "Crawl real: indexare, meta tag-uri, link-uri rupte, pregătire pentru AI.",
      href: "/cont/seo-geo/audit",
      icon: ClipboardText,
      done: Boolean(audit),
    },
    {
      title: "Conectează Google Search Console",
      description: "Căutările reale din Google care îți aduc vizitatori.",
      href: "/cont/seo-geo/integrari",
      icon: MagnifyingGlass,
      done: Boolean(integrations?.gsc.connected && integrations.gsc.property_id),
    },
    {
      title: "Conectează Google Analytics 4",
      description: "Ce fac vizitatorii după ce ajung pe site.",
      href: "/cont/seo-geo/integrari",
      icon: ChartLineUp,
      done: Boolean(integrations?.ga4.connected && integrations.ga4.property_id),
    },
  ];

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Privire de ansamblu</h1>
        <p className="mt-2 max-w-2xl text-base text-foreground-muted">
          {host
            ? `Cum stă ${host} în Google și în răspunsurile modelelor AI.`
            : "Cum stă site-ul tău în Google și în răspunsurile modelelor AI."}
        </p>
      </header>

      <GetStarted steps={steps} />

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <AuditSummaryCard audit={audit} error={auditError} />
        {integrationsError && <p className="text-sm text-red-400">{integrationsError}</p>}
        {integrations &&
          (["gsc", "ga4"] as const).map((name) => (
            <IntegrationSummaryCard
              key={name}
              name={name}
              state={integrations[name]}
              oauthConfigured={integrations.oauth_configured}
            />
          ))}
      </div>
    </div>
  );
}
