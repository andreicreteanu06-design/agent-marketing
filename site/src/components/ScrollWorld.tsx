"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { SceneAnimatedTitle } from "./SceneAnimatedTitle";
import { HeroProductDemo } from "./HeroProductDemo";
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
  const [demoHost, setDemoHost] = useState<HTMLDivElement | null>(null);
  const [titleHosts, setTitleHosts] = useState<HTMLHeadingElement[]>([]);

  // Pause decorative CSS layers when the cinematic sequence leaves the viewport.
  useEffect(() => {
    const container = ref.current;
    if (!container) return;
    const io = new IntersectionObserver(
      ([entry]) => container.classList.toggle("is-offscreen", !entry.isIntersecting),
      { rootMargin: "200px 0px" },
    );
    io.observe(container);
    const syncPageVisibility = () => container.classList.toggle("is-document-hidden", document.hidden);
    syncPageVisibility();
    document.addEventListener("visibilitychange", syncPageVisibility);
    return () => {
      io.disconnect();
      document.removeEventListener("visibilitychange", syncPageVisibility);
    };
  }, []);

  useEffect(() => {
    const container = ref.current;
    if (!container) return;

    const destroy = mountScrollWorld(container, {
      diveScroll: 1.5,
      connScroll: 0.9,
      hint: "scrolează",
      nav: false,
      atmosphere: false,
      sections: [
        {
          id: "hero",
          label: "Agent AI",
          accent: CYAN,
          scroll: 1.7,
          linger: 0.35,
          eyebrow: "AC Media / Agency in a Box",
          title: "O agenție întreagă. Într-un singur sistem.",
          body: "Cinci agenți AI. O strategie comună. Controlul asupra bugetului rămâne la tine.",
          tags: ["5 agenți", "Decizii explicabile", "Aprobare umană"],
          cta: {
            primary: { label: "Solicită o programare", href: "/#programeaza" },
            secondary: { label: "Descoperă sistemul", href: "/#consiliu" },
          },
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
          title: "Fiecare decizie contează. Mai ales pentru buget.",
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
          title: "Design care atrage. Experiențe care conving.",
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
          title: "Mai puțină rutină. Mai multă perspectivă.",
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
          eyebrow: "Începe cu o conversație",
          title: "Următorul pas începe cu o conversație.",
          body: "Discutăm datele, bugetul și nivelul de control de care ai nevoie.",
          tags: [],
          cta: {
            primary: { label: "Solicită o programare", href: "/#programeaza" },
            secondary: { label: "Explorează platforma", href: "/creeaza-cont" },
          },
        },
      ],
      connectors: [null, null, null, null],
      connectorsMobile: [null, null, null, null],
    });

    // Presentation only: preserve the engine's copy nodes, scene timing and media.
    const titles = container.querySelectorAll<HTMLHeadingElement>(".sw-copy__title");
    titles.forEach((original, index) => {
      const text = original.textContent ?? "";
      const heading = document.createElement(index === 0 ? "h1" : "h2");
      heading.className = original.className + " motion-title-host";
      heading.setAttribute("aria-label", text);
      const fallback = document.createElement("span");
      fallback.className = "motion-title-fallback";
      fallback.setAttribute("aria-hidden", "true");
      fallback.textContent = text;
      heading.append(fallback);
      original.replaceWith(heading);
    });
    // The original article still owns the scroll position and scene opacity.
    const heroCopy = container.querySelector<HTMLElement>(".sw-copy");
    const message = document.createElement("div");
    message.className = "hero-message sw-reading-surface";
    const host = document.createElement("div");
    host.className = "hero-demo-host";
    if (heroCopy) {
      heroCopy.classList.add("sw-copy--hero");
      message.append(...Array.from(heroCopy.childNodes));
      heroCopy.append(message, host);
    }
    const portalFrame = requestAnimationFrame(() => {
      setDemoHost(heroCopy ? host : null);
      setTitleHosts(Array.from(container.querySelectorAll<HTMLHeadingElement>(".motion-title-host")));
    });
    // A hidden scene must not intercept clicks or retain keyboard focus.
    // The engine remains the source of truth for each scene's active state.
    const copies = Array.from(container.querySelectorAll<HTMLElement>(".sw-copy"));
    copies.forEach(copy => {
      if (copy !== heroCopy) copy.classList.add("sw-reading-surface");
    });
    const syncSceneAccess = () => {
      for (const copy of copies) {
        const hidden = copy.style.pointerEvents === "none";
        if (!hidden) copy.classList.add("is-copy-entered");
        if (copy.inert !== hidden) copy.inert = hidden;
        if (copy.getAttribute("aria-hidden") !== String(hidden)) copy.setAttribute("aria-hidden", String(hidden));
      }
    };
    const visibilityObserver = new MutationObserver(syncSceneAccess);
    copies.forEach(copy => visibilityObserver.observe(copy, { attributes: true, attributeFilter: ["style"] }));
    syncSceneAccess();

    const material = document.createElement("div");
    material.className = "sw-hero-material";
    material.setAttribute("aria-hidden", "true");
    material.innerHTML = '<span class="sw-hero-material__orbit sw-hero-material__orbit--a"><i></i></span><span class="sw-hero-material__orbit sw-hero-material__orbit--b"><i></i></span><span class="sw-hero-material__sculpture"></span><span class="sw-hero-material__caustic"></span>';
    container.querySelector(".sw-scene")?.appendChild(material);
    // Decorative optics run independently of the scroll engine and its media.
    const optics = document.createElement("div");
    optics.className = "sw-optics";
    optics.setAttribute("aria-hidden", "true");
    optics.innerHTML = '<span class="sw-optics__bloom"></span><span class="sw-optics__rim"></span>';
    container.querySelector(".sw-stage")?.appendChild(optics);
    container.querySelectorAll<HTMLButtonElement>(".sw-route__dot").forEach(dot => {
      dot.setAttribute("aria-label", dot.textContent?.trim() || "Scenă");
    });
    const bloom = optics.querySelector<HTMLElement>(".sw-optics__bloom");
    const rim = optics.querySelector<HTMLElement>(".sw-optics__rim");
    const pointerAllowed = window.matchMedia("(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)");
    let lightFrame = 0;
    let lightX = 0;
    let lightY = 0;
    const followLight = (event: PointerEvent) => {
      if (!pointerAllowed.matches || container.classList.contains("is-offscreen")) return;
      lightX = (event.clientX / window.innerWidth - 0.5) * 42;
      lightY = (event.clientY / window.innerHeight - 0.5) * 28;
      if (lightFrame) return;
      lightFrame = requestAnimationFrame(() => {
        material.style.transform = `translate3d(${lightX}px,${lightY}px,0) rotateY(${lightX / 10}deg)`;
        if (bloom) bloom.style.translate = `${-lightX}px ${-lightY}px`;
        if (rim) rim.style.translate = `${lightX}px 0`;
        lightFrame = 0;
      });
    };
    window.addEventListener("pointermove", followLight, { passive: true });
    return () => {
      cancelAnimationFrame(portalFrame);
      visibilityObserver.disconnect();
      window.removeEventListener("pointermove", followLight);
      cancelAnimationFrame(lightFrame);
      destroy();
    };
  }, []);

  // `isolate`: straturile fixed ale motorului (z-index 0-60) raman intr-un
  // stacking context propriu, sub Navbar (z-50) - altfel .sw-topbar (gol, dar
  // cu pointer-events) statea peste meniu si inghitea click-urile pe linkuri,
  // iar continutul de dupa trebuia ridicat la z-[100], peste Navbar si grain.
  return <><div ref={ref} className="sw-container isolate" />{demoHost && createPortal(<HeroProductDemo />, demoHost)}{titleHosts.map((heading, index) => <SceneAnimatedTitle key={index} heading={heading} />)}</>;
}
