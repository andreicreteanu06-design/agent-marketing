import Link from "next/link";
import { ArrowUpRight, MagnifyingGlass, GlobeHemisphereWest, Files, Sparkle } from "@phosphor-icons/react/dist/ssr";
import { AnimatedHeading } from "./AnimatedHeading";
import { RevealSection } from "./RevealSection";
import { SpotlightCard } from "./SpotlightCard";

const checks = [
  { icon: GlobeHemisphereWest, title: "Acces & indexare", text: "robots.txt, sitemap și linkuri interne", kind: "SEO" },
  { icon: Files, title: "Conținut & structură", text: "Titluri, meta descriptions și conținut duplicat", kind: "SEO" },
  { icon: Sparkle, title: "Vizibilitate în răspunsurile AI", text: "Citabilitate în ChatGPT, Perplexity și AI Overviews", kind: "GEO" },
];
export function SeoGeoPreview() {
  return <section className="audit-preview mx-auto max-w-7xl px-6 py-24 lg:px-8 lg:py-32">
    <RevealSection>
      <AnimatedHeading text="Claritate, înainte de următoarea decizie." className="section-display max-w-xl" />
      <p className="section-description mt-7">Un audit SEO + GEO care citește site-ul pagină cu pagină. Primești problemele exacte, URL-urile afectate și valorile măsurate, într-un singur raport.</p>
      <Link href="/creeaza-cont" className="enterprise-text-link mt-8 text-sm">Rulează primul audit <ArrowUpRight size={18} /></Link>
    </RevealSection>
    <RevealSection delay={0.08}>
      <SpotlightCard className="premium-panel audit-report">
        <div className="audit-report__header"><MagnifyingGlass size={22} /><h3>Ce verifică raportul tău</h3></div>
        <div className="audit-report__checks">{checks.map(check => <div className="audit-report__row" key={check.title}><check.icon size={20} /><div><h3>{check.title}</h3><p>{check.text}</p></div><span>{check.kind}</span></div>)}</div>
        <div className="audit-report__footer"><p>Pornește cu domeniul tău.</p><Link href="/creeaza-cont" className="enterprise-button px-4 py-3">Creează cont <ArrowUpRight size={16} /></Link></div>
      </SpotlightCard>
    </RevealSection>
  </section>;
}
