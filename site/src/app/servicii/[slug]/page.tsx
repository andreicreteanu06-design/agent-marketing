import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, ArrowUpRight, Check } from "@phosphor-icons/react/dist/ssr";
import { Footer } from "@/components/Footer";
import { AnimatedHeading } from "@/components/AnimatedHeading";
import { RevealSection } from "@/components/RevealSection";
import { MagneticButton } from "@/components/MagneticButton";
import { ServiceVisual3DLazy } from "@/components/ServiceVisual3DLazy";
import { ServiceShowcase } from "@/components/ServiceShowcase";
import { SpatialSculpture } from "@/components/SpatialSculpture";
import { ServiceScrollHero } from "@/components/ServiceScrollHero";
import { AutomationCatalog } from "@/components/AutomationCatalog";
import { SERVICES, getServiceBySlug } from "@/lib/services";

export function generateStaticParams() {
  return SERVICES.map((service) => ({ slug: service.slug }));
}

export async function generateMetadata(props: PageProps<"/servicii/[slug]">): Promise<Metadata> {
  const { slug } = await props.params;
  const service = getServiceBySlug(slug);
  if (!service) return {};
  return { title: service.title + ": AC Media Marketing", description: service.subtitle };
}

export default async function ServiceDetailPage(props: PageProps<"/servicii/[slug]">) {
  const { slug } = await props.params;
  const service = getServiceBySlug(slug);
  if (!service) notFound();
  const otherServices = SERVICES.filter((s) => s.slug !== service.slug);

  return <>
    <main className={"service-detail service-detail--" + service.variant}>
      <ServiceScrollHero variant={service.variant} title={service.title} />
      <div className="service-page-content">
        <section className="service-editorial mx-auto max-w-7xl px-6 lg:px-8">
          <RevealSection className="service-editorial__intro">
            <AnimatedHeading text={service.title} className="section-display" />
            <p className="section-description">{service.subtitle}</p>
          </RevealSection>
          <RevealSection className={"service-editorial__exhibit service-editorial__exhibit--" + service.variant}>
            <ServiceShowcase variant={service.variant} />
            <div className="service-editorial__principle">
              {service.variant === "automations" && <SpatialSculpture variant="relay" className="service-editorial__sculpture" />}
              <h3>{service.variant === "ppc" ? "Vezi motivul din spatele fiecărei propuneri." : service.variant === "web" ? "O identitate care se simte în fiecare pagină." : "Un traseu clar, de la solicitare la răspuns."}</h3>
              <p>{service.cardBody[0]}</p>
              {service.variant === "web" && <Link href="/#portofoliu" className="enterprise-text-link">Vezi proiectele reale <ArrowUpRight size={18} /></Link>}
              {service.variant === "ppc" && <Link href="/#consiliu" className="enterprise-text-link">Descoperă consiliul AI <ArrowUpRight size={18} /></Link>}
            </div>
          </RevealSection>
        </section>

        {service.variant === "automations" && <AutomationCatalog />}

        <section id="proces" className="service-journey mx-auto max-w-7xl px-6 lg:px-8" aria-labelledby="service-process-title">
          <RevealSection><div id="service-process-title"><AnimatedHeading text="Cum prinde formă." className="section-display" /></div></RevealSection>
          <div className="service-journey__layout">
            <div className="service-journey__visual">
              <div className="service-journey__lens"><i /><i /></div>
              <ServiceVisual3DLazy variant={service.variant} />
              <p>De la intenție, la execuție.</p>
            </div>
            <div className="service-journey__steps">
              {service.howItWorks.map((step, index) => <RevealSection key={step.title} className="service-journey__step">
                <span className="service-journey__number">0{index + 1}</span>
                <div><h3>{step.title}</h3><p>{step.body}</p></div>
              </RevealSection>)}
            </div>
          </div>
        </section>

        <section className="service-value mx-auto max-w-7xl px-6 lg:px-8">
          <RevealSection className="service-value__layout">
            <AnimatedHeading text={"Ce câștigi,\nîn practică."} className="section-display" />
            <div className="service-value__list">{service.benefits.map(benefit => <div key={benefit.title}>
              <Check size={20} /><div><h3>{benefit.title}</h3><p>{benefit.body}</p></div>
            </div>)}</div>
          </RevealSection>
        </section>

        <section className="service-next mx-auto max-w-7xl px-6 lg:px-8">
          <RevealSection className="service-next__invitation">
            <div><AnimatedHeading text="Să pornim de la obiectivul tău." className="section-display" /><p>O conversație despre ce ai nevoie și cum putem construi împreună.</p></div>
            <MagneticButton href="/#programeaza" className="enterprise-button">Programează un apel <ArrowUpRight size={18} /></MagneticButton>
          </RevealSection>
          <RevealSection className="service-next__links">{otherServices.map(s => <Link key={s.slug} href={"/servicii/" + s.slug}><span>{s.title}</span><ArrowRight size={20} /></Link>)}</RevealSection>
        </section>
      </div>
    </main>
    <Footer />
  </>;
}