"use client";

import { motion } from "motion/react";
import { ArrowRight } from "@phosphor-icons/react/dist/ssr";
import { EASE_OUT } from "@/lib/motion";
import { AuroraBackground } from "./AuroraBackground";
import GlowHorizonFM from "./ui/glow-horizon";
import { AnimatedTitleFM } from "./ui/glow-horizon-utils/animated-title-fm";
import { HeroVisual } from "./HeroVisual";
import { MagneticButton } from "./MagneticButton";

export function Hero() {
  return (
    <section className="relative flex min-h-[100dvh] items-center overflow-hidden pt-24 pb-16">
      <GlowHorizonFM variant="top" className="opacity-70" />
      <AuroraBackground />
      <div className="relative mx-auto grid w-full max-w-7xl grid-cols-1 items-center gap-16 px-6 lg:grid-cols-[1.3fr_0.7fr] lg:px-8">
        <div>
          <AnimatedTitleFM
            open
            align="left"
            title="Bugetul de reclame, realocat automat."
            titleClassName="text-foreground md:text-5xl lg:text-6xl"
          />
          <motion.p
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 1.0, ease: EASE_OUT }}
            className="mt-6 max-w-lg text-lg leading-relaxed text-foreground-muted"
          >
            Un agent AI mută zilnic bugetul spre campania care chiar
            convertește, pe Google, Meta și TikTok Ads, cu aprobare umană
            înainte de orice schimbare.
          </motion.p>
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 1.3, ease: EASE_OUT }}
            className="mt-9 flex flex-wrap items-center gap-4"
          >
            <MagneticButton
              href="#programeaza"
              className="flex items-center gap-2 rounded-full bg-brand-blue px-6 py-3.5 text-sm font-semibold text-white"
            >
              Programează un apel
              <ArrowRight size={16} weight="bold" />
            </MagneticButton>
            <a
              href="/creeaza-cont"
              className="rounded-full border border-border-strong px-6 py-3.5 text-sm font-semibold text-foreground transition-colors hover:bg-white/5"
            >
              Creează cont
            </a>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 32 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, delay: 0.2, ease: EASE_OUT }}
          className="flex justify-center lg:justify-end"
        >
          <HeroVisual />
        </motion.div>
      </div>
    </section>
  );
}
