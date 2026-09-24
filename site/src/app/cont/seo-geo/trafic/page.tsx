import type { Metadata } from "next";
import { TrafficPositions } from "@/components/seo-geo/TrafficPositions";

export const metadata: Metadata = {
  title: "Trafic & Poziții: AC Media Marketing",
  description:
    "Traficul din GA4, pozițiile din Search Console și volumele din Keyword Planner, cu recomandările agentului.",
};

export default function TrafficPositionsPage() {
  return <TrafficPositions />;
}
