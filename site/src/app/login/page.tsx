import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { LoginForm } from "@/components/LoginForm";
import { RevealSection } from "@/components/RevealSection";

export const metadata: Metadata = {
  title: "Autentificare: AC Media Marketing",
  description: "Autentifică-te în contul tău de client AC Media.",
};

export default function LoginPage() {
  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-md px-6 pb-28 pt-32 lg:px-8">
        <Link
          href="/"
          className="mb-8 inline-flex items-center gap-1.5 text-sm text-foreground-muted hover:text-foreground"
        >
          <ArrowLeft size={14} />
          Înapoi la site
        </Link>
        <RevealSection>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Autentificare</h1>
          <p className="mt-3 text-base text-foreground-muted">
            Intră în contul tău de client AC Media.
          </p>
        </RevealSection>
        <RevealSection delay={0.1} className="mt-10">
          <LoginForm />
        </RevealSection>
      </main>
      <Footer />
    </>
  );
}
