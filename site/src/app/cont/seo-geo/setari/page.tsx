import type { Metadata } from "next";
import { SeoGeoSettings } from "@/components/seo-geo/SeoGeoSettings";

export const metadata: Metadata = {
  title: "Setări SEO + GEO: AC Media Marketing",
  description: "Site-ul și brandul pe care lucrează agentul.",
};

export default function SeoGeoSettingsPage() {
  return <SeoGeoSettings />;
}
