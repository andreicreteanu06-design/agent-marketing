import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { SeoGeoDashboard } from "@/components/SeoGeoDashboard";

export const metadata: Metadata = {
  title: "Analiză SEO + GEO: AC Media Marketing",
  description: "Scoruri SEO și GEO plus sugestii tehnice exacte, pe baza rapoartelor tale.",
};

export default function SeoGeoPage() {
  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-3xl px-6 pb-28 pt-32 lg:px-8">
        <Link
          href="/cont"
          className="mb-8 inline-flex items-center gap-1.5 text-sm text-foreground-muted hover:text-foreground"
        >
          <ArrowLeft size={14} />
          Contul meu
        </Link>
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Analiză SEO + GEO</h1>
        <p className="mt-3 text-base text-foreground-muted">
          Scoruri și sugestii tehnice exacte - pentru motoare de căutare clasice
          (SEO) și pentru citare de către modele AI (GEO).
        </p>
        <div className="mt-10">
          <SeoGeoDashboard />
        </div>
      </main>
      <Footer />
    </>
  );
}
