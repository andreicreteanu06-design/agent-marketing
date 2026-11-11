import Link from "next/link";
import { ArrowUpRight, ShieldCheck } from "@phosphor-icons/react/dist/ssr";
import { AnimatedHeading } from "./AnimatedHeading";
import { RevealSection } from "./RevealSection";
import { SpotlightCard } from "./SpotlightCard";
import { ServiceShowcase } from "./ServiceShowcase";
import { SpatialSculpture } from "./SpatialSculpture";
import { SERVICES } from "@/lib/services";

const SERVICE_COPY = {
  ppc: { title: "Mai mult sens pentru fiecare leu.", body: "Campaniile sunt evaluate pe date de conversie. Vezi ce recomandă sistemul și aprobi schimbările de buget înainte de aplicare.", detail: "Management PPC · Google, Meta, TikTok" },
  web: { title: "Din prima impresie, spre următorul pas.", body: "Un site care îți exprimă identitatea și face alegerea mai ușoară. Structură clară, pagini rapide și un parcurs firesc spre contact sau comandă.", detail: "Web design · Experiență · Dezvoltare" },
  automations: { title: "Timp pentru ceea ce contează.", body: "Conectăm datele și instrumentele pe care le folosești. Sarcinile repetitive devin fluxuri clare, iar echipa își păstrează atenția pentru clienți.", detail: "Automatizări AI · Integrări · Fluxuri" },
} as const;

export function Services() {
  return (
    <section id="servicii" className="services-section marketing-section mx-auto max-w-7xl px-6 py-24 lg:px-8 lg:py-32" aria-labelledby="services-title">
      <RevealSection className="section-intro">
        <div id="services-title"><AnimatedHeading text={"Totul conectat.\nFiecare detaliu contează."} className="section-display max-w-3xl" /></div>
        <div className="services-intro__support">
          <SpatialSculpture variant="relay" className="services-intro__sculpture" />
          <p className="section-description">Campanii, experiențe web și automatizări. Trei capabilități care lucrează împreună, în jurul aceluiași obiectiv.</p>
        </div>
      </RevealSection>
      <div className="services-grid">
        {SERVICES.map((service, index) => (
          <RevealSection key={service.slug} delay={index * 0.04} className={`service-card-wrap service-card-wrap--${service.variant}`}>
            <Link href={`/servicii/${service.slug}`} className="service-card-link" aria-label={`Explorează: ${service.title}`}>
              <SpotlightCard className={`premium-panel service-card service-card--${service.variant}`}>
                <div className="service-card__art" aria-hidden="true">
                  <ServiceShowcase variant={service.variant} />
                </div>
                <div className="service-card__content">
                  <div className="service-card__category"><service.icon size={20} weight="duotone" /><span>{service.title}</span></div>
                  <h3>{SERVICE_COPY[service.variant].title}</h3>
                  <p>{SERVICE_COPY[service.variant].body}</p>
                  <span className="service-card__disciplines">{SERVICE_COPY[service.variant].detail}</span>
                  {index === 0 && <div className="service-card__assurance"><ShieldCheck size={17} /> Control uman asupra bugetului</div>}
                  <div className="service-card__link">{service.variant === "automations" ? "Vezi cele 9 automatizări" : "Explorează serviciul"} <span><ArrowUpRight size={19} /></span></div>
                </div>
              </SpotlightCard>
            </Link>
          </RevealSection>
        ))}
      </div>
    </section>
  );
}
