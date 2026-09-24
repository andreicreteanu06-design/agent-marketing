"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { CheckCircle, Info, WarningCircle } from "@phosphor-icons/react/dist/ssr";
import { getIntegrations, type IntegrationName, type IntegrationsStatus } from "@/lib/api";
import { CALLBACK_ERRORS, INTEGRATION_META, IntegrationPanel } from "./Integrations";
import { useSeoGeoSession } from "./SeoGeoSession";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function isIntegrationName(value: string | null): value is IntegrationName {
  return value === "gsc" || value === "ga4";
}

/** Mesajul cu care se intoarce clientul de pe ecranul Google (?conectat= / ?eroare=). */
function useCallbackNotice(): { kind: "success" | "error"; text: string } | null {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [notice] = useState(() => {
    const connected = searchParams.get("conectat");
    if (isIntegrationName(connected)) {
      return {
        kind: "success" as const,
        text: `${INTEGRATION_META[connected].title} e conectat. Alege mai jos proprietatea folosită.`,
      };
    }
    const code = searchParams.get("eroare");
    if (code) {
      const integration = searchParams.get("integrare");
      const prefix = isIntegrationName(integration) ? `${INTEGRATION_META[integration].title}: ` : "";
      return {
        kind: "error" as const,
        text: prefix + (CALLBACK_ERRORS[code] ?? "Conectarea nu s-a putut finaliza. Încearcă din nou."),
      };
    }
    return null;
  });

  // Mesajul e citit o data; URL-ul se curata, ca un refresh sa nu-l mai arate.
  useEffect(() => {
    if (searchParams.size > 0) router.replace(pathname, { scroll: false });
  }, [searchParams, router, pathname]);

  return notice;
}

export function IntegrationsHub() {
  const { token, errorMessage } = useSeoGeoSession();
  const notice = useCallbackNotice();
  const [status, setStatus] = useState<IntegrationsStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getIntegrations(token)
      .then(setStatus)
      .catch((err: unknown) => setError(errorMessage(err, "Nu am putut încărca integrările.")));
  }, [token, errorMessage]);

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Integrări</h1>
        <p className="mt-2 max-w-2xl text-base text-foreground-muted">
          Conectează-ți conturile Google ca agentul să lucreze cu datele reale ale site-ului:
          ce caută oamenii în Google înainte să ajungă la tine și ce fac după ce ajung.
        </p>
      </header>

      {notice && (
        <div
          role="status"
          className={
            notice.kind === "success"
              ? "flex items-start gap-3 rounded-2xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-200"
              : "flex items-start gap-3 rounded-2xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-300"
          }
        >
          {notice.kind === "success" ? (
            <CheckCircle size={18} weight="fill" className="mt-0.5 shrink-0" />
          ) : (
            <WarningCircle size={18} weight="fill" className="mt-0.5 shrink-0" />
          )}
          <p className="leading-relaxed">{notice.text}</p>
        </div>
      )}

      {error && <p className="text-sm text-red-400">{error}</p>}
      {!status && !error && <p className="text-sm text-foreground-muted">Se încarcă...</p>}

      {status && !status.oauth_configured && (
        <div className="flex items-start gap-3 rounded-2xl border border-amber-400/30 bg-amber-400/10 px-4 py-4 text-sm text-amber-100">
          <Info size={18} weight="fill" className="mt-0.5 shrink-0" />
          <div className="space-y-2 leading-relaxed">
            <p className="font-medium">Conectarea cu Google nu e încă activată pe server.</p>
            <p className="text-amber-100/80">
              Administratorul trebuie să creeze un client OAuth de tip „Web application” în Google
              Cloud Console, să pună PPC_GOOGLE_OAUTH_CLIENT_ID și PPC_GOOGLE_OAUTH_CLIENT_SECRET în
              .env și să adauge la „Authorized redirect URIs”:
            </p>
            <ul className="space-y-1 font-mono text-xs text-amber-50">
              <li>{API_BASE_URL}/api/v1/integrations/gsc/callback</li>
              <li>{API_BASE_URL}/api/v1/integrations/ga4/callback</li>
            </ul>
          </div>
        </div>
      )}

      {status && (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          {(["gsc", "ga4"] as const).map((name) => (
            <IntegrationPanel
              key={name}
              name={name}
              state={status[name]}
              oauthConfigured={status.oauth_configured}
              onStateChange={(next) =>
                setStatus((current) => (current ? { ...current, [name]: next } : current))
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
