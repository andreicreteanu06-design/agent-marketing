"use client";

import { useEffect, useRef, useState } from "react";
import { SceneAnimatedTitle } from "./SceneAnimatedTitle";
import { mountScrollWorld } from "@/lib/scroll-world-engine.js";
import type { ServiceVisualVariant } from "@/lib/services";

const SCENES = {
  ppc: { file: "ppc", title: "Fiecare decizie contează.", body: "Marketing ghidat de date. Propuneri explicate, bugete aprobate de tine." },
  web: { file: "web", title: "Design care atrage. Experiențe care conving.", body: "De la primul contact cu brandul, până la următoarea acțiune. Un parcurs gândit în fiecare detaliu." },
  automations: { file: "automations", title: "Mai puțină rutină. Mai multă perspectivă.", body: "Datele, echipa și instrumentele tale, conectate într-un proces care are sens." },
} as const;

/** Each service reuses one existing camera take. The landing-page timeline is untouched. */
export function ServiceScrollHero({ variant, title }: { variant: ServiceVisualVariant; title: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const scene = SCENES[variant];
  const [titleHost, setTitleHost] = useState<HTMLHeadingElement | null>(null);

  useEffect(() => {
    const container = ref.current;
    if (!container) return;
    const destroy = mountScrollWorld(container, {
      atmosphere: false,
      nav: false,
      hint: "Explorează prin scroll",
      diveScroll: 1.35,
      sections: [{
        id: variant,
        label: title,
        still: "/scroll-world/" + scene.file + ".webp",
        stillMobile: "/scroll-world/" + scene.file + "-m.webp",
        clip: "/scroll-world/vid/" + scene.file + ".mp4",
        clipMobile: "/scroll-world/vid/" + scene.file + "-m.mp4",
        accent: "#a3cee7",
        scroll: 1.35,
        linger: 0.2,
        title: scene.title,
        body: scene.body,
        tags: [],
        cta: {
          primary: { label: "Programează un apel", href: "/#programeaza" },
          secondary: { label: variant === "automations" ? "Vezi automatizările" : "Vezi procesul", href: variant === "automations" ? "#automatizari" : "#proces" },
        },
      }],
      connectors: [],
      connectorsMobile: [],
    });
    const copy = container.querySelector<HTMLElement>(".sw-copy");
    const heading = copy?.querySelector(".sw-copy__title");
    if (heading) {
      const h1 = document.createElement("h1");
      h1.className = heading.className + " motion-title-host";
      h1.setAttribute("aria-label", scene.title);
      const fallback = document.createElement("span");
      fallback.className = "motion-title-fallback";
      fallback.setAttribute("aria-hidden", "true");
      fallback.textContent = scene.title;
      h1.append(fallback);
      heading.replaceWith(h1);
    }
    if (copy) {
      copy.classList.add("sw-reading-surface");
      const back = document.createElement("a");
      back.href = "/#servicii";
      back.className = "service-world__back";
      back.textContent = "Toate serviciile";
      copy.prepend(back);
    }
    const portalFrame = requestAnimationFrame(() => setTitleHost(container.querySelector<HTMLHeadingElement>(".motion-title-host")));
    const syncAccess = () => {
      if (!copy) return;
      const hidden = copy.style.pointerEvents === "none";
      if (!hidden) copy.classList.add("is-copy-entered");
      copy.inert = hidden;
      copy.setAttribute("aria-hidden", String(hidden));
    };
    const observer = new MutationObserver(syncAccess);
    if (copy) observer.observe(copy, { attributes: true, attributeFilter: ["style"] });
    syncAccess();
    return () => {
      cancelAnimationFrame(portalFrame);
      observer.disconnect();
      destroy();
    };
  }, [variant, title, scene]);

  return <><div ref={ref} className={"sw-container service-world service-world--" + variant + " isolate"} aria-label={title + " — prezentare interactivă"} />{titleHost && <SceneAnimatedTitle heading={titleHost} />}</>;
}
