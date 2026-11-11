import Link from "next/link";
import { AnimatedHeading } from "./AnimatedHeading";
import { RevealSection } from "./RevealSection";

export function About() {
  return (
    <section id="despre" className="mx-auto max-w-7xl px-6 py-28 lg:px-8">
      <div className="grid grid-cols-1 items-center gap-14 lg:grid-cols-[0.8fr_1.2fr]">
        <RevealSection className="founder-surface">
          <div className="founder-surface__light" aria-hidden="true" />
          <div className="founder-surface__mark" aria-hidden="true">AC</div>
          <p>Tu decizi.<br /><span>Sistemul execută.</span></p>
          <span className="founder-surface__signature">Andrei · Fondator AC Media</span>
        </RevealSection>

        <RevealSection delay={0.1}>
          <AnimatedHeading
            text="Lucrezi direct cu omul din spatele sistemului."
            className="section-display"
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
