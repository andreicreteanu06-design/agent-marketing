"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { clearToken, getToken } from "@/lib/auth";
import { ApiError, getMe, type ClientAccountInfo, type MeResponse } from "@/lib/api";
import { SeoGeoApiError } from "@/lib/seoGeoApi";

interface SeoGeoSession {
  token: string;
  me: MeResponse;
  /** Contul actualizat (ex. dupa Setari) - meniul lateral si paginile il vad imediat. */
  setAccount: (account: ClientAccountInfo) => void;
  /**
   * Mesajul de aratat pentru o eroare de API. La 401 (sesiune expirata)
   * trimite la login si intoarce sirul gol - nu mai e nimic de aratat aici.
   */
  errorMessage: (err: unknown, fallback: string) => string;
}

const SessionContext = createContext<SeoGeoSession | null>(null);

/**
 * Sesiunea modulului SEO + GEO: verificata o singura data, in layout, nu pe
 * fiecare pagina. Ca in restul contului, verificarea e client-side (tokenul
 * sta in localStorage): fara token sau cu unul expirat, clientul ajunge la login.
 */
export function SeoGeoSessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    const existing = getToken();
    if (!existing) {
      router.replace("/login");
      return;
    }
    setError(null);
    getMe(existing)
      .then((response) => {
        setToken(existing);
        setMe(response);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          clearToken();
          router.replace("/login");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Nu am putut încărca contul.");
      });
  }, [router]);

  // O singura incarcare la montare (fetch initial, nu o "cascada" - load() nu
  // depinde de starea pe care o seteaza), ca in AccountDashboard.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const errorMessage = useCallback(
    (err: unknown, fallback: string): string => {
      const status =
        err instanceof ApiError || err instanceof SeoGeoApiError ? err.status : undefined;
      if (status === 401) {
        clearToken();
        router.replace("/login");
        return "";
      }
      return err instanceof Error && err.message ? err.message : fallback;
    },
    [router]
  );

  const setAccount = useCallback((account: ClientAccountInfo) => {
    setMe((current) => (current ? { ...current, account } : current));
  }, []);

  const value = useMemo(
    () => (token && me ? { token, me, setAccount, errorMessage } : null),
    [token, me, setAccount, errorMessage]
  );

  if (error) {
    return (
      <div className="mx-auto max-w-lg px-6 pt-32">
        <div className="rounded-3xl border border-border-subtle bg-background-elevated p-6">
          <p className="text-sm text-red-400">{error}</p>
          <button
            type="button"
            onClick={load}
            className="mt-4 text-sm font-semibold text-brand-cyan hover:underline"
          >
            Încearcă din nou
          </button>
        </div>
      </div>
    );
  }

  if (!value) {
    return <p className="px-6 pt-32 text-center text-sm text-foreground-muted">Se încarcă...</p>;
  }

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSeoGeoSession(): SeoGeoSession {
  const session = useContext(SessionContext);
  if (!session) {
    throw new Error("useSeoGeoSession se foloseste doar in interiorul SeoGeoSessionProvider");
  }
  return session;
}

/** "https://www.exemplu.ro" -> "www.exemplu.ro" - cum il scrie un om. */
export function displayHost(targetDomain: string): string {
  return targetDomain.replace(/^https?:\/\//, "").replace(/\/+$/, "");
}
