import type { Metadata } from "next";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { AccountDashboard } from "@/components/AccountDashboard";

export const metadata: Metadata = {
  title: "Contul meu: AC Media Marketing",
  description: "Contul tău de client AC Media - conectează-ți conturile de reclame.",
};

export default function ContPage() {
  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-lg px-6 pb-28 pt-32 lg:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Contul meu</h1>
        <p className="mt-3 text-base text-foreground-muted">
          Conectează-ți conturile de reclame ca agentul să poată gestiona campaniile.
        </p>
        <div className="mt-10">
          <AccountDashboard />
        </div>
      </main>
      <Footer />
    </>
  );
}
