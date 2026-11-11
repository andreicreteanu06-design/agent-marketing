import Image from "next/image";

export type ServiceVisualVariant = "ppc" | "web" | "automations";

const VISUALS = {
  ppc: {
    src: "/higgsfield-precision-aperture.webp",
    alt: "Discuri de precizie din titan și sticlă fumurie suspendate în jurul unui nucleu mat",
  },
  web: {
    src: "/higgsfield-web-prism.webp",
    alt: "Prismă arhitecturală din sticlă fumurie și titan, randată pentru Web Design",
  },
  automations: {
    src: "/higgsfield-automation-titanium.webp",
    alt: "Structură fluidă din titan în jurul unui nucleu ceramic, randată pentru Automatizări AI",
  },
} as const;

/** Randări Higgsfield: materialitate 3D, fără un canvas WebGL activ pe pagina de serviciu. */
export function ServiceVisual3D({ variant, priority = true }: { variant: ServiceVisualVariant; priority?: boolean }) {
  const visual = VISUALS[variant];

  return (
    <div className={`service-object service-object--${variant}`}>
      <span className="service-object__halo" aria-hidden="true" />
      <Image
        src={visual.src}
        alt={visual.alt}
        fill
        priority={priority}
        sizes="(max-width: 1024px) 100vw, 45vw"
        className="service-object__image object-contain"
      />
      <span className="service-object__reflection" aria-hidden="true" />
    </div>
  );
}
