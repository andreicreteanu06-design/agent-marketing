import Image from "next/image";
import type { CSSProperties } from "react";
import { ArrowRight, Check, EnvelopeSimple, Folders, ShieldCheck, UserCheck } from "@phosphor-icons/react/dist/ssr";

/** Illustrative service presentations. They never read or change campaign data. */
export function ServiceShowcase({ variant }: { variant: "ppc" | "web" | "automations" }) {
  if (variant === "ppc") return <div className="decision-exhibit">
    <div className="decision-exhibit__material"><Image src="/higgsfield-precision-aperture.webp" alt="" fill sizes="340px" /></div>
    <div className="decision-exhibit__sheet">
      <div className="decision-exhibit__top"><span>O decizie explicată</span><span>Exemplu</span></div>
      <div className="decision-exhibit__comparison">
        <div><span>Cost / conversie</span><strong>42 <small>lei</small></strong><i><b /></i></div>
        <div><span>Ținta stabilită</span><strong>50 <small>lei</small></strong><i><b /></i></div>
      </div>
      <div className="decision-exhibit__reason"><Check size={18} /><p>Costul este sub țintă.<br /><strong>Un test controlat poate fi evaluat.</strong></p></div>
      <div className="decision-exhibit__approval"><ShieldCheck size={18} /><span>Orice schimbare începe cu acordul tău.</span></div>
    </div>
  </div>;

  if (variant === "web") return <div className="web-exhibit">
    <div className="web-exhibit__window">
      <div className="web-exhibit__bar"><span><i /><i /><i /></span><span>artingcoffee.ro</span><ArrowRight size={14} /></div>
      <Image src="/portfolio/artingcoffee.webp" alt="" width={1400} height={735} sizes="(max-width: 860px) 90vw, 750px" className="web-exhibit__capture" />
    </div>
    <div className="web-exhibit__type"><span>Din proiectul ArtingCoffee</span><p>Identitate.<br /><em>Până în ultimul detaliu.</em></p><span className="web-exhibit__swatches"><i /><i /><i /><b>Ton · Ritm · Contrast</b></span></div>
  </div>;

  const steps = [
    { icon: EnvelopeSimple, title: "Solicitarea intră", detail: "Formularul de pe site" },
    { icon: Folders, title: "Datele se organizează", detail: "Informația ajunge în CRM" },
    { icon: ShieldCheck, title: "Contextul se verifică", detail: "Echipa primește un rezumat" },
    { icon: UserCheck, title: "Tu alegi următorul pas", detail: "Aprobi răspunsul propus" },
  ];
  return <div className="flow-exhibit">
    <Image src="/higgsfield-automation-titanium.webp" alt="" fill sizes="500px" className="flow-exhibit__material" />
    <ol className="flow-exhibit__steps">{steps.map((step, index) => <li key={step.title} style={{ "--flow-step": index } as CSSProperties}>
      <span className="flow-exhibit__icon"><step.icon size={22} weight="duotone" /></span>
      <div><strong>{step.title}</strong><span>{step.detail}</span></div>
      <span className="flow-exhibit__signal" />
    </li>)}</ol>
    <p className="flow-exhibit__caption">Un posibil flux, adaptat echipei tale.</p>
  </div>;
}
