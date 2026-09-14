"use client";

import { motion } from "motion/react";
import { ArrowUpRight } from "@phosphor-icons/react/dist/ssr";
import { RevealSection } from "./RevealSection";
import { MagneticButton } from "./MagneticButton";
import { CAL_LINK } from "@/lib/config";

export function FinalCta() {
  return (
    <section id="programeaza" className="mx-auto max-w-7xl px-6 py-28 lg:px-8">
      <RevealSection className="relative overflow-hidden rounded-3xl border border-border-subtle bg-background-elevated px-8 py-16 text-center md:px-16">
        <motion.div
          className="pointer-events-none absolute inset-x-0 -top-24 mx-auto h-64 w-[600px] rounded-full opacity-25 blur-[120px]"
          style={{ background: "linear-gradient(135deg, #3fd8e8, #1450d8)" }}
          animate={{ scale: [1, 1.15, 1], opacity: [0.25, 0.35, 0.25] }}
          transition={{ duration: 6, repeat: Infinity, ease: "easeInOut" }}
        />
        <h2 className="relative mx-auto max-w-2xl text-3xl font-bold tracking-tight text-foreground md:text-4xl">
          Hai să vedem dacă bugetul tău de reclame poate lucra mai eficient.
        </h2>
        <p className="relative mx-auto mt-4 max-w-md text-base text-foreground-muted">
          Un apel de 20 de minute, fără obligații. Îți arăt exact ce ar face
          agentul cu campaniile tale.
        </p>
        <MagneticButton
          href={CAL_LINK}
          target="_blank"
          rel="noopener noreferrer"
          className="relative mt-8 inline-flex items-center gap-2 rounded-full bg-brand-blue px-7 py-3.5 text-sm font-semibold text-white"
        >
          Programează un apel
          <ArrowUpRight size={16} weight="bold" />
        </MagneticButton>
      </RevealSection>
    </section>
  );
}
