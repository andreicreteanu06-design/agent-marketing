"use client";

import { useEffect, useRef } from "react";
import { mountScrollWorld } from "@/lib/scroll-world-engine.js";

const CYAN = "#3fd8e8";
const BLUE = "#1450d8";

/**
 * Engine-ul isi construieste singur DOM-ul (vezi scroll-world-engine.js) si
 * porneste o bucla requestAnimationFrame + listeners pe window. Cleanup-ul
 * efectului apeleaza destroy()-ul intors de mountScrollWorld: fara el, fiecare
 * intoarcere pe homepage (navigare client-side, documentul ramane acelasi)
 * lasa in urma o bucla care nu se opreste niciodata si listeners care citesc
 * scroll-ul si pe alte pagini - si descarca acolo clipuri de 12-22 MB pentru o
 * scena pe care nu o mai vede nimeni. In StrictMode (dev) efectul ruleaza,
 * face cleanup si ruleaza din nou: montare -> destroy (goleste containerul,
 * anuleaza descarcarile) -> montare curata.
 */
export function ScrollWorld() {
  const ref = useRef<HTMLDivElement>(null);

  // Titlurile din scroll-world au glow + gradient animate continuu (vezi
  // .sw-copy__title in globals.css) - text-shadow si background-position
  // sunt proprietati de paint, nu de compositor, deci browserul le repicteaza
  // in fiecare cadru cat timp animatia ruleaza. Fara asta ar rula pentru
  // totdeauna, si dupa ce utilizatorul a scrolat mult mai jos (continutul opac
  // cu z-index mai mare acopera oricum acest strat fixed - vezi comentariul
  // din page.tsx). Clasa .is-offscreen le pune pe pauza cand containerul (deci
  // toata secventa cinematica) iese din viewport; vizualul cand E vizibil
  // ramane neschimbat.
  useEffect(() => {
    const container = ref.current;
    if (!container) return;
    const io = new IntersectionObserver(
      ([entry]) => container.classList.toggle("is-offscreen", !entry.isIntersecting),
      { rootMargin: "200px 0px" },
    );
    io.observe(container);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    const container = ref.current;
    if (!container) return;

    return mountScrollWorld(container, {
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
          tags: ["Google Ads", "Meta Ads", "TikTok Ads", "ChatGPT Ads"],
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
          body: "Recalculare zilnică pe date reale de conversie, pe Google, Meta, TikTok și ChatGPT Ads.",
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
            primary: { label: "Programează un apel", href: "/#programeaza" },
            secondary: { label: "Creează cont", href: "/creeaza-cont" },
          },
        },
      ],
      connectors: [null, null, null, null],
      connectorsMobile: [null, null, null, null],
    });
  }, []);

  // `isolate`: straturile fixed ale motorului (z-index 0-60) raman intr-un
  // stacking context propriu, sub Navbar (z-50) - altfel .sw-topbar (gol, dar
  // cu pointer-events) statea peste meniu si inghitea click-urile pe linkuri,
  // iar continutul de dupa trebuia ridicat la z-[100], peste Navbar si grain.
  return <div ref={ref} className="sw-container isolate" />;
}
