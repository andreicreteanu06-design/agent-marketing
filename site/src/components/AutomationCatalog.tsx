"use client";

import Link from "next/link";
import { useId, useRef, useState, type CSSProperties } from "react";
import { useInView } from "motion/react";
import { ArrowUpRight, CheckCircle, GitBranch, Lightning, Sparkle, UserCircle } from "@phosphor-icons/react/dist/ssr";
import { AnimatedHeading } from "./AnimatedHeading";
import { WORKFLOWS, type Workflow, type WorkflowNode } from "@/lib/workflows";

const LABELS: Record<string, string> = { leaduri: "Răspuns la lead-uri", facturi: "Urmărirea facturilor", suport: "Răspuns la emailuri", continut: "O idee, patru canale", onboarding: "Primirea clienților", cv: "Traseul candidaturilor", comenzi: "Confirmarea comenzilor", stoc: "Alertă de stoc", reviewuri: "Cerere de review" };
const DEPARTMENTS = ["Toate", ...new Set(WORKFLOWS.map(w => w.department))];
const NODE_ICONS = { trigger: Lightning, decision: GitBranch, human: UserCircle, result: CheckCircle };

function WorkflowGraph({ workflow, selected, onSelect, detailId }: { workflow: Workflow; selected: string; onSelect: (id: string) => void; detailId: string }) {
  const ref = useRef<HTMLElement>(null);
  const visible = useInView(ref, { amount: .15 });
  const marker = useId().replace(/:/g, "");
  const height = workflow.rows.length * 106 + 8;
  const points = new Map(workflow.rows.flatMap((row, r) => row.map((node, i) => [node.id, { x: (i + .5) * 1000 / row.length, y: 12 + r * 106 }] as const)));
  return <figure ref={ref} className={"workflow-figure " + (visible ? "is-visible" : "")} aria-label={"Diagrama: " + LABELS[workflow.id]}>
    <div className="workflow-graph" style={{ height }}>
      <svg viewBox={`0 0 1000 ${height}`} preserveAspectRatio="none" aria-hidden="true" className="workflow-wires">
        <defs><marker id={marker} markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7" fill="#88b5ce" /></marker></defs>
        {workflow.edges.map(([a,b]) => {
          const from = points.get(a)!; const to = points.get(b)!;
          const mid = (from.y + 76 + to.y) / 2;
          const d = `M${from.x},${from.y+76} C${from.x},${mid} ${to.x},${mid} ${to.x},${to.y-3}`;
          return <g key={a+b}><path d={d} className="workflow-wire" markerEnd={`url(#${marker})`} /><path d={d} className="workflow-signal" /></g>;
        })}
      </svg>
      {workflow.rows.map((row, r) => <div className={"workflow-row " + (row.length > 1 ? "workflow-row--branch" : "")} key={r}>
        {row.length > 1 && <span className="workflow-mobile-branch">{workflow.id === "continut" ? "Patru adaptări" : ["comenzi", "stoc"].includes(workflow.id) ? "Acțiuni în paralel" : "În funcție de situație"}</span>}
        {row.map(node => {
          const point = points.get(node.id)!; const Icon = node.kind ? NODE_ICONS[node.kind] : Sparkle;
          return <button key={node.id} type="button" className={"workflow-node workflow-node--" + (node.kind ?? "action")} style={{ left: point.x / 10 + "%", top: point.y, "--node-width": row.length === 4 ? "23%" : "29%" } as CSSProperties} aria-pressed={selected === node.id} aria-controls={detailId} onClick={() => onSelect(node.id)}>
            <Icon size={20} weight="duotone" aria-hidden="true" /><span><small>{node.label}</small><strong>{node.title}</strong></span>
          </button>;
        })}
      </div>)}
    </div>
    <figcaption>Alege un pas pentru explicație. Diagramă simplificată a procesului; selectarea pașilor nu rulează automatizarea.</figcaption>
  </figure>;
}

export function AutomationCatalog() {
  const [department, setDepartment] = useState("Toate");
  const [workflowId, setWorkflowId] = useState(WORKFLOWS[0].id);
  const [nodeId, setNodeId] = useState("in");
  const panelId = useId();
  const detailId = useId();
  const filtered = WORKFLOWS.filter(w => department === "Toate" || w.department === department);
  const workflow = filtered.find(w => w.id === workflowId) ?? filtered[0];
  const nodes = workflow.rows.flat();
  const node: WorkflowNode = nodes.find(n => n.id === nodeId) ?? nodes[0];

  return <section id="automatizari" className="automation-catalog mx-auto max-w-7xl px-6 lg:px-8" aria-labelledby="automation-catalog-title">
    <div className="automation-catalog__intro">
      <div id="automation-catalog-title"><AnimatedHeading text={"Mai clar când\nvezi întregul flux."} className="section-display" /></div>
      <p className="section-description">Nouă automatizări, explicate pas cu pas. Vezi ce pornește fiecare flux, unde intervine un coleg și cum se păstrează rezultatul direct în AC Media.</p>
    </div>
    <div className="workflow-filters" role="group" aria-label="Filtrează după departament">{DEPARTMENTS.map(d => <button key={d} type="button" aria-pressed={department === d} onClick={() => { setDepartment(d); setNodeId("in"); }}>{d}</button>)}</div>
    <div className="workflow-explorer">
      <aside className="workflow-picker" aria-label="Alege automatizarea">
        <p>{filtered.length} {filtered.length === 1 ? "automatizare" : "automatizări"}</p>
        {filtered.map(w => <button key={w.id} type="button" aria-pressed={workflow.id === w.id} aria-controls={panelId} onClick={() => { setWorkflowId(w.id); setNodeId("in"); }}><span><small>{w.department}</small><strong>{LABELS[w.id]}</strong></span><ArrowUpRight size={17} aria-hidden="true" /></button>)}
      </aside>
      <div id={panelId} className="workflow-stage">
        <div className="workflow-stage__intro"><span>{workflow.department}</span><h3>{workflow.title}</h3><p>{workflow.summary}</p></div>
        <div className="workflow-tools" aria-label="Instrumentele fluxului">{workflow.tools.map(tool => <span key={tool}>{tool}</span>)}</div>
        <WorkflowGraph key={workflow.id} workflow={workflow} selected={node.id} onSelect={setNodeId} detailId={detailId} />
        <div id={detailId} className="workflow-explanation" aria-live="polite"><span>Pasul selectat</span><h4>{node.title}</h4><p>{node.detail}</p></div>
        <div className="workflow-outcome"><div><h4>Ce obții</h4><p>{workflow.outcome}</p></div><div><h4>Control și configurare</h4><p>{workflow.control}</p></div></div>
        <Link href={`/cont/automatizari?flux=${workflow.id}`} className="enterprise-button workflow-native-link">Configurează în cont <ArrowUpRight size={18} /></Link>
        <Link href="/#programeaza" className="enterprise-text-link workflow-cta">Discutăm acest flux pentru echipa ta <ArrowUpRight size={18} /></Link>
      </div>
    </div>
  </section>;
}
