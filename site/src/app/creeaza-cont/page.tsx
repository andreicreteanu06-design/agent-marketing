import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { SignupForm } from "@/components/SignupForm";
import { RevealSection } from "@/components/RevealSection";

export const metadata: Metadata = {
  title: "Creează cont: AC Media Marketing",
  description: "Creează-ți contul de client AC Media și conectează-ți conturile de reclame.",
};

export default function CreeazaContPage() {
  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-lg px-6 pb-28 pt-32 lg:px-8">
        <Link
          href="/"
          className="mb-8 inline-flex items-center gap-1.5 text-sm text-foreground-muted hover:text-foreground"
        >
          <ArrowLeft size={14} />
          Înapoi la site
        </Link>
        <RevealSection>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">
            Creează cont
          </h1>
          <p className="mt-3 text-base text-foreground-muted">
            Contul tău de client AC Media. După ce te înregistrezi,
            conectezi conturile de reclame direct din pagina de cont, cu
            cheile criptate imediat.
          </p>
        </RevealSection>
        <RevealSection delay={0.1} className="mt-10">
          <SignupForm />
        </RevealSection>
      </main>
      <Footer />
    </>
  );
}
