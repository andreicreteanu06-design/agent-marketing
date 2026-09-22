import { ChartLineUp, PaintBrush, Robot } from "@phosphor-icons/react/dist/ssr";
import type { Icon } from "@phosphor-icons/react";

export type ServiceVisualVariant = "ppc" | "web" | "automations";

export interface ServiceStep {
  title: string;
  body: string;
}

export interface ServiceDetail {
  slug: string;
  variant: ServiceVisualVariant;
  icon: Icon;
  eyebrow: string;
  title: string;
  cardBody: string[];
  subtitle: string;
  howItWorks: ServiceStep[];
  benefits: ServiceStep[];
}

// Continut canonic pentru cele trei servicii - folosit atat de cardurile de
// pe homepage (Services.tsx) cat si de paginile dedicate (/servicii/[slug]),
// ca sa nu existe doua surse de adevar pentru acelasi text.
export const SERVICES: ServiceDetail[] = [
  {
    slug: "ppc",
    variant: "ppc",
    icon: ChartLineUp,
    eyebrow: "Serviciu 01",
    title: "Management PPC cu agent AI",
    cardBody: [
      "Alocare de buget prin Thompson Sampling, dimensionare Kelly Criterion după ROAS și monitorizare a oboselii creative, pe Google, Meta, TikTok și ChatGPT Ads.",
      "Fiecare modificare trece printr-o poartă de aprobare umană înainte să ajungă pe cont. Nimic nu se schimbă singur, fără confirmarea ta.",
    ],
    subtitle:
      "Un agent care alocă bugetul zilnic pe baza performanței reale, nu pe reguli fixe scrise acum un an. Tu aprobi fiecare schimbare majoră, nu doar te uiți la un raport lunar.",
    howItWorks: [
      {
        title: "Conectezi conturile",
        body: "Google Ads, Meta Ads, TikTok Ads și acum ChatGPT Ads se conectează o singură dată, prin chei API criptate. Agentul citește performanța la nivel de campanie și creativă.",
      },
      {
        title: "Agentul propune, tu aprobi",
        body: "Realocări de buget prin Thompson Sampling, dimensionare prin Kelly Criterion după ROAS. Fiecare propunere ajunge la tine înainte să se aplice pe cont.",
      },
      {
        title: "Monitorizare continuă",
        body: "Oboseala creativelor e detectată automat, nu descoperită după ce bugetul s-a dus pe un anunț obosit de o săptămână.",
      },
    ],
    benefits: [
      {
        title: "Decizii pe date, nu pe intuiție",
        body: "Alocarea de buget urmează performanța reală a fiecărui canal, actualizată zilnic.",
      },
      {
        title: "Control, nu automatizare oarbă",
        body: "Nimic nu se schimbă pe cont fără aprobarea ta explicită.",
      },
      {
        title: "Un singur loc pentru toate canalele",
        body: "Google, Meta, TikTok și ChatGPT Ads gestionate din aceeași logică, nu instrumente separate.",
      },
    ],
  },
  {
    slug: "web-design",
    variant: "web",
    icon: PaintBrush,
    eyebrow: "Serviciu 02",
    title: "Web design",
    cardBody: [
      "Site-uri rapide, construite pentru conversie. Fiecare pagină susține direct campaniile de PPC, nu lucrează separat de ele.",
    ],
    subtitle:
      "Site-uri construite pentru conversie, nu doar pentru portofoliu. Fiecare pagină e gândită să susțină campaniile de PPC care trimit trafic către ea.",
    howItWorks: [
      {
        title: "Pornim de la obiectivul campaniei",
        body: "Pagina de destinație e construită pentru acțiunea pe care o cere campania (formular, apel, comandă), nu un site generic.",
      },
      {
        title: "Viteză, nu doar aspect",
        body: "Cod curat, imagini optimizate, fără librării inutile. O pagină lentă costă conversii, indiferent cât de bine arată.",
      },
      {
        title: "Livrare, apoi măsurare",
        body: "După lansare, urmărim cum se comportă pagina în campanii reale și ajustăm ce nu convertește.",
      },
    ],
    benefits: [
      {
        title: "Legat direct de PPC",
        body: "Pagina de destinație și campania sunt construite împreună, nu în paralel.",
      },
      {
        title: "Fără șabloane reciclate",
        body: "Fiecare site pornește de la brandul și oferta reală a clientului.",
      },
      {
        title: "Portofoliu verificabil",
        body: "artingauto.ro și artingcoffee.ro rulează live, pentru clienți reali.",
      },
    ],
  },
  {
    slug: "automatizari",
    variant: "automations",
    icon: Robot,
    eyebrow: "Serviciu 03",
    title: "Automatizări AI",
    cardBody: [
      "Lead-uri răspunse în minute, nu zile. Facturi restante urmărite automat, nu uitate într-un Excel. Fluxuri construite pe măsura departamentului tău, nu un șablon generic.",
    ],
    subtitle:
      "Fluxuri care preiau task-urile repetitive din departamentul tău: lead-uri, facturi restante, follow-up-uri. Construite pe măsura procesului tău, nu un șablon generic.",
    howItWorks: [
      {
        title: "Mapăm procesul actual",
        body: "Pornim de la ce faci manual acum (Excel, e-mailuri, follow-up telefonic) și identificăm ce se poate prelua fără risc.",
      },
      {
        title: "Construim fluxul",
        body: "Automatizarea rulează pe infrastructura ta (n8n self-hosted), fără să depindă de un abonament extern care poate dispărea.",
      },
      {
        title: "Om în buclă unde contează",
        body: "Pentru decizii sensibile, cum ar fi filtrarea CV-urilor, fluxul cere validare umană, nu decide singur.",
      },
    ],
    benefits: [
      {
        title: "Timp de răspuns în minute",
        body: "Lead-urile primesc primul răspuns automat, nu așteaptă până dimineață.",
      },
      {
        title: "Nimic uitat într-un Excel",
        body: "Facturi restante, follow-up-uri și task-uri repetitive urmărite automat.",
      },
      {
        title: "Construit pe măsură",
        body: "Fluxul respectă procesul real al departamentului tău, nu invers.",
      },
    ],
  },
];

export function getServiceBySlug(slug: string): ServiceDetail | undefined {
  return SERVICES.find((service) => service.slug === slug);
}
