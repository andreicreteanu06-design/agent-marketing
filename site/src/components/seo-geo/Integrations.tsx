"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { Icon } from "@phosphor-icons/react";
import { ChartLineUp, CheckCircle, GoogleLogo, MagnifyingGlass } from "@phosphor-icons/react/dist/ssr";
import {
  disconnectIntegration,
  getIntegrationAuthUrl,
  getIntegrationProperties,
  updateIntegration,
  type IntegrationName,
  type IntegrationProperty,
  type IntegrationState,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { useSeoGeoSession } from "./SeoGeoSession";
import { ghostButton, outlineButton, primaryButton } from "./ui";

interface IntegrationMeta {
  title: string;
  icon: Icon;
  summary: string;
  benefits: string[];
  propertyHint: string;
}

export const INTEGRATION_META: Record<IntegrationName, IntegrationMeta> = {
  gsc: {
    title: "Google Search Console",
    icon: MagnifyingGlass,
    summary: "Căutările reale din Google care îți aduc vizitatori.",
    benefits: [
      "Interogările pe care apari, cu clicuri, afișări și poziție medie",
      "Folosite și de agentul PPC: nu plătești reclame pe ce aduci deja organic",
    ],
    propertyHint: "Proprietatea exact ca în Search Console: sc-domain:exemplu.ro sau https://www.exemplu.ro/",
  },
  ga4: {
    title: "Google Analytics 4",
    icon: ChartLineUp,
    summary: "Ce fac vizitatorii după ce ajung pe site.",
    benefits: [
      "Sesiuni, surse de trafic și conversii, pe proprietatea aleasă",
      "Acces doar de citire - nu modificăm nimic în contul tău",
    ],
    propertyHint: "ID-ul numeric al proprietății (Admin → Property settings), nu ID-ul G-... al fluxului",
  },
};

/** Mesajele pentru codurile cu care serverul intoarce clientul de pe ecranul Google. */
export const CALLBACK_ERRORS: Record<string, string> = {
  acces_refuzat: "Ai refuzat accesul pe ecranul Google. Poți încerca din nou oricând.",
  sesiune_expirata: "Conectarea a expirat înainte să fie confirmată. Încearcă din nou.",
  schimb_esuat: "Google nu a confirmat conectarea. Încearcă din nou.",
  raspuns_incomplet: "Google a întors un răspuns incomplet. Încearcă din nou.",
  eroare_google: "Google a întors o eroare. Încearcă din nou.",
  cont_inexistent: "Contul pentru care s-a pornit conectarea nu mai există.",
  server_neconfigurat: "Conectarea cu Google nu e configurată pe server.",
};

/** Proprietatea salvata, cum o citeste un om. */
export function propertyDisplay(name: IntegrationName, propertyId: string): string {
  if (name === "gsc" && propertyId.startsWith("sc-domain:")) {
    return `${propertyId.slice("sc-domain:".length)} (tot domeniul)`;
  }
  return name === "ga4" ? `Proprietatea ${propertyId}` : propertyId;
}

function statusBadge(state: IntegrationState) {
  if (!state.connected) return <Badge>Neconectat</Badge>;
  if (!state.property_id) return <Badge variant="warning">Alege proprietatea</Badge>;
  return <Badge variant="success">Conectat</Badge>;
}

function IntegrationIcon({ name }: { name: IntegrationName }) {
  const MetaIcon = INTEGRATION_META[name].icon;
  return (
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-blue/15 text-brand-cyan">
      <MetaIcon size={20} weight="duotone" />
    </span>
  );
}

/** Porneste consimtamantul Google: cere URL-ul semnat si navigheaza acolo. */
function useGoogleConnect() {
  const { token, errorMessage } = useSeoGeoSession();
  const [connecting, setConnecting] = useState<IntegrationName | null>(null);
  const [error, setError] = useState<string | null>(null);

  const connect = useCallback(
    async (name: IntegrationName) => {
      setError(null);
      setConnecting(name);
      try {
        const { auth_url } = await getIntegrationAuthUrl(token, name);
        window.location.assign(auth_url);
      } catch (err) {
        setError(errorMessage(err, "Nu am putut porni conectarea cu Google."));
        setConnecting(null);
      }
    },
    [token, errorMessage]
  );

  return { connect, connecting, error };
}

/* -------------------------------------------------------------------------- */
/* Cardul compact - pagina de ansamblu                                         */
/* -------------------------------------------------------------------------- */

export function IntegrationSummaryCard({
  name,
  state,
  oauthConfigured,
}: {
  name: IntegrationName;
  state: IntegrationState;
  oauthConfigured: boolean;
}) {
  const meta = INTEGRATION_META[name];
  const { connect, connecting, error } = useGoogleConnect();
  const manageLink = cn(buttonVariants({ variant: "outline" }), outlineButton);

  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="flex min-w-0 items-center gap-3">
          <IntegrationIcon name={name} />
          <CardTitle className="truncate">{meta.title}</CardTitle>
        </div>
        {statusBadge(state)}
      </CardHeader>
      <CardContent className="flex-1">
        <CardDescription>
          {state.connected && state.property_id
            ? propertyDisplay(name, state.property_id)
            : meta.summary}
        </CardDescription>
        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
      </CardContent>
      <CardFooter>
        {!state.connected && oauthConfigured && (
          <Button
            className={cn(outlineButton, "gap-2")}
            variant="outline"
            disabled={connecting !== null}
            onClick={() => void connect(name)}
          >
            <GoogleLogo size={16} weight="bold" />
            {connecting === name ? "Se deschide Google..." : "Conectează"}
          </Button>
        )}
        {!state.connected && !oauthConfigured && (
          <Link href="/cont/seo-geo/integrari" className={manageLink}>
            Vezi detalii
          </Link>
        )}
        {state.connected && (
          <Link href="/cont/seo-geo/integrari" className={manageLink}>
            {state.property_id ? "Gestionează" : "Alege proprietatea"}
          </Link>
        )}
      </CardFooter>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Panoul complet - pagina Integrari                                           */
/* -------------------------------------------------------------------------- */

function PropertyPicker({
  name,
  onSaved,
  onCancel,
}: {
  name: IntegrationName;
  onSaved: (state: IntegrationState) => void;
  onCancel?: () => void;
}) {
  const { token, errorMessage } = useSeoGeoSession();
  const [options, setOptions] = useState<IntegrationProperty[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState("");
  const [manual, setManual] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Lista vine din contul Google al clientului - o singura cerere, la deschidere.
  useEffect(() => {
    let active = true;
    getIntegrationProperties(token, name)
      .then((list) => {
        if (!active) return;
        setOptions(list);
        setSelected(list[0]?.id ?? "");
        if (list.length === 0) setManual(true);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setLoadError(errorMessage(err, "Nu am putut citi proprietățile din contul Google."));
        setManual(true);
      });
    return () => {
      active = false;
    };
  }, [token, name, errorMessage]);

  async function save() {
    if (!selected.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      onSaved(await updateIntegration(token, name, selected.trim()));
    } catch (err) {
      setSaveError(errorMessage(err, "Nu am putut salva proprietatea."));
    } finally {
      setSaving(false);
    }
  }

  const loading = options === null && loadError === null;

  return (
    <div className="space-y-3 rounded-2xl border border-border-subtle bg-background p-4">
      <label htmlFor={`property-${name}`} className="block text-sm font-medium text-foreground">
        Proprietatea folosită
      </label>
      {loading && <p className="text-sm text-foreground-muted">Citim proprietățile din contul Google...</p>}
      {loadError && <p className="text-sm text-amber-200">{loadError} Poți scrie proprietatea de mână.</p>}
      {options !== null && options.length === 0 && !loadError && (
        <p className="text-sm text-amber-200">
          Contul Google conectat nu are acces la nicio proprietate. Scrie-o de mână sau
          reconectează-te cu contul care o administrează.
        </p>
      )}

      {!manual && options !== null && options.length > 0 && (
        <select
          id={`property-${name}`}
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
          className="w-full rounded-xl border border-border-subtle bg-background-elevated px-3 py-2.5 text-sm text-foreground outline-none focus:border-brand-cyan"
        >
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      )}
      {manual && (
        <>
          <input
            id={`property-${name}`}
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            placeholder={name === "gsc" ? "sc-domain:exemplu.ro" : "123456789"}
            className="w-full rounded-xl border border-border-subtle bg-background-elevated px-3 py-2.5 text-sm text-foreground outline-none placeholder:text-foreground-muted/60 focus:border-brand-cyan"
          />
          <p className="text-xs text-foreground-muted">{INTEGRATION_META[name].propertyHint}</p>
        </>
      )}
      {saveError && <p className="text-sm text-red-400">{saveError}</p>}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <Button
          className={primaryButton}
          disabled={saving || !selected.trim()}
          onClick={() => void save()}
        >
          {saving ? "Se salvează..." : "Salvează proprietatea"}
        </Button>
        {!manual && options !== null && options.length > 0 && (
          <Button variant="ghost" className={ghostButton} onClick={() => setManual(true)}>
            Scriu de mână
          </Button>
        )}
        {onCancel && (
          <Button variant="ghost" className={ghostButton} onClick={onCancel}>
            Anulează
          </Button>
        )}
      </div>
    </div>
  );
}

export function IntegrationPanel({
  name,
  state,
  oauthConfigured,
  onStateChange,
}: {
  name: IntegrationName;
  state: IntegrationState;
  oauthConfigured: boolean;
  onStateChange: (state: IntegrationState) => void;
}) {
  const meta = INTEGRATION_META[name];
  const { token, errorMessage } = useSeoGeoSession();
  const { connect, connecting, error: connectError } = useGoogleConnect();
  const [changing, setChanging] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function disconnect() {
    setDisconnecting(true);
    setError(null);
    try {
      await disconnectIntegration(token, name);
      onStateChange({ connected: false, property_id: "" });
      setConfirmDisconnect(false);
      setChanging(false);
    } catch (err) {
      setError(errorMessage(err, "Nu am putut deconecta contul."));
    } finally {
      setDisconnecting(false);
    }
  }

  const showPicker = state.connected && (!state.property_id || changing);

  return (
    <Card className="flex flex-col">
      <CardHeader className="items-start">
        <div className="flex min-w-0 items-center gap-3">
          <IntegrationIcon name={name} />
          <div className="min-w-0">
            <CardTitle>{meta.title}</CardTitle>
            <CardDescription>{meta.summary}</CardDescription>
          </div>
        </div>
        {statusBadge(state)}
      </CardHeader>

      <CardContent className="flex-1 space-y-5">
        <ul className="space-y-2">
          {meta.benefits.map((benefit) => (
            <li key={benefit} className="flex items-start gap-2 text-sm text-foreground-muted">
              <CheckCircle size={16} weight="fill" className="mt-0.5 shrink-0 text-brand-cyan" />
              {benefit}
            </li>
          ))}
        </ul>

        {state.connected && state.property_id && !changing && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border-subtle bg-background px-4 py-3">
            <div className="min-w-0">
              <p className="text-xs uppercase tracking-widest text-foreground-muted">Proprietate</p>
              <p className="truncate text-sm font-medium text-foreground">
                {propertyDisplay(name, state.property_id)}
              </p>
            </div>
            <Button variant="ghost" className={ghostButton} onClick={() => setChanging(true)}>
              Schimbă
            </Button>
          </div>
        )}

        {showPicker && (
          <PropertyPicker
            name={name}
            onSaved={(next) => {
              onStateChange(next);
              setChanging(false);
            }}
            onCancel={state.property_id ? () => setChanging(false) : undefined}
          />
        )}

        {(error || connectError) && <p className="text-sm text-red-400">{error ?? connectError}</p>}
      </CardContent>

      <CardFooter className="flex-wrap justify-between">
        {!state.connected ? (
          <Button
            className={cn(primaryButton, "gap-2")}
            disabled={!oauthConfigured || connecting !== null}
            onClick={() => void connect(name)}
          >
            <GoogleLogo size={16} weight="bold" />
            {connecting === name ? "Se deschide Google..." : "Conectează cu Google"}
          </Button>
        ) : (
          <Button
            variant="outline"
            className={cn(outlineButton, "gap-2")}
            disabled={!oauthConfigured || connecting !== null}
            onClick={() => void connect(name)}
          >
            <GoogleLogo size={16} weight="bold" />
            {connecting === name ? "Se deschide Google..." : "Reconectează"}
          </Button>
        )}

        {state.connected && !confirmDisconnect && (
          <Button
            variant="ghost"
            className={cn(ghostButton, "hover:bg-red-500/10 hover:text-red-400")}
            onClick={() => setConfirmDisconnect(true)}
          >
            Deconectează
          </Button>
        )}
        {state.connected && confirmDisconnect && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-foreground-muted">Sigur?</span>
            <Button
              variant="ghost"
              className={cn(ghostButton, "text-red-400 hover:bg-red-500/10 hover:text-red-300")}
              disabled={disconnecting}
              onClick={() => void disconnect()}
            >
              {disconnecting ? "Se deconectează..." : "Da, deconectează"}
            </Button>
            <Button
              variant="ghost"
              className={ghostButton}
              onClick={() => setConfirmDisconnect(false)}
            >
              Nu
            </Button>
          </div>
        )}
      </CardFooter>
    </Card>
  );
}
