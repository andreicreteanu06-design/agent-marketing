import Link from "next/link";
import { Logo } from "./Logo";
import { CONTACT_EMAIL } from "@/lib/config";
import { RevealSection } from "./RevealSection";

const LINK_CLASS =
  "group relative hover:text-foreground transition-colors after:absolute after:-bottom-1 after:left-0 after:h-px after:w-full after:origin-left after:scale-x-0 after:bg-brand-cyan after:transition-transform after:duration-300 hover:after:scale-x-100";

export function Footer() {
  return (
    <footer className="border-t border-border-subtle">
      <RevealSection className="mx-auto flex max-w-7xl flex-col gap-8 px-6 py-12 md:flex-row md:items-center md:justify-between lg:px-8">
        <Logo />
        <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-foreground-muted">
          <li>
            <a href="#servicii" className={LINK_CLASS}>
              Servicii
            </a>
          </li>
          <li>
            <a href="#despre" className={LINK_CLASS}>
              Despre
            </a>
          </li>
          <li>
            <Link href="/creeaza-cont" className={LINK_CLASS}>
              Creează cont
            </Link>
          </li>
          <li>
            <a href={`mailto:${CONTACT_EMAIL}`} className={LINK_CLASS}>
              {CONTACT_EMAIL}
            </a>
          </li>
        </ul>
      </RevealSection>
      <div className="mx-auto max-w-7xl px-6 pb-8 text-xs text-foreground-muted/70 lg:px-8">
        AC Media Marketing
      </div>
    </footer>
  );
}
