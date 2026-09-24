import type { Metadata } from "next";
import { SeoGeoOverview } from "@/components/seo-geo/SeoGeoOverview";

export const metadata: Metadata = {
  title: "SEO + GEO: AC Media Marketing",
  description:
    "Starea site-ului în Google și în răspunsurile AI: ultimul audit, Search Console și Google Analytics.",
};

export default function SeoGeoOverviewPage() {
  return <SeoGeoOverview />;
}
