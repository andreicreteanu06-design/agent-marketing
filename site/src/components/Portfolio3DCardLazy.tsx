"use client";

import dynamic from "next/dynamic";

// Portfolio3DCard trage three.js + @react-three/fiber + drei doar ca sa
// incline un screenshot in WebGL - cateva sute de KB nefolosite de niciun
// vizitator care nu ajunge (sau nu are JS activ inca) pana la Portofoliu.
// dynamic + ssr:false scoate tot pachetul din bundle-ul initial al paginii:
// se cere abia cand cardul chiar se randeaza pe client. Fallback-ul pastreaza
// acelasi aspect-ratio ca originalul, deci nu apare layout shift cand
// canvas-ul real preia locul.
export const Portfolio3DCardLazy = dynamic(
  () => import("./Portfolio3DCard").then((m) => m.Portfolio3DCard),
  {
    ssr: false,
    loading: () => (
      <div className="aspect-[16/10] w-full animate-pulse bg-background-elevated" />
    ),
  },
);
