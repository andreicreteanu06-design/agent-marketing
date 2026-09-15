import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowRight } from "@phosphor-icons/react/dist/ssr";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { RevealSection } from "@/components/RevealSection";
import { SpotlightCard } from "@/components/SpotlightCard";
import { MagneticButton } from "@/components/MagneticButton";
import { ServiceVisual3D } from "@/components/ServiceVisual3D";
import { SERVICES, getServiceBySlug } from "@/lib/services";
import { CAL_LINK } from "@/lib/config";

export function generateStaticParams() {
  return SERVICES.map((service) => ({ slug: service.slug }));
}

export async function generateMetadata(
  props: PageProps<"/servicii/[slug]">,
): Promise<Metadata> {
  const { slug } = await props.params;
  const service = getServiceBySlug(slug);
  if (!service) return {};
  return {
    title: `${service.title}: AC Media Marketing`,
    description: service.subtitle,
  };
}

export default async function ServiceDetailPage(props: PageProps<"/servicii/[slug]">) {
  const { slug } = await props.params;
  const service = getServiceBySlug(slug);
  if (!service) notFound();

  const otherServices = SERVICES.filter((s) => s.slug !== service.slug);

  return (
    <>
      <Navbar />
      <main>
        <section className="mx-auto max-w-7xl px-6 pb-16 pt-32 lg:px-8">
          <Link
            href="/#servicii"
            className="mb-8 inline-flex items-center gap-1.5 text-sm text-foreground-muted hover:text-foreground"
          >
            <ArrowLeft size={14} />
            Toate serviciile
          </Link>

          <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
            <RevealSection>
              <span className="text-sm font-semibold uppercase tracking-widest text-brand-cyan">
                {service.eyebrow}
              </span>
              <h1 className="mt-4 text-4xl font-bold tracking-tight text-foreground md:text-5xl">
                {service.title}
              </h1>
              <p className="mt-5 max-w-lg text-lg leading-relaxed text-foreground-muted">
                {service.subtitle}
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-5">
                <MagneticButton
                  href="/creeaza-cont"
                  className="rounded-full bg-brand-blue px-6 py-3 text-sm font-semibold text-white"
                >
                  Creează cont
                </MagneticButton>
                <a
                  href={CAL_LINK}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-semibold text-foreground hover:text-brand-cyan"
                >
                  Programează un apel
                </a>
              </div>
            </RevealSection>

            <RevealSection
              delay={0.1}
              className="aspect-square w-full overflow-hidden rounded-3xl border border-border-subtle bg-background-elevated bg-[radial-gradient(circle_at_50%_45%,rgba(20,80,216,0.28),transparent_70%)]"
            >
              <ServiceVisual3D variant={service.variant} />
            </RevealSection>
          </div>
        </section>

        <section className="border-t border-border-subtle bg-background-elevated/40">
          <div className="mx-auto max-w-7xl px-6 py-24 lg:px-8">
            <RevealSection>
              <h2 className="max-w-xl text-3xl font-bold tracking-tight text-foreground md:text-4xl">
                Cum funcționează
              </h2>
            </RevealSection>
            <div className="mt-12 grid grid-cols-1 gap-10 md:grid-cols-3">
              {service.howItWorks.map((step, i) => (
                <RevealSection key={step.title} delay={0.05 + i * 0.05}>
                  <span className="text-sm font-semibold text-brand-cyan">0{i + 1}</span>
                  <h3 className="mt-3 text-lg font-semibold text-foreground">{step.title}</h3>
                  <p className="mt-2 leading-relaxed text-foreground-muted">{step.body}</p>
                </RevealSection>
              ))}
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-6 py-24 lg:px-8">
          <RevealSection>
            <h2 className="max-w-xl text-3xl font-bold tracking-tight text-foreground md:text-4xl">
              Beneficii concrete
            </h2>
          </RevealSection>
          <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-3">
            {service.benefits.map((benefit, i) => (
              <RevealSection key={benefit.title} delay={0.05 + i * 0.05}>
                <SpotlightCard className="h-full rounded-3xl border border-border-subtle bg-background-elevated p-8">
                  <h3 className="text-lg font-semibold text-foreground">{benefit.title}</h3>
                  <p className="mt-3 leading-relaxed text-foreground-muted">{benefit.body}</p>
                </SpotlightCard>
              </RevealSection>
            ))}
          </div>
        </section>

        <section className="border-t border-border-subtle">
          <div className="mx-auto max-w-7xl px-6 py-24 text-center lg:px-8">
            <RevealSection>
              <h2 className="mx-auto max-w-2xl text-3xl font-bold tracking-tight text-foreground md:text-4xl">
                Hai să vedem dacă se potrivește pentru tine.
              </h2>
              <div className="mt-8 flex flex-wrap items-center justify-center gap-5">
                <MagneticButton
                  href="/creeaza-cont"
                  className="rounded-full bg-brand-blue px-6 py-3 text-sm font-semibold text-white"
                >
                  Creează cont
                </MagneticButton>
                <a
                  href={CAL_LINK}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-semibold text-foreground hover:text-brand-cyan"
                >
                  Programează un apel
                </a>
              </div>
            </RevealSection>

            <div className="mx-auto mt-16 grid max-w-3xl grid-cols-1 gap-4 text-left sm:grid-cols-2">
              {otherServices.map((s) => (
                <Link
                  key={s.slug}
                  href={`/servicii/${s.slug}`}
                  className="group flex items-center justify-between rounded-2xl border border-border-subtle bg-background-elevated px-6 py-4 transition-colors hover:border-brand-blue/40"
                >
                  <span className="font-medium text-foreground">{s.title}</span>
                  <ArrowRight
                    size={16}
                    className="text-foreground-muted transition-transform group-hover:translate-x-1"
                  />
                </Link>
              ))}
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
