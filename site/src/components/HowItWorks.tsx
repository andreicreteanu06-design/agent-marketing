"use client";

import { useRef } from "react";
import { RevealSection } from "./RevealSection";
import { ScrollLine } from "./ScrollLine";

const STEPS = [
  {
    n: "01",
    title: "Conectezi conturile",
    body: "Google Ads, Meta Ads, TikTok Ads. Datele tale de performanță, nu un cont demo.",
  },
  {
    n: "02",
    title: "Agentul propune",
    body: "Recalculează alocarea de buget și semnalează reclamele obosite, zilnic.",
  },
  {
    n: "03",
    title: "Aprobi",
    body: "Vezi exact ce se schimbă și de ce, înainte să confirmi orice modificare.",
  },
  {
    n: "04",
    title: "Rulează și se ajustează",
    body: "Bugetul curge spre campania cu șanse mai mari, in fiecare zi de acum inainte.",
  },
];

export function HowItWorks() {
  const trackRef = useRef<HTMLDivElement>(null);

  return (
    <section id="cum-functioneaza" className="mx-auto max-w-7xl px-6 py-28 lg:px-8">
      <RevealSection>
        <h2 className="max-w-xl text-3xl font-bold tracking-tight text-foreground md:text-4xl">
          Cum funcționează, fără cutie neagră.
        </h2>
      </RevealSection>

      <div ref={trackRef} className="relative mt-14 grid grid-cols-1 gap-10 md:grid-cols-4 md:gap-6">
        <ScrollLine trackRef={trackRef} />
        {STEPS.map((step, i) => (
          <RevealSection key={step.n} delay={i * 0.08} className="relative">
            <span className="font-mono text-xs text-brand-cyan">{step.n}</span>
            <h3 className="mt-3 text-lg font-semibold text-foreground">{step.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-foreground-muted">
              {step.body}
            </p>
          </RevealSection>
        ))}
      </div>
    </section>
  );
}
