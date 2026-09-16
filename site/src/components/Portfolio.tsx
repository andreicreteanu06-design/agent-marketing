import { ArrowUpRight } from "@phosphor-icons/react/dist/ssr";
import { AnimatedHeading } from "./AnimatedHeading";
import { RevealSection } from "./RevealSection";
import { Portfolio3DCardLazy } from "./Portfolio3DCardLazy";

const PROJECTS = [
  {
    name: "ArtingAuto",
    category: "Service auto, București",
    description:
      "Rezervare online și preț anunțat înainte de reparație, pentru un atelier cu peste 5.000 de mașini reparate și rating 5.0 pe Google.",
    href: "https://artingauto.ro",
    image: "/portfolio/artingauto.webp",
  },
  {
    name: "ArtingCoffee",
    category: "Cafea de specialitate, online",
    description:
      "Magazin online pentru cafea gustată intern înainte să ajungă pe site, cu livrare în 24-48h.",
    href: "https://artingcoffee.ro",
    image: "/portfolio/artingcoffee.webp",
  },
];

export function Portfolio() {
  return (
    <section id="portofoliu" className="mx-auto max-w-7xl px-6 py-28 lg:px-8">
      <RevealSection>
        <span className="text-shimmer text-sm font-semibold uppercase tracking-widest">
          Portofoliu
        </span>
        <AnimatedHeading
          text="Site-uri live, nu machete."
          className="mt-4 max-w-xl text-3xl font-bold tracking-tight text-foreground md:text-4xl"
        />
        <p className="mt-4 max-w-xl text-base leading-relaxed text-foreground-muted">
          Fiecare proiect de mai jos rulează live, pentru un client real.
          Design construit pentru conversie, nu doar pentru un portofoliu.
        </p>
      </RevealSection>

      <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-2">
        {PROJECTS.map((project, i) => (
          <RevealSection key={project.name} delay={0.05 + i * 0.05}>
            <a
              href={project.href}
              target="_blank"
              rel="noopener noreferrer"
              className="group block overflow-hidden rounded-3xl border border-border-subtle bg-background-elevated"
            >
              <Portfolio3DCardLazy
                src={project.image}
                alt={`Captură de ecran a site-ului ${project.name}`}
              />
              <div className="p-6 md:p-8">
                <p className="text-shimmer text-xs font-semibold uppercase tracking-widest">
                  {project.category}
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <h3 className="text-xl font-semibold text-foreground">{project.name}</h3>
                  <ArrowUpRight
                    size={16}
                    weight="bold"
                    className="text-foreground-muted transition-transform duration-300 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-brand-cyan"
                  />
                </div>
                <p className="mt-3 leading-relaxed text-foreground-muted">{project.description}</p>
              </div>
            </a>
          </RevealSection>
        ))}
      </div>
    </section>
  );
}
