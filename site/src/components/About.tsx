import Link from "next/link";
import { AnimatedHeading } from "./AnimatedHeading";
import { RevealSection } from "./RevealSection";
import { AsciiArt } from "./ui/robot-human";

export function About() {
  return (
    <section id="despre" className="mx-auto max-w-7xl px-6 py-28 lg:px-8">
      <div className="grid grid-cols-1 items-center gap-14 lg:grid-cols-[0.8fr_1.2fr]">
        <RevealSection className="relative aspect-square w-full max-w-sm overflow-hidden rounded-3xl border border-border-subtle bg-background-elevated">
          {/* Robot + om, animatie ASCII (21st.dev) - potrivita tematic cu
              "nu vinzi unei agentii, vorbesti cu cine scrie codul": omul care
              scrie codul si agentul AI pe care il construieste, unul langa
              altul, nu unul in locul celuilalt. */}
          <AsciiArt className="absolute inset-0 h-full w-full opacity-90" />
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "linear-gradient(to top, var(--background-elevated) 0%, transparent 35%)",
            }}
          />
        </RevealSection>

        <RevealSection delay={0.1}>
          <AnimatedHeading
            text="Nu vinzi unei agenții. Vorbești cu cine scrie codul."
            className="text-3xl font-bold tracking-tight text-foreground md:text-4xl"
          />
          <div className="mt-6 space-y-4 text-base leading-relaxed text-foreground-muted">
            <p>
              Sunt Andrei, student la Academia de Studii Economice, secția
              Marketing, și construiesc singur sistemul din spatele AC Media.
              Alocarea de buget, monitorizarea oboselii reclamelor și
              regulile de aprobare sunt cod scris de mine, pe care îl pot
              explica linie cu linie oricărui client, nu un abonament
              revândut la un SaaS străin.
            </p>
            <p>
              Prefer o discuție directă unui formular de contact anonim.
              Dacă vrei să știi exact ce se întâmplă cu bugetul tău de
              reclame, întreabă-mă direct.
            </p>
          </div>
          <Link
            href="/#programeaza"
            className="mt-8 inline-block text-sm font-semibold text-brand-cyan hover:underline"
          >
            Hai să vorbim
          </Link>
        </RevealSection>
      </div>
    </section>
  );
}
