"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowUpRight,
  MagnifyingGlass,
  ShoppingBagOpen,
  SignOut,
} from "@phosphor-icons/react/dist/ssr";
import { getToken, clearToken } from "@/lib/auth";
import { getMe, ApiError, type MeResponse } from "@/lib/api";
import { CredentialsForm } from "./CredentialsForm";
import { RevealSection } from "./RevealSection";

type Session = { token: string; me: MeResponse };

/**
 * Pagina de cont e protejata client-side (nu exista inca sesiune de server) -
 * fara token in localStorage, sau cu un token expirat/invalid (401 de la
 * /me), redirectioneaza spre /login. Alte erori (retea, 503 server) raman
 * afisate aici, cu optiune de reincercare - un 401 e "nu esti autentificat",
 * restul sunt probleme temporare, nu acelasi lucru.
 */
export function AccountDashboard() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    const token = getToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setLoading(true);
    setError(null);
    getMe(token)
      .then((me) => setSession({ token, me }))
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          clearToken();
          router.replace("/login");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Nu am putut încărca contul.");
      })
      .finally(() => setLoading(false));
  }, [router]);

  // Incarcare o singura data la montare (fetch initial de date, nu o
  // "cascada" - load() nu depinde de starea pe care o seteaza pe urma).
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  function handleLogout() {
    clearToken();
    router.push("/");
  }

  if (loading) {
    return <p className="text-sm text-foreground-muted">Se încarcă...</p>;
  }

  if (error) {
    return (
      <div className="rounded-3xl border border-border-subtle bg-background-elevated p-6">
        <p className="text-sm text-red-400">{error}</p>
        <button
          onClick={load}
          className="mt-4 text-sm font-semibold text-brand-cyan hover:underline"
        >
          Încearcă din nou
        </button>
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="space-y-6">
      <RevealSection className="flex items-center justify-between rounded-3xl border border-border-subtle bg-background-elevated p-6">
        <div>
          <p className="text-sm text-foreground-muted">Autentificat ca</p>
          <p className="text-lg font-semibold text-foreground">{session.me.user.email}</p>
        </div>
        <button
          onClick={handleLogout}
          className="flex items-center gap-1.5 text-sm text-foreground-muted transition-colors hover:text-foreground"
        >
          <SignOut size={16} />
          Deconectare
        </button>
      </RevealSection>

      <RevealSection delay={0.1}>
        <CredentialsForm
          token={session.token}
          initialStatus={{
            google: session.me.google_ads_connected,
            meta: session.me.meta_connected,
            tiktok: session.me.tiktok_connected,
            chatgpt: session.me.chatgpt_connected,
          }}
        />
      </RevealSection>

      <RevealSection delay={0.15}>
        <Link
          href="/cont/seo-geo"
          className="group flex items-center justify-between rounded-3xl border border-border-subtle bg-background-elevated p-6 transition-colors hover:border-brand-blue/40"
        >
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-blue/15 text-brand-cyan">
              <MagnifyingGlass size={20} weight="duotone" />
            </div>
            <div>
              <p className="text-sm font-semibold text-foreground">SEO + GEO</p>
              <p className="text-sm text-foreground-muted">
                Auditul site-ului, Search Console și Google Analytics, într-un singur loc.
              </p>
            </div>
          </div>
          <ArrowUpRight
            size={18}
            weight="bold"
            className="shrink-0 text-foreground-muted transition-transform duration-300 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-brand-cyan"
          />
        </Link>
      </RevealSection>

      <RevealSection delay={0.2}>
        <Link
          href="/cont/produse-chatgpt"
          className="group flex items-center justify-between rounded-3xl border border-border-subtle bg-background-elevated p-6 transition-colors hover:border-brand-blue/40"
        >
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-blue/15 text-brand-cyan">
              <ShoppingBagOpen size={20} weight="duotone" />
            </div>
            <div>
              <p className="text-sm font-semibold text-foreground">Convertor produse ChatGPT</p>
              <p className="text-sm text-foreground-muted">
                Catalogul tău (CSV, Excel, XML), transformat în formatul ChatGPT Shopping.
              </p>
            </div>
          </div>
          <ArrowUpRight
            size={18}
            weight="bold"
            className="shrink-0 text-foreground-muted transition-transform duration-300 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-brand-cyan"
          />
        </Link>
      </RevealSection>
    </div>
  );
}
