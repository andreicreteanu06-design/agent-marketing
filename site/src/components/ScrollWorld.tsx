"use client";

import { useEffect, useRef } from "react";
import { mountScrollWorld } from "@/lib/scroll-world-engine.js";
import { CAL_LINK } from "@/lib/config";

const CYAN = "#3fd8e8";
const BLUE = "#1450d8";

/**
 * Engine-ul isi construieste singur DOM-ul (vezi scroll-world-engine.js) si
 * porneste event listeners globale la montare, fara cleanup expus - in
 * StrictMode (dev) efectul ruleaza de doua ori, deci verificam childElementCount
 * ca a doua rulare sa fie no-op, nu o dubla montare.
 */
export function ScrollWorld() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = ref.current;
    if (!container || container.childElementCount > 0) return;

    mountScrollWorld(container, {
      diveScroll: 1.5,
      connScroll: 0.9,
      hint: "scrolează",
      nav: false,
      atmosphere: true,
      sections: [
        {
          id: "hero",
          label: "Agent AI",
          still: "/scroll-world/hero.webp",
          stillMobile: "/scroll-world/hero-m.webp",
          clip: "/scroll-world/vid/hero.mp4",
          clipMobile: "/scroll-world/vid/hero-m.mp4",
          accent: CYAN,
          scroll: 1.7,
          linger: 0.35,
          eyebrow: "AC Media",
          title: "Un agent AI care îți crește afacerea.",
          body: "Kelly și Thompson Sampling decid zilnic unde merge bugetul. Tu aprobi fiecare schimbare.",
          tags: ["Google Ads", "Meta Ads", "TikTok Ads"],
        },
        {
          id: "ppc",
          label: "Management PPC",
          still: "/scroll-world/ppc.webp",
          stillMobile: "/scroll-world/ppc-m.webp",
          clip: "/scroll-world/vid/ppc.mp4",
          clipMobile: "/scroll-world/vid/ppc-m.mp4",
          accent: BLUE,
          scroll: 1.4,
          eyebrow: "Management PPC",
          title: "Bugetul merge unde convertește.",
          body: "Recalculare zilnică pe date reale de conversie, pe Google, Meta și TikTok Ads.",
          tags: ["Thompson Sampling", "Aprobare umană"],
        },
        {
          id: "web",
          label: "Web Design",
          still: "/scroll-world/web.webp",
          stillMobile: "/scroll-world/web-m.webp",
          clip: "/scroll-world/vid/web.mp4",
          clipMobile: "/scroll-world/vid/web-m.mp4",
          accent: CYAN,
          scroll: 1.4,
          eyebrow: "Web Design",
          title: "Site-uri construite să convertească.",
          body: "Structură clară, viteză și un design care își câștigă vizitatorii.",
          tags: [],
        },
        {
          id: "automations",
          label: "Automatizări AI",
          still: "/scroll-world/automations.webp",
          stillMobile: "/scroll-world/automations-m.webp",
          clip: "/scroll-world/vid/automations.mp4",
          clipMobile: "/scroll-world/vid/automations-m.mp4",
          accent: BLUE,
          scroll: 1.4,
          eyebrow: "Automatizări AI",
          title: "Procese care rulează singure.",
          body: "Fluxuri automate care leagă datele, echipa și clienții, fără muncă manuală repetitivă.",
          tags: [],
        },
        {
          id: "cta",
          label: "Hai să vorbim",
          still: "/scroll-world/cta.webp",
          stillMobile: "/scroll-world/cta-m.webp",
          clip: "/scroll-world/vid/cta.mp4",
          clipMobile: "/scroll-world/vid/cta-m.mp4",
          accent: CYAN,
          scroll: 1.8,
          linger: 0.4,
          eyebrow: "Hai să vorbim",
          title: "Programează un apel.",
          body: "Vezi exact cum ar arăta agentul lucrând pentru afacerea ta.",
          tags: [],
          cta: {
            primary: { label: "Programează un apel", href: CAL_LINK },
            secondary: { label: "Creează cont", href: "/creeaza-cont" },
          },
        },
      ],
      connectors: [null, null, null, null],
      connectorsMobile: [null, null, null, null],
    });
  }, []);

  return <div ref={ref} className="sw-container" />;
}
