"use client";

import { useState, type ChangeEvent, type FormEvent } from "react";
import { CheckCircle, LockSimple } from "@phosphor-icons/react/dist/ssr";
import { ApiError, updateCredentials, type CredentialsUpdateInput } from "@/lib/api";

export interface ConnectionStatus {
  google: boolean;
  meta: boolean;
  tiktok: boolean;
  chatgpt: boolean;
}

function CredentialField({
  label,
  placeholder,
  connected,
  value,
  onChange,
  disabled,
}: {
  label: string;
  placeholder: string;
  connected: boolean;
  value: string;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <label className="text-sm font-medium text-foreground">{label}</label>
        {connected && (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-400">
            <CheckCircle size={12} weight="fill" />
            Conectat
          </span>
        )}
      </div>
      <input
        type="password"
        value={value}
        onChange={onChange}
        disabled={disabled}
        placeholder={connected ? "Completează doar dacă vrei să o înlocuiești" : placeholder}
        autoComplete="off"
        className="rounded-xl border border-border-subtle bg-background px-4 py-3 text-sm text-foreground placeholder:text-foreground-muted/60 outline-none transition-colors focus:border-brand-cyan disabled:cursor-not-allowed disabled:opacity-60"
      />
    </div>
  );
}

export function CredentialsForm({
  token,
  initialStatus,
}: {
  token: string;
  initialStatus: ConnectionStatus;
}) {
  const [googleToken, setGoogleToken] = useState("");
  const [metaToken, setMetaToken] = useState("");
  const [tiktokToken, setTiktokToken] = useState("");
  const [chatgptKey, setChatgptKey] = useState("");
  const [status, setStatus] = useState(initialStatus);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccessMessage(null);

    // Trimite DOAR campurile completate acum - un camp lasat gol nu trebuie
    // sa suprascrie cu "" o cheie deja conectata la o vizita anterioara.
    const payload: CredentialsUpdateInput = {};
    if (googleToken.trim()) payload.google_ads_refresh_token = googleToken.trim();
    if (metaToken.trim()) payload.meta_access_token = metaToken.trim();
    if (tiktokToken.trim()) payload.tiktok_access_token = tiktokToken.trim();
    if (chatgptKey.trim()) payload.chatgpt_ads_api_key = chatgptKey.trim();

    if (Object.keys(payload).length === 0) {
      setError("Completează cel puțin un câmp înainte de a salva.");
      return;
    }

    setSubmitting(true);
    try {
      const { updated_fields } = await updateCredentials(token, payload);
      setStatus((prev) => ({
        google: prev.google || updated_fields.includes("google_ads_refresh_token"),
        meta: prev.meta || updated_fields.includes("meta_access_token"),
        tiktok: prev.tiktok || updated_fields.includes("tiktok_access_token"),
        chatgpt: prev.chatgpt || updated_fields.includes("chatgpt_ads_api_key"),
      }));
      // Cheia introdusa nu ramane in state-ul paginii mai mult decat strict
      // necesar pentru submit - golita imediat dupa succes.
      setGoogleToken("");
      setMetaToken("");
      setTiktokToken("");
      setChatgptKey("");
      setSuccessMessage("Salvat. Cheile sunt criptate imediat, nu rămân în clar nicăieri.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ceva nu a mers bine. Încearcă din nou.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-5 rounded-3xl border border-border-subtle bg-background-elevated p-6 md:p-8"
    >
      <div className="flex items-center gap-2">
        <LockSimple size={16} className="text-brand-cyan" />
        <h2 className="text-lg font-semibold text-foreground">
          Acces pentru agentul AI
        </h2>
      </div>
      <p className="text-sm text-foreground-muted">
        Cheile se criptează imediat ce le trimiți. Nu le mai poți vedea înapoi
        aici, nici tu, nici noi. Doar agentul le folosește, direct.
      </p>

      <div className="grid gap-5">
        <CredentialField
          label="Google Ads: Refresh Token"
          placeholder="1//..."
          connected={status.google}
          value={googleToken}
          onChange={(e) => setGoogleToken(e.target.value)}
          disabled={submitting}
        />
        <CredentialField
          label="Meta: Access Token"
          placeholder="EAAG..."
          connected={status.meta}
          value={metaToken}
          onChange={(e) => setMetaToken(e.target.value)}
          disabled={submitting}
        />
        <CredentialField
          label="TikTok: Access Token"
          placeholder="act..."
          connected={status.tiktok}
          value={tiktokToken}
          onChange={(e) => setTiktokToken(e.target.value)}
          disabled={submitting}
        />
        <div>
          <CredentialField
            label="ChatGPT (OpenAI Ads): Cheie API"
            placeholder="sk-..."
            connected={status.chatgpt}
            value={chatgptKey}
            onChange={(e) => setChatgptKey(e.target.value)}
            disabled={submitting}
          />
          <p className="mt-1.5 text-xs text-foreground-muted">
            O salvăm criptat de-acum, dar reclamele ChatGPT nu rulează încă -
            OpenAI dă acces la API doar partenerilor aprobați.
          </p>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded-xl bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {error}
        </p>
      )}
      {successMessage && (
        <p className="rounded-xl bg-emerald-500/10 px-4 py-3 text-sm text-emerald-400">
          {successMessage}
        </p>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-full bg-brand-blue px-6 py-3.5 text-sm font-semibold text-white transition-transform hover:scale-[1.01] active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
      >
        {submitting ? "Se salvează..." : "Salvează"}
      </button>
    </form>
  );
}
