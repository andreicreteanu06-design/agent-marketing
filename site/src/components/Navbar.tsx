"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AnimatePresence, motion, useMotionValueEvent, useScroll } from "motion/react";
import { List, X } from "@phosphor-icons/react/dist/ssr";
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
  const { scrollY } = useScroll();

  useMotionValueEvent(scrollY, "change", (latest) => {
    setScrolled(latest > 24);
  });

  // Citit doar la montare - suficient pentru navigare in site (nu urmarim
  // schimbari intre tab-uri); pagina /cont oricum reverifica token-ul cu
  // serverul (GET /me), aici e doar despre ce arata navbar-ul. localStorage
  // nu exista pe server, deci nu poate porni ca stare initiala (ar rupe
  // hidratarea) - setat corect dupa montare e patternul corect aici, nu o
  // "cascada" (react-hooks/set-state-in-effect e prea stricta pentru asta).
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAuthenticated(Boolean(getToken()));
  }, []);

  return (
    <motion.header
      animate={{
        backgroundColor: scrolled ? "rgba(9,9,11,0.72)" : "rgba(9,9,11,0)",
        borderBottomColor: scrolled ? "var(--border-subtle)" : "rgba(0,0,0,0)",
        backdropFilter: scrolled ? "blur(12px)" : "blur(0px)",
      }}
      transition={{ duration: 0.35 }}
      className="fixed inset-x-0 top-0 z-50 border-b"
    >
      <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6 lg:px-8">
        <div className="flex items-center gap-8">
          <Link href="/" onClick={() => setOpen(false)}>
            <motion.div whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.97 }}>
              <Logo />
            </motion.div>
          </Link>
          <ul className="hidden items-center gap-7 lg:flex">
            {NAV_LINKS.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  className="group relative text-sm text-foreground-muted transition-colors hover:text-foreground"
                >
                  {link.label}
                  <span className="absolute -bottom-1 left-0 h-px w-full origin-left scale-x-0 bg-brand-cyan transition-transform duration-300 group-hover:scale-x-100" />
                </Link>
              </li>
            ))}
          </ul>
        </div>

        <div className="hidden items-center gap-5 lg:flex">
          {authenticated ? (
            <Link
              href="/cont"
              className="text-sm font-medium text-foreground-muted transition-colors hover:text-foreground"
            >
              Contul meu
            </Link>
          ) : (
            <>
              <Link
                href="/login"
                className="text-sm text-foreground-muted transition-colors hover:text-foreground"
              >
                Autentificare
              </Link>
              <Link
                href="/creeaza-cont"
                className="text-sm font-medium text-foreground-muted transition-colors hover:text-foreground"
              >
                Creează cont
              </Link>
            </>
          )}
          <MagneticButton
            href="/#programeaza"
            className="rounded-full bg-brand-blue px-4 py-2 text-sm font-semibold text-white"
          >
            Programează un apel
          </MagneticButton>
        </div>

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "Închide meniul" : "Deschide meniul"}
          className="flex h-10 w-10 items-center justify-center rounded-full border border-border-subtle text-foreground lg:hidden"
        >
          {open ? <X size={20} /> : <List size={20} />}
        </button>
      </nav>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden border-t border-border-subtle bg-background lg:hidden"
          >
            <ul className="flex flex-col gap-1 px-6 py-4">
              {NAV_LINKS.map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    onClick={() => setOpen(false)}
                    className="block py-2 text-base text-foreground-muted"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
              {authenticated ? (
                <li className="pt-2">
                  <Link
                    href="/cont"
                    onClick={() => setOpen(false)}
                    className="block py-2 text-base text-foreground"
                  >
                    Contul meu
                  </Link>
                </li>
              ) : (
                <>
                  <li className="pt-2">
                    <Link
                      href="/login"
                      onClick={() => setOpen(false)}
                      className="block py-2 text-base text-foreground-muted"
                    >
                      Autentificare
                    </Link>
                  </li>
                  <li>
                    <Link
                      href="/creeaza-cont"
                      onClick={() => setOpen(false)}
                      className="block py-2 text-base text-foreground"
                    >
                      Creează cont
                    </Link>
                  </li>
                </>
              )}
              <li className="pt-2">
                <Link
                  href="/#programeaza"
                  onClick={() => setOpen(false)}
                  className="block rounded-full bg-brand-blue px-4 py-3 text-center text-base font-semibold text-white"
                >
                  Programează un apel
                </Link>
              </li>
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.header>
  );
}
