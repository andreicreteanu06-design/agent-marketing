"use client";

import { MaterialSurface } from "./MaterialSurface";

import Image from "next/image";
import Link from "next/link";
import { useState, type KeyboardEvent, type CSSProperties } from "react";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import { ArrowUpRight, ShieldCheck, ArrowRight } from "@phosphor-icons/react";
import { RevealSection } from "./RevealSection";

const members = [
  { title: "CMO", field: "Strategie", detail: "Definește publicul și mesajul.", note: "O direcție pentru fiecare campanie.", angle: -4 },
  { title: "CFO", field: "Rentabilitate", detail: "Verifică propunerile în raport cu bugetul.", note: "Fiecare propunere trece prin cifre.", angle: 2 },
  { title: "CTO", field: "Infrastructură", detail: "Validează trackingul și poate opri o decizie.", note: "Date corecte înainte de orice decizie.", angle: 6 },
  { title: "CPO", field: "Ofertă", detail: "Evaluează poziționarea și potrivirea cu piața.", note: "Oferta potrivită, pentru publicul potrivit.", angle: -1 },
  { title: "CSO", field: "Context", detail: "Aduce date despre piață și concurență.", note: "Perspectivă dincolo de propriile campanii.", angle: -6 },
] as const;
const MODULE_CENTERS = [[47, 24], [71, 38], [70, 64], [46, 68], [30, 42]] as const;

export function CouncilExperience() {
  const [active, setActive] = useState(0);
  const reduce = useReducedMotion();
  const spring = reduce ? { duration: 0 } : { type: "spring" as const, stiffness: 280, damping: 34, mass: 1 };
  const member = members[active];

  function navigate(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === "ArrowDown" || event.key === "ArrowRight") next = (index + 1) % members.length;
    else if (event.key === "ArrowUp" || event.key === "ArrowLeft") next = (index + members.length - 1) % members.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = members.length - 1;
    else return;
    event.preventDefault();
    setActive(next);
    document.getElementById(`council-tab-${next}`)?.focus();
  }

  return <LayoutGroup id="executive-council"><RevealSection className="council-experience">
    <MaterialSurface className="council-theatre" role="tabpanel" id="council-panel" aria-labelledby={`council-tab-${active}`}>
      <div className="council-theatre__aura" aria-hidden="true" />
      <div className="council-theatre__orbit council-theatre__orbit--outer" aria-hidden="true"><i /></div>
      <div className="council-theatre__orbit council-theatre__orbit--inner" aria-hidden="true"><i /></div>
      <span className="council-theatre__watermark" key={member.title} aria-hidden="true">{member.title}</span>
      <motion.div className="council-theatre__object" initial={false} animate={{ rotate: member.angle, x: (active - 2) * 3 }} transition={spring}>
        <div className="council-theatre__figure">
        <Image src="/higgsfield-executive-sculpture.webp" alt="Cinci module din titan și ceramică în jurul unui nucleu de sticlă" fill sizes="(max-width: 860px) 90vw, 52vw" className="object-contain" />
        {members.map((item, index) => <span key={item.title} className={"council-module-light" + (active === index ? " is-active" : "")} aria-hidden="true" style={{ "--module-x": MODULE_CENTERS[index][0] + "%", "--module-y": MODULE_CENTERS[index][1] + "%" } as CSSProperties} />)}
        </div>
      </motion.div>
      <div className="council-satellites" aria-hidden="true">
        {members.map((item, index) => <span key={item.title} className={`council-satellite council-satellite--${index} ${active === index ? "is-active" : ""}`}><i />{item.title}</span>)}
      </div>
      <div className="council-theatre__notes">
        {members.map((item, index) => <motion.div key={item.title} className="council-theatre__note" aria-hidden={active !== index} initial={false} animate={{ opacity: active === index ? 1 : 0, y: active === index ? 0 : 8 }} transition={reduce ? { duration: 0 } : { duration: 0.18 }}><span>{item.field}</span><p>{item.note}</p></motion.div>)}
      </div>
      <div className="council-theatre__caption"><ShieldCheck size={17} /> Inteligență conectată. Control uman.</div>
    </MaterialSurface>
    <div className="council-selector">
      <p className="council-selector__hint">Explorează cele cinci perspective <ArrowRight size={14} /></p>
      <div role="tablist" aria-label="Rolurile consiliului AI" aria-orientation="vertical">
        {members.map((item, index) => <button type="button" role="tab" key={item.title} id={`council-tab-${index}`} aria-controls="council-panel" aria-selected={active === index} tabIndex={active === index ? 0 : -1} onClick={() => setActive(index)} onKeyDown={event => navigate(event, index)} className="council-tab">
          <span className="council-tab__role">{item.title}</span>
          {active === index && <motion.span className="council-tab__selection" layoutId="council-selection" transition={spring} aria-hidden="true"><i /></motion.span>}
          <span className="council-tab__copy"><strong>{item.field}</strong><span>{item.detail}</span></span>
          <ArrowUpRight className="council-tab__arrow" size={18} />
        </button>)}
      </div>
      <Link href="/cont/regina" className="enterprise-text-link council-link">Descoperă consiliul <ArrowUpRight size={18} /></Link>
    </div>
  </RevealSection></LayoutGroup>;
}
