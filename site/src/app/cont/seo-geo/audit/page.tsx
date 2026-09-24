import type { Metadata } from "next";
import { SiteAudit } from "@/components/seo-geo/SiteAudit";

export const metadata: Metadata = {
  title: "Audit site: AC Media Marketing",
  description:
    "Audit tehnic al site-ului: crawl real, probleme verificabile cu URL și valorile măsurate, plus scoruri SEO și GEO.",
};

export default function SiteAuditPage() {
  return <SiteAudit />;
}
