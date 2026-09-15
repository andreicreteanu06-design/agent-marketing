import Link from "next/link";
import { ArrowUpRight } from "@phosphor-icons/react/dist/ssr";
import { RevealSection } from "./RevealSection";
import { SpotlightCard } from "./SpotlightCard";
import { SERVICES } from "@/lib/services";

export function Services() {
  return (
    <section id="servicii" className="mx-auto max-w-7xl px-6 py-28 lg:px-8">
      <RevealSection>
        <h2 className="max-w-xl text-3xl font-bold tracking-tight text-foreground md:text-4xl">
          Trei servicii, o singură logică din spate.
        </h2>
        <p className="mt-4 max-w-xl text-base leading-relaxed text-foreground-muted">
          PPC, web design și automatizări nu sunt echipe separate. Tot ce
          construiesc pentru un client pornește de la datele reale ale
          campaniilor lui. Deschide fiecare serviciu pentru detalii.
        </p>
      </RevealSection>

      <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-2">
        {SERVICES.map((service, i) => (
          <RevealSection
            key={service.slug}
            delay={0.05 + i * 0.05}
            className={i === 0 ? "md:row-span-2" : undefined}
          >
            <Link href={`/servicii/${service.slug}`} className="block h-full">
              <SpotlightCard className="h-full rounded-3xl border border-border-subtle bg-background-elevated p-8">
                <div className="flex h-full flex-col">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-blue/15 text-brand-cyan transition-transform duration-300 group-hover:-rotate-6 group-hover:scale-110">
                    <service.icon size={22} weight="duotone" />
                  </div>
                  <h3 className="mt-6 text-xl font-semibold text-foreground">{service.title}</h3>
                  {service.cardBody.map((paragraph) => (
                    <p key={paragraph} className="mt-3 leading-relaxed text-foreground-muted">
                      {paragraph}
                    </p>
                  ))}
                  <div className="mt-auto flex items-center gap-1.5 pt-8 text-sm font-semibold text-brand-cyan">
                    Vezi în detaliu
                    <ArrowUpRight
                      size={16}
                      weight="bold"
                      className="transition-transform duration-300 group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                    />
                  </div>
                </div>
              </SpotlightCard>
            </Link>
          </RevealSection>
        ))}
      </div>
    </section>
  );
}
