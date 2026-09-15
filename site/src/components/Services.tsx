import { ChartLineUp, PaintBrush, Robot } from "@phosphor-icons/react/dist/ssr";
import { RevealSection } from "./RevealSection";
import { SpotlightCard } from "./SpotlightCard";

export function Services() {
  return (
    <section id="servicii" className="mx-auto max-w-7xl px-6 py-28 lg:px-8">
      <RevealSection>
        <h2 className="max-w-xl text-3xl font-bold tracking-tight text-foreground md:text-4xl">
          Trei servicii, o singură logică din spate.
        </h2>
        <p className="mt-4 max-w-xl text-base leading-relaxed text-foreground-muted">
          PPC, web design și automatizări nu sunt echipe separate. Tot ce
          construiesc pentru un client pornește de la datele reale ale
          campaniilor lui.
        </p>
      </RevealSection>

      <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-2">
        <RevealSection delay={0.05} className="md:row-span-2">
          <SpotlightCard className="h-full rounded-3xl border border-border-subtle bg-background-elevated p-8">
            <div className="flex h-full flex-col">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-blue/15 text-brand-cyan transition-transform duration-300 group-hover:-rotate-6 group-hover:scale-110">
                <ChartLineUp size={22} weight="duotone" />
              </div>
              <h3 className="mt-6 text-xl font-semibold text-foreground">
                Management PPC cu agent AI
              </h3>
              <p className="mt-3 leading-relaxed text-foreground-muted">
                Alocare de buget prin Thompson Sampling, dimensionare Kelly
                Criterion după ROAS și monitorizare a oboselii creative, pe
                Google, Meta și TikTok Ads.
              </p>
              <p className="mt-4 leading-relaxed text-foreground-muted">
                Fiecare modificare trece printr-o poartă de aprobare umană
                înainte să ajungă pe cont. Nimic nu se schimbă singur, fără
                confirmarea ta.
              </p>
              <div className="mt-auto pt-8">
                <a
                  href="/creeaza-cont"
                  className="text-sm font-semibold text-brand-cyan hover:underline"
                >
                  Dă-i acces agentului AI
                </a>
              </div>
            </div>
          </SpotlightCard>
        </RevealSection>

        <RevealSection delay={0.1}>
          <SpotlightCard className="rounded-3xl border border-border-subtle bg-background-elevated p-8">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-blue/15 text-brand-cyan transition-transform duration-300 group-hover:-rotate-6 group-hover:scale-110">
              <PaintBrush size={22} weight="duotone" />
            </div>
            <h3 className="mt-6 text-xl font-semibold text-foreground">Web design</h3>
            <p className="mt-3 leading-relaxed text-foreground-muted">
              Site-uri rapide, construite pentru conversie. Fiecare pagină
              susține direct campaniile de PPC, nu lucrează separat de ele.
            </p>
          </SpotlightCard>
        </RevealSection>

        <RevealSection delay={0.15}>
          <SpotlightCard className="rounded-3xl border border-border-subtle bg-background-elevated p-8">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-blue/15 text-brand-cyan transition-transform duration-300 group-hover:-rotate-6 group-hover:scale-110">
              <Robot size={22} weight="duotone" />
            </div>
            <h3 className="mt-6 text-xl font-semibold text-foreground">
              Automatizări AI
            </h3>
            <p className="mt-3 leading-relaxed text-foreground-muted">
              Lead-uri răspunse în minute, nu zile. Facturi restante urmărite
              automat, nu uitate într-un Excel. Fluxuri construite pe măsura
              departamentului tău, nu un șablon generic.
            </p>
          </SpotlightCard>
        </RevealSection>
      </div>
    </section>
  );
}
