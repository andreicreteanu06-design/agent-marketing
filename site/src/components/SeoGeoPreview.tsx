import Link from "next/link";
import { LockSimple, MagnifyingGlass } from "@phosphor-icons/react/dist/ssr";
import { AnimatedHeading } from "./AnimatedHeading";
import { RevealSection } from "./RevealSection";
import { CircleProgress } from "./ui/circle-progress";

function SkeletonIssueRow({ severity, label }: { severity: string; label: string }) {
  return (
    <div className="flex items-center gap-3 border-t border-border-subtle px-4 py-3 first:border-t-0">
      <span className={`h-2 w-2 shrink-0 rounded-full ${severity}`} />
      <span className="flex-1 text-sm text-foreground-muted">{label}</span>
      <span className="h-3 w-6 animate-pulse rounded-full bg-foreground-muted/15" />
    </div>
  );
}

/**
 * Teaser public pentru unealta reala (SeoGeoDashboard, gated in /cont/seo-geo)
 * - aceeasi forma vizuala ca raportul de audit (cele doua inele CircleProgress,
 * rezumatul si lista de probleme grupate pe severitate), dar dezactivata si
 * "neincarcata". Lacatul de deasupra duce la /creeaza-cont - nimic de aici nu
 * trimite vreo cerere catre seo_geo_agent (spre deosebire de pagina reala).
 */
export function SeoGeoPreview() {
  return (
    <section className="mx-auto max-w-7xl px-6 py-28 lg:px-8">
      <RevealSection>
        <AnimatedHeading
          text="Un audit real al site-ului tău, nu o părere."
          className="max-w-xl text-3xl font-bold tracking-tight text-foreground md:text-4xl"
        />
        <p className="mt-4 max-w-xl text-base leading-relaxed text-foreground-muted">
          Îți crawlăm site-ul ca un motor de căutare - robots.txt, sitemap,
          fiecare pagină - și verificăm regulile una câte una. Primești
          problemele exacte, cu URL-ul și valorile măsurate: titluri lipsă,
          linkuri rupte, conținut duplicat, plus partea GEO (cât de citabil ești
          de ChatGPT, Perplexity și AI Overviews).
        </p>
      </RevealSection>

      <RevealSection delay={0.1} className="relative mt-12">
        <div
          aria-hidden
          className="pointer-events-none select-none space-y-8 rounded-3xl border border-border-subtle bg-background-elevated p-6 opacity-40 blur-[1px] md:p-8"
        >
          <div className="flex items-center gap-2">
            <MagnifyingGlass size={16} className="text-brand-cyan" />
            <h3 className="text-lg font-semibold text-foreground">Audit SEO + GEO</h3>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-[2fr_1fr]">
            <div className="h-12 rounded-xl border border-border-subtle bg-background" />
            <div className="h-12 rounded-xl border border-border-subtle bg-background" />
          </div>

          <div className="flex flex-col items-center justify-center gap-10 py-4 sm:flex-row sm:gap-16">
            <CircleProgress value={0} label="SEO" />
            <CircleProgress value={0} label="GEO" useGradient />
          </div>

          <div className="overflow-hidden rounded-2xl border border-border-subtle">
            <SkeletonIssueRow severity="bg-red-500" label="Link intern rupt" />
            <SkeletonIssueRow severity="bg-amber-400" label="Titlu duplicat" />
            <SkeletonIssueRow severity="bg-amber-400" label="Pagina nu are date structurate" />
            <SkeletonIssueRow severity="bg-foreground-muted/40" label="Meta description prea scurtă" />
          </div>
        </div>

        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 rounded-3xl bg-background/50 p-8 text-center backdrop-blur-sm">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-blue/15 text-brand-cyan">
            <LockSimple size={26} weight="fill" />
          </div>
          <p className="max-w-xs text-sm font-medium text-foreground">
            Creează cont gratuit ca să rulezi un audit real pentru domeniul tău.
          </p>
          <Link
            href="/creeaza-cont"
            className="rounded-full bg-brand-blue px-6 py-3 text-sm font-semibold text-white transition-transform hover:scale-[1.03] active:scale-[0.98]"
          >
            Creează cont
          </Link>
        </div>
      </RevealSection>
    </section>
  );
}
