"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, LayoutGroup, motion, useMotionValueEvent, useReducedMotion, useScroll } from "motion/react";
import { ArrowUpRight, List, X, PlugsConnected } from "@phosphor-icons/react/dist/ssr";
import { Logo } from "./Logo";
import { MagneticButton } from "./MagneticButton";
import { getToken } from "@/lib/auth";

const NAV_LINKS = [
  { href: "/#servicii", label: "Servicii" },
  { href: "/#portofoliu", label: "Portofoliu" },
  { href: "/#despre", label: "Despre" },
];

export function Navbar() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const [anchor, setAnchor] = useState("");
  const toggle = useRef<HTMLButtonElement>(null);
  const reduce = useReducedMotion();
  const { scrollY } = useScroll();
  useMotionValueEvent(scrollY, "change", latest => setScrolled(latest > 24));
  const pathname = usePathname();
  useEffect(() => {
    // Existing auth follows client navigation. Hash tracking is visual only.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAuthenticated(Boolean(getToken()));
    const sync = () => setAnchor(window.location.hash);
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); toggle.current?.focus(); }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open]);

  const selected = pathname.startsWith("/servicii/") ? "/#servicii" : pathname === "/" && anchor ? "/" + anchor : null;
  const illuminated = focused ?? hovered ?? selected;
  const transition = reduce ? { duration: 0 } : { type: "spring" as const, stiffness: 430, damping: 36, mass: 0.65 };

  return <header className={`site-header site-header--optical fixed z-50 ${scrolled ? "site-header--scrolled" : ""} ${open ? "site-header--open" : ""}`}>
    <nav className="site-nav" aria-label="Navigație principală">
      <Link href="/" aria-label="AC Media — Acasă" onClick={() => setOpen(false)} className="site-logo"><Logo /></Link>
      <LayoutGroup id="primary-navigation">
        <ul className="site-nav-cluster hidden items-center gap-1 lg:flex" onMouseLeave={() => setHovered(null)}>
          {NAV_LINKS.map(link => <li key={link.href}>
            <a href={pathname === "/" ? link.href.slice(1) : link.href} className="site-nav-link"
              aria-current={selected === link.href ? "location" : undefined}
              onMouseEnter={() => setHovered(link.href)} onFocus={() => setFocused(link.href)} onBlur={() => setFocused(null)}>
              {illuminated === link.href && <motion.span className="site-nav-lens" layoutId="navigation-lens" initial={false} transition={transition} aria-hidden="true" />}
              <span className="site-nav-label">{link.label}</span>
              <span className="site-nav-glint" aria-hidden="true" />
            </a>
          </li>)}
        </ul>
      </LayoutGroup>
      <Link href="/mcp" className="site-mcp-link" aria-current={pathname === "/mcp" ? "page" : undefined} aria-label="Conectează AI prin MCP" onClick={() => setOpen(false)}>
        <span className="site-mcp-icon" aria-hidden="true"><PlugsConnected size={18} /></span><span>MCP</span><ArrowUpRight className="site-mcp-arrow" size={12} aria-hidden="true" />
      </Link>
      <div className="site-nav-account ml-auto hidden items-center gap-2 lg:flex">
        {authenticated ? <Link href="/cont" className="site-nav-action" aria-current={pathname.startsWith("/cont") ? "page" : undefined}><span>Contul meu</span><ArrowUpRight size={13} aria-hidden="true" /></Link> : <>
          <Link href="/login" className="site-nav-action" aria-current={pathname === "/login" ? "page" : undefined}><span>Autentificare</span></Link>
          <Link href="/creeaza-cont" className="site-nav-action site-nav-register" aria-current={pathname === "/creeaza-cont" ? "page" : undefined}><span>Creează cont</span><ArrowUpRight size={13} aria-hidden="true" /></Link>
        </>}
        <MagneticButton href="/#programeaza" className="enterprise-button nav-cta">Solicită o programare <ArrowUpRight size={16} /></MagneticButton>
      </div>
      <button ref={toggle} type="button" onClick={() => setOpen(v => !v)} aria-label={open ? "Închide meniul" : "Deschide meniul"} aria-expanded={open} aria-controls="mobile-navigation" className="site-menu-button lg:hidden">
        {open ? <X size={22} /> : <List size={22} />}
      </button>
    </nav>
    <AnimatePresence>
      {open && <motion.div id="mobile-navigation" initial={reduce ? false : { opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: reduce ? 0 : -4 }} transition={{ duration: reduce ? 0 : 0.18, ease: [0.16, 1, 0.3, 1] }} className="site-mobile-menu lg:hidden">
        <ul>{NAV_LINKS.map((link, index) => <motion.li key={link.href} initial={reduce ? false : { opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.18, delay: reduce ? 0 : index * 0.035 }}>
          <a href={pathname === "/" ? link.href.slice(1) : link.href} onClick={() => setOpen(false)}>{link.label}<ArrowUpRight size={18} /></a>
        </motion.li>)}
          {authenticated ? <li><Link href="/cont" onClick={() => setOpen(false)}>Contul meu</Link></li> : <>
            <li><Link href="/login" onClick={() => setOpen(false)}>Autentificare</Link></li>
            <li><Link href="/creeaza-cont" onClick={() => setOpen(false)}>Creează cont</Link></li>
          </>}
        </ul>
        <Link href="/#programeaza" onClick={() => setOpen(false)} className="enterprise-button">Solicită o programare <ArrowUpRight size={18} /></Link>
      </motion.div>}
    </AnimatePresence>
  </header>;
}
