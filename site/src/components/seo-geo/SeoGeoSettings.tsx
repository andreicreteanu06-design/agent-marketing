"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { CheckCircle } from "@phosphor-icons/react/dist/ssr";
import { updateSiteSettings } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { displayHost, useSeoGeoSession } from "./SeoGeoSession";
import { outlineButton, primaryButton } from "./ui";

const inputClass =
  "w-full rounded-xl border border-border-subtle bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors placeholder:text-foreground-muted/60 focus:border-brand-cyan";

export function SeoGeoSettings() {
  const { token, me, setAccount, errorMessage } = useSeoGeoSession();
  const [domain, setDomain] = useState(displayHost(me.account.target_domain));
  const [brand, setBrand] = useState(me.account.brand_name);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const account = await updateSiteSettings(token, { target_domain: domain, brand_name: brand });
      setAccount(account);
      setDomain(displayHost(account.target_domain));
      setBrand(account.brand_name);
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err, "Nu am putut salva setările."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Setări</h1>
        <p className="mt-2 max-w-2xl text-base text-foreground-muted">
          Site-ul pe care lucrează agentul. Le setezi o dată și le folosesc auditul, verificările
          GEO și agentul PPC.
        </p>
      </header>

      <form onSubmit={handleSubmit}>
        <Card>
          <CardHeader>
            <CardTitle>Site-ul tău</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <label htmlFor="settings-domain" className="block text-sm font-medium text-foreground">
                Domeniu
              </label>
              <input
                id="settings-domain"
                value={domain}
                onChange={(event) => setDomain(event.target.value)}
                placeholder="exemplu.ro"
                className={inputClass}
              />
              <CardDescription>
                Pornește de aici auditul și tot de aici citește agentul PPC datele organice.
              </CardDescription>
            </div>

            <div className="space-y-2">
              <label htmlFor="settings-brand" className="block text-sm font-medium text-foreground">
                Numele brandului <span className="text-foreground-muted">(opțional)</span>
              </label>
              <input
                id="settings-brand"
                value={brand}
                onChange={(event) => setBrand(event.target.value)}
                placeholder="Ex. Arting Auto"
                maxLength={200}
                className={inputClass}
              />
              <CardDescription>
                Folosit la verificarea GEO: cât de des apare brandul explicit în text, ca un model
                AI să te poată cita pe nume. Gol înseamnă că îl deducem din domeniu.
              </CardDescription>
            </div>

            {error && (
              <p role="alert" className="rounded-xl bg-red-500/10 px-4 py-3 text-sm text-red-400">
                {error}
              </p>
            )}
          </CardContent>
          <CardFooter>
            <Button type="submit" className={primaryButton} disabled={saving}>
              {saving ? "Se salvează..." : "Salvează"}
            </Button>
            {saved && (
              <span className="flex items-center gap-1.5 text-sm text-emerald-300">
                <CheckCircle size={16} weight="fill" />
                Salvat
              </span>
            )}
          </CardFooter>
        </Card>
      </form>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Contul tău</CardTitle>
            <CardDescription>{me.user.email}</CardDescription>
          </div>
          <Link href="/cont" className={cn(buttonVariants({ variant: "outline" }), outlineButton)}>
            Contul meu
          </Link>
        </CardHeader>
        <CardContent>
          <CardDescription>
            Conturile de reclame (Google Ads, Meta, TikTok) se conectează din Contul meu. Conturile
            Google pentru date organice, din{" "}
            <Link href="/cont/seo-geo/integrari" className="text-brand-cyan hover:underline">
              Integrări
            </Link>
            .
          </CardDescription>
        </CardContent>
      </Card>
    </div>
  );
}
