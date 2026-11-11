import type { Metadata } from "next";
import { AutomationWorkspace } from "@/components/AutomationWorkspace";
import { AnimatedHeading } from "@/components/AnimatedHeading";
import { Footer } from "@/components/Footer";

export const metadata: Metadata = { title: "Automatizările echipei: AC Media", description: "Configurează fluxurile, verifică mesajele și urmărește rulările direct în contul AC Media." };
export default function AutomationsPage() {
  return <><main className="native-page mx-auto max-w-7xl px-6 lg:px-8"><header className="native-page__intro"><AnimatedHeading as="h1" text={"Automatizările echipei.\nÎntr-un singur loc."} className="section-display" /><p className="section-description">Configurezi procesul, verifici mesajele și urmărești fiecare rulare. Totul rămâne în contul tău AC Media.</p></header><AutomationWorkspace /></main><Footer /></>;
}
