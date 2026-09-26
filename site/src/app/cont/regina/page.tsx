import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, Crown } from "@phosphor-icons/react/dist/ssr";
import { QueenChat } from "@/components/queen/QueenChat";

export const metadata: Metadata = {
  title: "Regina, CMO-ul tău: AC Media Marketing",
  description:
    "Întreab-o pe Regina orice despre campaniile tale - răspunde după ce își consultă consiliul.",
};

const COUNCIL = [
  "Regina · strategie de brand",
  "CFO · rentabilitate",
  "Tehnician · tracking și viteză",
  "Researcher · piață",
  "Decizie deterministă",
];

/**
 * Chatul cu Regina (agentul CMO). O interfata de lucru, ca modulul SEO + GEO:
 * fara footer-ul de marketing - conversatia ocupa ecranul.
 */
export default function QueenPage() {
  return (
    <main className="mx-auto max-w-4xl px-6 pb-10 pt-28 lg:px-8">
      <Link
        href="/cont"
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-foreground-muted hover:text-foreground"
      >
        <ArrowLeft size={14} />
        Contul meu
      </Link>

      <header className="mb-6">
        <div className="flex items-center gap-3.5">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-blue to-brand-cyan/80 p-px">
            <span className="flex h-full w-full items-center justify-center rounded-2xl bg-background-elevated">
              <Crown size={22} weight="duotone" className="text-brand-cyan" />
            </span>
          </span>
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-foreground">Regina</h1>
            <p className="text-sm text-foreground-muted">
              CMO-ul tău AI. Răspunde abia după ce își consultă consiliul.
            </p>
          </div>
        </div>
        <ul className="mt-4 flex flex-wrap gap-1.5">
          {COUNCIL.map((seat) => (
            <li
              key={seat}
              className="rounded-full border border-border-subtle bg-white/[0.02] px-2.5 py-1 text-[11px] text-foreground-muted"
            >
              {seat}
            </li>
          ))}
        </ul>
      </header>

      <QueenChat />
    </main>
  );
}
