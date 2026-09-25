import { ScrollWorld } from "@/components/ScrollWorld";
import { Services } from "@/components/Services";
import { SeoGeoPreview } from "@/components/SeoGeoPreview";
import { Portfolio } from "@/components/Portfolio";
import { About } from "@/components/About";
import { FinalCta } from "@/components/FinalCta";
import { Footer } from "@/components/Footer";

export default function Home() {
  return (
    <main>
      <ScrollWorld />
      {/* Fundal opac + z-index peste straturile position:fixed ale
          scroll-world (izolate in containerul lor, vezi ScrollWorld) - altfel
          ultima scena ramane suprapusa peste tot ce urmeaza in flux. z-10, nu
          mai mult: Navbar-ul (z-50) si grain-ul (z-60) trebuie sa ramana deasupra. */}
      <div className="relative z-10 bg-background">
        <Services />
        <SeoGeoPreview />
        <Portfolio />
        <About />
        <FinalCta />
        <Footer />
      </div>
    </main>
  );
}
