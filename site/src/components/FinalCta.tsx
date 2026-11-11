"use client";

import dynamic from "next/dynamic";
import { ArrowUpRight } from "@phosphor-icons/react/dist/ssr";
import { AnimatedHeading } from "./AnimatedHeading";
import { NearViewport } from "./NearViewport";
import { RevealSection } from "./RevealSection";
import { SpatialSculpture } from "./SpatialSculpture";
import { Spinner } from "./ui/spinner";
import { CAL_LINK } from "@/lib/config";

const calendarPlaceholder = (
  <div className="flex h-full w-full items-center justify-center">
    <Spinner label="Se încarcă calendarul…" />
  </div>
);

// Calendarul e ultima sectiune a homepage-ului: @calcom/embed-react, embed.js
// de la cal.com si iframe-ul lor se incarca abia cand utilizatorul ajunge
// aproape (NearViewport, mai jos), nu odata cu primul ecran.
const CalEmbed = dynamic(() => import("./CalEmbed").then((m) => m.CalEmbed), {
  ssr: false,
  loading: () => calendarPlaceholder,
});

export function FinalCta() {
  return (
    <section id="programeaza" className="mx-auto max-w-7xl px-6 py-24 lg:px-8 lg:py-32">
      <RevealSection className="booking-intro relative">
        <div className="cta-light" aria-hidden="true" />
        <div className="booking-copy">
          <AnimatedHeading
            text="O conversație bună. O direcție nouă."
            className="relative section-display"
          />
          <p className="relative mt-6 max-w-xl text-base leading-7 text-foreground-muted">
            În 20 de minute parcurgem obiectivele, datele și regulile de aprobare.
            Vezi unde consiliul poate aduce claritate înainte de implementare.
          </p>
          <a
            href={CAL_LINK}
            target="_blank"
            rel="noopener noreferrer"
            className="enterprise-text-link relative mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-foreground"
          >
            Deschide calendarul separat
            <ArrowUpRight size={14} weight="bold" />
          </a>
        </div>
        <SpatialSculpture variant="gateway" className="booking-sculpture" />
      </RevealSection>

      <RevealSection
        delay={0.1}
        className="premium-panel relative mt-12 overflow-hidden rounded-3xl"
      >
        <NearViewport className="h-[600px] w-full md:h-[700px]" fallback={calendarPlaceholder}>
          <CalEmbed />
        </NearViewport>
      </RevealSection>
    </section>
  );
}
