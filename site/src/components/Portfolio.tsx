import Image from "next/image";
import { ArrowUpRight } from "@phosphor-icons/react/dist/ssr";
import { AnimatedHeading } from "./AnimatedHeading";
import { RevealSection } from "./RevealSection";

const PROJECTS = [
  {
    name: "ArtingAuto",
    category: "Servicii auto · București",
    headline: "Încredere, de la primul contact.",
    description: "Serviciile, modul de lucru și programarea au un traseu clar. O identitate directă, construită în jurul atelierului.",
    detail: "Programarea și accesul la servicii sunt vizibile din primul ecran.",
    tags: ["Ierarhie clară", "Programare la îndemână"],
    href: "https://artingauto.ro",
    domain: "artingauto.ro",
    image: "/portfolio/artingauto.webp",
    theme: "auto",
    width: 1400,
    height: 757,
  },
  {
    name: "ArtingCoffee",
    category: "Cafea de specialitate · E-commerce",
    headline: "O experiență cu gust propriu.",
    description: "Tipografie editorială, tonuri calde și o prezentare amplă a cafelei. Povestea brandului conduce natural spre produse.",
    detail: "Două puncte de intrare: explorează cafeaua sau descoperă cum este aleasă.",
    tags: ["Direcție editorială", "Descoperirea produselor"],
    href: "https://artingcoffee.ro",
    domain: "artingcoffee.ro",
    image: "/portfolio/artingcoffee.webp",
    theme: "coffee",
    width: 1400,
    height: 735,
  },
] as const;

export function Portfolio() {
  return (
    <section id="portofoliu" className="portfolio-section marketing-section mx-auto max-w-7xl px-6 py-28 lg:px-8" aria-labelledby="portfolio-title">
      <RevealSection className="portfolio-intro">
        <div id="portfolio-title">
          <AnimatedHeading text={"Idei clare.\nExperiențe reale."} className="section-display" />
        </div>
        <p className="section-description">Două afaceri, două identități distincte. Același respect pentru detalii și pentru oamenii care le folosesc.</p>
      </RevealSection>
      <div className="portfolio-projects">
        {PROJECTS.map((project, index) => (
          <RevealSection key={project.name} className={"portfolio-project portfolio-project--" + project.theme}>
            <div className="portfolio-project__header">
              <div><h3>{project.name}</h3></div>
              <span className="portfolio-project__category">{project.category}</span>
            </div>
            <a href={project.href} target="_blank" rel="noopener noreferrer" className="portfolio-project__visual" aria-label={"Deschide " + project.name + " într-o filă nouă"}>
              <div className="portfolio-browser">
                <div className="portfolio-browser__chrome" aria-hidden="true"><span><i /><i /><i /></span><span>{project.domain}</span><ArrowUpRight size={14} /></div>
                <Image src={project.image} alt={"Captură reală a paginii principale " + project.name} width={project.width} height={project.height} sizes="(max-width: 860px) 100vw, 1100px" className="portfolio-browser__capture" />
              </div>
              <span className="portfolio-project__open"><ArrowUpRight size={22} /><span>Explorează site-ul</span></span>
            </a>
            <div className="portfolio-project__story">
              <div><h4>{project.headline}</h4><p>{project.description}</p></div>
              <div className="portfolio-project__decisions"><span>În detaliu</span><p>{project.detail}</p><ul>{project.tags.map(tag => <li key={tag}>{tag}</li>)}</ul></div>
            </div>
            {index === 0 && <div className="portfolio-case">
              <div className="portfolio-case__brief"><h4>De la interes<br />la programare.</h4><div><h5>Obiectivul experienței</h5><p>Vizitatorul înțelege ce oferă atelierul și găsește imediat următorul pas: o programare sau o privire asupra serviciilor.</p></div></div>
              <div className="portfolio-case__details">
                <figure><div className="portfolio-detail portfolio-detail--identity"><Image src={project.image} alt="Detaliu din ArtingAuto: titlul și identitatea atelierului" width={1400} height={757} sizes="1000px" /></div><figcaption><strong>Un mesaj cu personalitate.</strong><span>Titlul, accentul roșu și fotografia vorbesc aceeași limbă.</span></figcaption></figure>
                <figure><div className="portfolio-detail portfolio-detail--action"><Image src={project.image} alt="Detaliu din ArtingAuto: butonul de programare și accesul la servicii" width={1400} height={757} sizes="1000px" /></div><figcaption><strong>Următorul pas, la vedere.</strong><span>Programarea are prioritate; explorarea serviciilor rămâne aproape.</span></figcaption></figure>
              </div>
              <div className="portfolio-case__scope"><span>Ce poți vedea în proiect</span><p>Identitate vizuală <i /> Ierarhie de conținut <i /> Traseu spre programare</p><span>Detalii din captura desktop</span></div>
            </div>}
          </RevealSection>
        ))}
      </div>
    </section>
  );
}
