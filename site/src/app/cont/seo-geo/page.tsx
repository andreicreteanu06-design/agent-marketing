import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { SeoGeoDashboard } from "@/components/SeoGeoDashboard";

export const metadata: Metadata = {
  title: "Audit SEO + GEO: AC Media Marketing",
  description:
    "Audit tehnic al site-ului: crawl real, probleme verificabile cu URL și valorile măsurate, plus scoruri SEO și GEO.",
};

export default function SeoGeoPage() {
  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-5xl px-6 pb-28 pt-32 lg:px-8">
        <Link
          href="/cont"
          className="mb-8 inline-flex items-center gap-1.5 text-sm text-foreground-muted hover:text-foreground"
        >
          <ArrowLeft size={14} />
          Contul meu
        </Link>
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Audit SEO + GEO</h1>
        <p className="mt-3 text-base text-foreground-muted">
          Crawlăm site-ul și verificăm fiecare regulă pe rând - pentru motoarele
          de căutare clasice (SEO) și pentru citarea de către modele AI (GEO).
          Fiecare problemă vine cu URL-ul afectat și cu valorile măsurate.
        </p>
        <div className="mt-10">
          <SeoGeoDashboard />
        </div>
      </main>
      <Footer />
    </>
  );
}
