"use client";

import { useId, useRef, useState, type KeyboardEvent } from "react";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import { ArrowRight, Check, Crown, ShieldCheck, ArrowCounterClockwise } from "@phosphor-icons/react";
import { Badge } from "@/components/ui/badge";
import { MaterialSurface } from "./MaterialSurface";

const STEPS = ["Date", "Consiliu", "Aprobare"] as const;
const SPRING = { type: "spring" as const, stiffness: 420, damping: 41, mass: 1 };

/** An illustrative UI only. No account, budget or API is connected to this demo. */
export function HeroProductDemo() {
  const [step, setStep] = useState(0);
  const [approved, setApproved] = useState(false);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const id = useId();
  const reduce = useReducedMotion();

  function navigate(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % STEPS.length;
    else if (event.key === "ArrowLeft") next = (index + STEPS.length - 1) % STEPS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = STEPS.length - 1;
    else return;
    event.preventDefault();
    setStep(next);
    tabs.current[next]?.focus();
  }

  return (
    <LayoutGroup id={id}>
      <MaterialSurface className="product-demo" aria-label="Exemplu interactiv al unei decizii de marketing">
        <div className="product-demo__chrome">
          <span className="product-demo__identity"><Crown size={16} weight="duotone" /> Regina <span>/ Consiliul AI</span></span>
          <span className="product-demo__sample">Date exemplu</span>
        </div>
        <div className="product-demo__steps" role="tablist" aria-label="Etapele demonstrației">
          {STEPS.map((label, index) => (
            <button key={label} ref={node => { tabs.current[index] = node; }} type="button" role="tab"
              id={id + "-step-" + index} aria-controls={id + "-panel"} aria-selected={step === index}
              tabIndex={step === index ? 0 : -1} onClick={() => setStep(index)} onKeyDown={event => navigate(event, index)}>
              {step === index && <motion.span className="product-demo__step-indicator" layoutId="step" transition={reduce ? { duration: 0 } : SPRING} />}
              <span className="product-demo__step-number">{index < step ? <Check size={10} weight="bold" /> : "0" + (index + 1)}</span>
              <span>{label}</span>
            </button>
          ))}
        </div>
        <div className="product-demo__panel" id={id + "-panel"} role="tabpanel" aria-labelledby={id + "-step-" + step}>
          <motion.div key={step} initial={reduce ? false : { opacity: 0, y: 7 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: reduce ? 0 : 0.2, ease: [0.22, 1, 0.36, 1] }} className="product-demo__scene">
            {step === 0 && <>
              <h2>„Merită să cresc bugetul?”</h2>
              <p className="product-demo__explanation">O decizie bună începe cu datele potrivite.</p>
              <div className="product-demo__metrics">
                <div><span>Cost / conversie</span><strong>42 <small>lei</small></strong></div>
                <div><span>Țintă CPA</span><strong>50 <small>lei</small></strong></div>
                <div><span>Conversii</span><strong>128</strong></div>
              </div>
              <div className="product-demo__data-note"><span /> Date ilustrative · 30 de zile</div>
            </>}
            {step === 1 && <>
              <h2>Mai întâi, contextul complet.</h2>
              <div className="product-demo__opinions">
                <div><span>CFO</span><p>Costul este sub țintă.</p><Check size={15} /></div>
                <div><span>CTO</span><p>Tracking valid în exemplu.</p><Check size={15} /></div>
                <div><span>CMO</span><p>Propune un test controlat.</p><Check size={15} /></div>
              </div>
              <p className="product-demo__data-note">CPO: ofertă · CSO: contextul pieței</p>
            </>}
            {step === 2 && <>
              <h2>Tu ai ultimul cuvânt.</h2>
              <div className="product-demo__proposal">
                <div><span>Buget zilnic · exemplu</span><strong>300 <ArrowRight size={16} /> <span>330 <small>lei</small></span></strong></div>
                <span className="product-demo__delta">+10%</span>
              </div>
              <Badge variant={approved ? "success" : "warning"} className="product-demo__badge">
                {approved ? "Aprobare simulată" : "Așteaptă aprobarea ta"}
              </Badge>
              <p className="product-demo__data-note">Demonstrație locală. Nicio campanie nu este modificată.</p>
            </>}
          </motion.div>
        </div>
        <div className="product-demo__footer">
          <span className="product-demo__safety"><ShieldCheck size={15} /> Control uman</span>
          <motion.button type="button" className="product-demo__action" whileTap={reduce ? undefined : { scale: 0.97 }}
            onClick={() => {
              if (step < 2) setStep(step + 1);
              else if (!approved) setApproved(true);
              else { setApproved(false); setStep(0); }
            }}>
            {step === 0 ? "Vezi analiza" : step === 1 ? "Vezi propunerea" : approved ? "Reia exemplul" : "Simulează aprobarea"}
            {approved && step === 2 ? <ArrowCounterClockwise size={15} /> : <ArrowRight size={15} />}
          </motion.button>
        </div>
        <span className="sr-only" role="status">{step === 2 && approved ? "Aprobarea a fost simulată. Nicio campanie reală nu a fost modificată." : ""}</span>
      </MaterialSurface>
      <div className="product-demo__caption" aria-hidden="true"><span /> De la întrebare la o decizie explicabilă.</div>
    </LayoutGroup>
  );
}
