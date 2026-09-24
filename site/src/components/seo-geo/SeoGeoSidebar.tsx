"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Icon } from "@phosphor-icons/react";
import {
  ArrowLeft,
  ChartLineUp,
  ClipboardText,
  GearSix,
  Globe,
  PlugsConnected,
  SquaresFour,
} from "@phosphor-icons/react/dist/ssr";
import { cn } from "@/lib/utils";
import { displayHost, useSeoGeoSession } from "./SeoGeoSession";

interface NavItem {
  href: string;
  label: string;
  icon: Icon;
}

const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: "Prezentare",
    items: [{ href: "/cont/seo-geo", label: "Privire de ansamblu", icon: SquaresFour }],
  },
  {
    title: "Site-ul meu",
    items: [
      { href: "/cont/seo-geo/trafic", label: "Trafic & Poziții", icon: ChartLineUp },
      { href: "/cont/seo-geo/audit", label: "Audit site", icon: ClipboardText },
      { href: "/cont/seo-geo/integrari", label: "Integrări", icon: PlugsConnected },
    ],
  },
  {
    title: "Cont",
    items: [{ href: "/cont/seo-geo/setari", label: "Setări", icon: GearSix }],
  },
];

const ALL_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

function isActive(pathname: string, href: string): boolean {
  // Pagina de ansamblu e radacina modulului - activa doar exact pe ea.
  return href === "/cont/seo-geo" ? pathname === href : pathname.startsWith(href);
}

/**
 * Navigarea modulului SEO + GEO: coloana fixa pe desktop, rand de file pe mobil.
 *
 * `fixed`, nu `sticky`: dupa o vizita pe homepage, stilul injectat de
 * scroll-world pune `overflow-x: hidden` si pe <html>, si pe <body>, iar asta
 * face din <body> un container de scroll in care `sticky` nu se mai lipeste.
 */
export function SeoGeoSidebar() {
  const pathname = usePathname();
  const { me } = useSeoGeoSession();
  const host = displayHost(me.account.target_domain);

  return (
    <>
      <aside className="hidden w-60 shrink-0 lg:block">
        <div className="fixed top-24 flex w-60 flex-col gap-6">
          <Link
            href="/cont/seo-geo/setari"
            className="group flex items-center gap-3 rounded-2xl border border-border-subtle bg-background-elevated px-3.5 py-3 transition-colors hover:border-brand-blue/40"
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-blue/15 text-brand-cyan">
              <Globe size={16} weight="duotone" />
            </span>
            <span className="min-w-0">
              <span className="block text-[11px] uppercase tracking-widest text-foreground-muted">
                Site
              </span>
              <span className="block truncate text-sm font-semibold text-foreground">
                {host || "Setează site-ul"}
              </span>
            </span>
          </Link>

          <nav aria-label="Modulul SEO + GEO" className="flex flex-col gap-5">
            {NAV_GROUPS.map((group) => (
              <div key={group.title}>
                <p className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-widest text-foreground-muted/70">
                  {group.title}
                </p>
                <ul className="flex flex-col gap-0.5">
                  {group.items.map((item) => {
                    const active = isActive(pathname, item.href);
                    const ItemIcon = item.icon;
                    return (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          aria-current={active ? "page" : undefined}
                          className={cn(
                            "relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-colors",
                            active
                              ? "bg-white/[0.05] font-medium text-foreground before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-brand-cyan"
                              : "text-foreground-muted hover:bg-white/[0.03] hover:text-foreground"
                          )}
                        >
                          <ItemIcon
                            size={17}
                            weight={active ? "fill" : "regular"}
                            className={active ? "text-brand-cyan" : undefined}
                          />
                          {item.label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>

          <Link
            href="/cont"
            className="flex items-center gap-2 px-3 text-sm text-foreground-muted transition-colors hover:text-foreground"
          >
            <ArrowLeft size={14} />
            Contul meu
          </Link>
        </div>
      </aside>

      <nav
        aria-label="Modulul SEO + GEO"
        className="-mx-6 mb-8 flex gap-2 overflow-x-auto px-6 pb-1 lg:hidden"
      >
        {ALL_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          const ItemIcon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex shrink-0 items-center gap-2 rounded-full border px-3.5 py-2 text-sm transition-colors",
                active
                  ? "border-brand-cyan/40 bg-brand-blue/15 text-foreground"
                  : "border-border-subtle text-foreground-muted hover:text-foreground"
              )}
            >
              <ItemIcon size={15} weight={active ? "fill" : "regular"} />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </>
  );
}
