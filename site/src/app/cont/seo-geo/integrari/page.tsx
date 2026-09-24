import { Suspense } from "react";
import type { Metadata } from "next";
import { IntegrationsHub } from "@/components/seo-geo/IntegrationsHub";

export const metadata: Metadata = {
  title: "Integrări: AC Media Marketing",
  description: "Conectează Google Search Console și Google Analytics 4 la contul tău.",
};

export default function IntegrationsPage() {
  // useSearchParams (mesajul de la intoarcerea de pe ecranul Google) cere o
  // limita Suspense pe rutele pre-randate - vezi documentatia useSearchParams.
  return (
    <Suspense fallback={<p className="text-sm text-foreground-muted">Se încarcă...</p>}>
      <IntegrationsHub />
    </Suspense>
  );
}
