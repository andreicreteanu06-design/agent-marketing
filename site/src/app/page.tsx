import { Navbar } from "@/components/Navbar";
import { ScrollWorld } from "@/components/ScrollWorld";
import { Services } from "@/components/Services";
import { About } from "@/components/About";
import { Footer } from "@/components/Footer";

export default function Home() {
  return (
    <>
      <Navbar />
      <main>
        <ScrollWorld />
        {/* Fundal opac + z-index peste straturile position:fixed ale
            scroll-world (topbar/stage/copylayer/route, toate z<=60) - altfel
            ultima sectiune ramane suprapusa peste tot ce urmeaza in flux. */}
        <div className="relative z-[100] bg-background">
          <Services />
          <About />
          <Footer />
        </div>
      </main>
    </>
  );
}
