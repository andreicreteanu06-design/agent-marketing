import type { Metadata } from "next";
import { ArrowDown, PlugsConnected, ShieldCheck } from "@phosphor-icons/react/dist/ssr";
import { AnimatedHeading } from "@/components/AnimatedHeading";
import { Footer } from "@/components/Footer";
import { McpConnectionPanel } from "@/components/McpConnectionPanel";
import { MaterialSurface } from "@/components/MaterialSurface";

export const metadata: Metadata = { title: "Conectează AI prin MCP: AC Media", description: "Conectează Codex sau Claude Code la datele contului AC Media, printr-o cheie MCP dedicată." };
const CAPABILITIES = [
  ["Bugetul, într-o privire", "Citește plafonul zilnic, bugetul deja angajat și spațiul disponibil."],
  ["PPC și organic, împreună", "Identifică termenii pentru care plătești deși ai deja o poziție organică bună."],
  ["Oportunități de conținut", "Găsește termenii care convertesc în reclame și au vizibilitate organică slabă."],
  ["Propuneri de buget", "Pregătește schimbări argumentate, care așteaptă aprobarea ta în platformă."],
  ["Feedback despre creative", "Înregistrează rezultatele creativelor pentru a îmbunătăți recomandările viitoare."],
  ["Lecții din rezultate", "Consultă observațiile acumulate din performanța creativelor contului."],
];
export default function McpPage() {
  return <><main className="mcp-page mx-auto max-w-7xl px-6 lg:px-8">
    <section className="mcp-hero">
      <div><AnimatedHeading as="h1" text={"Agentul tău AI.\nContextul afacerii tale."} className="section-display" /><p className="section-description">Conectează Codex sau Claude Code la AC Media. Discută despre bugete, campanii și oportunități folosind datele contului tău.</p><a href="#conectare" className="enterprise-button">Configurează conexiunea <ArrowDown size={18} /></a></div>
      <MaterialSurface className="mcp-bridge" aria-label="Agent AI conectat prin MCP la contul AC Media"><div className="mcp-bridge__agents"><span>Codex</span><span>Claude Code</span></div><i /><div className="mcp-bridge__core"><PlugsConnected size={38} weight="duotone" /><strong>MCP</strong><span>O conexiune comună</span></div><i /><div className="mcp-bridge__account"><ShieldCheck size={22} /><span>Contul tău AC Media</span></div></MaterialSurface>
    </section>
    <McpConnectionPanel />
    <section className="mcp-capabilities" aria-labelledby="mcp-capabilities-title"><h2 id="mcp-capabilities-title">Ce poate face agentul conectat.</h2><div>{CAPABILITIES.map(([title,body])=><article key={title}><h3>{title}</h3><p>{body}</p></article>)}</div></section>
  </main><Footer /></>;
}
