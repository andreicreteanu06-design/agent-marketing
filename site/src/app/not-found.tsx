import type { Metadata } from "next";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { AuroraBackground } from "@/components/AuroraBackground";
import { AnimatedTitleFM } from "@/components/ui/glow-horizon-utils/animated-title-fm";
import { MagneticButton } from "@/components/MagneticButton";

export const metadata: Metadata = {
  title: "Pagina nu există: AC Media Marketing",
};

export default function NotFound() {
  return (
    <>
      <Navbar />
      <main className="relative flex min-h-[100dvh] items-center justify-center overflow-hidden px-6">
        <AuroraBackground />
        <div className="relative text-center">
          <p className="font-mono text-sm text-brand-cyan">404</p>
          <div className="mt-4">
            <AnimatedTitleFM
              open
              align="center"
              title="Pagina nu există."
              subtitle="Verifică adresa sau întoarce-te acasă."
              titleClassName="text-foreground md:text-5xl"
            />
          </div>
          <MagneticButton
            href="/"
            className="relative z-10 mt-9 inline-flex items-center gap-2 rounded-full bg-brand-blue px-6 py-3.5 text-sm font-semibold text-white"
          >
            <ArrowLeft size={16} weight="bold" />
            Înapoi acasă
          </MagneticButton>
        </div>
      </main>
      <Footer />
    </>
  );
}
