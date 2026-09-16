"use client";

import dynamic from "next/dynamic";
import type { ServiceVisualVariant } from "./ServiceVisual3D";

// ServiceVisual3D trage three.js + @react-three/fiber + drei + postprocessing
// (Bloom/EffectComposer) + three-bvh-csg pentru fiecare varianta de vizual -
// cel mai greu pachet din site, cerut doar de paginile de detaliu serviciu.
// dynamic + ssr:false il scoate din bundle-ul initial al acelei pagini: se
// cere abia pe client, cand vizualul chiar se randeaza. Fallback-ul umple
// acelasi container (aspect-square, setat de parinte), deci nu apare layout
// shift cand canvas-ul real preia locul.
export const ServiceVisual3DLazy = dynamic<{ variant: ServiceVisualVariant }>(
  () => import("./ServiceVisual3D").then((m) => m.ServiceVisual3D),
  {
    ssr: false,
    loading: () => <div className="h-full w-full animate-pulse bg-background-elevated" />,
  },
);
