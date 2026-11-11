import { AnimatedHeading } from "./AnimatedHeading";
import { RevealSection } from "./RevealSection";
import { CouncilExperience } from "./CouncilExperience";

export function ExecutiveCouncil() {
  return <section id="consiliu" className="council-section marketing-section" aria-labelledby="council-title">
    <div className="mx-auto max-w-7xl px-6 lg:px-8">
      <RevealSection className="council-intro">
        <div id="council-title"><AnimatedHeading text={"Cinci perspective.\nO direcție clară."} className="section-display max-w-2xl" /></div>
        <p className="section-description">Strategia, cifrele, infrastructura, oferta și piața, la aceeași masă. Fiecare recomandare are un motiv. Fiecare schimbare de buget, aprobarea ta.</p>
      </RevealSection>
      <CouncilExperience />
    </div>
  </section>;
}
