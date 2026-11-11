"use client";

import { ShinyButton } from "@/components/ui/shiny-button";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowUpRight, Copy, Key, PlugsConnected, ShieldCheck } from "@phosphor-icons/react/dist/ssr";
import { ApiError, MCP_ENDPOINT, createMcpKey, listMcpKeys, revokeMcpKey, type CreatedMcpKey, type McpKey } from "@/lib/api";
import { getToken } from "@/lib/auth";

export function McpConnectionPanel() {
  const [status, setStatus] = useState<"loading" | "guest" | "ready" | "error">("loading");
  const [keys, setKeys] = useState<McpKey[]>([]);
  const [fresh, setFresh] = useState<CreatedMcpKey | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [client, setClient] = useState<"codex" | "claude">("codex");
  const [copyStatus, setCopyStatus] = useState("");
  const [endpoint, setEndpoint] = useState(MCP_ENDPOINT);

  const load = useCallback(async (signal?: AbortSignal) => {
    const token = getToken();
    if (!token) { setStatus("guest"); return; }
    setStatus("loading"); setError("");
    try { const result = await listMcpKeys(token, signal); if (!signal?.aborted) { setKeys(result); setStatus("ready"); } }
    catch (err) { if (signal?.aborted) return; setStatus(err instanceof ApiError && err.status === 401 ? "guest" : "error"); setError(err instanceof Error ? err.message : "Nu am putut încărca integrările."); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    // Initial authenticated request; no automatic key creation.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const token = getToken();
    if (!token) { setStatus("guest"); return; }
    if (!name.trim() || busy) return;
    setBusy(true); setError(""); setCopyStatus("");
    try {
      const result = await createMcpKey(token, name.trim());
      setFresh(result); setEndpoint(result.mcp_url); setRevealed(false); setName("");
      const { id, name: keyName, created_at, revoked_at } = result;
      setKeys(previous => [{ id, name: keyName, created_at, revoked_at }, ...previous]);
    } catch (err) { setError(err instanceof Error ? err.message : "Cheia nu a putut fi creată."); }
    finally { setBusy(false); }
  }
  async function revoke(id: number) {
    const token = getToken(); if (!token || busy) return;
    setBusy(true); setError("");
    try { const result = await revokeMcpKey(token, id); setKeys(previous => previous.map(k => k.id === id ? result : k)); if (fresh?.id === id) setFresh(null); setConfirmId(null); }
    catch (err) { setError(err instanceof Error ? err.message : "Nu am putut revoca cheia."); }
    finally { setBusy(false); }
  }
  async function copy(value: string, label: string) {
    try { await navigator.clipboard.writeText(value); setCopyStatus(label + " copiată."); }
    catch { setCopyStatus("Copierea automată nu este disponibilă. Selectează textul și copiază-l manual."); }
  }
  const config = client === "codex"
    ? `[mcp_servers.ac_media]\nurl = ${JSON.stringify(endpoint)}\nbearer_token_env_var = "AC_MEDIA_MCP_KEY"`
    : JSON.stringify({ mcpServers: { "ac-media": { type: "http", url: endpoint, headers: { Authorization: "Bearer ${AC_MEDIA_MCP_KEY}" } } } }, null, 2);

  return <section id="conectare" className="mcp-connection" aria-labelledby="mcp-connection-title">
    <div className="mcp-connection__heading"><PlugsConnected size={25} /><div><h2 id="mcp-connection-title">Conectează-ți agentul.</h2><p>O cheie dedicată, un server, datele contului tău.</p></div></div>
    <div className="mcp-connection__columns">
      <div className="mcp-access">
        <h3>Accesul agentului</h3>
        {status === "loading" && <p role="status">Se verifică sesiunea…</p>}
        {status === "guest" && <div className="mcp-guest"><p>Autentifică-te pentru a crea o cheie MCP și a gestiona accesul agenților la contul tău.</p><Link href="/login" className="enterprise-button">Autentificare <ArrowUpRight size={17} /></Link><Link href="/creeaza-cont" className="enterprise-text-link">Creează cont</Link></div>}
        {status === "error" && <div><p role="alert">{error}</p><button type="button" className="mcp-secondary" onClick={() => void load()}>Reîncearcă</button></div>}
        {status === "ready" && <>
          {!fresh && <form onSubmit={create} className="mcp-key-form"><label htmlFor="mcp-key-name">Numele agentului</label><input id="mcp-key-name" value={name} onChange={e=>setName(e.target.value)} placeholder="De exemplu, Codex — echipa marketing" maxLength={100} required disabled={busy} /><ShinyButton type="submit" disabled={busy || !name.trim()} ><Key size={17} />{busy ? "Se creează…" : "Creează cheia MCP"}</ShinyButton></form>}
          {fresh && <div className="mcp-new-key"><h4>Cheia pentru {fresh.name}</h4><p>Copiază cheia acum. Serverul nu o mai afișează după această etapă.</p><label className="sr-only" htmlFor="mcp-secret">Cheie MCP nouă</label><input id="mcp-secret" type={revealed ? "text" : "password"} readOnly value={fresh.key} autoComplete="off" spellCheck={false} /><div><button type="button" className="mcp-secondary" onClick={()=>void copy(fresh.key,"Cheie")}>Copiază cheia</button><button type="button" className="mcp-secondary" onClick={()=>setRevealed(v=>!v)}>{revealed ? "Ascunde" : "Arată"}</button></div><button type="button" className="enterprise-text-link" onClick={()=>{setFresh(null);setRevealed(false);}}>Am salvat cheia</button></div>}
          {error && <p className="mcp-error" role="alert">{error}</p>}
          <div className="mcp-key-list"><h4>Agenții tăi</h4>{keys.length === 0 && <p>Nu ai creat încă o cheie pentru un agent.</p>}{keys.map(k=><div key={k.id} className="mcp-key-row"><div><strong>{k.name}</strong><small>{k.revoked_at ? "Acces revocat" : "Cheie activă"} · {new Date(k.created_at).toLocaleDateString("ro-RO")}</small></div>{!k.revoked_at && (confirmId === k.id ? <div className="mcp-revoke"><span>Oprești accesul?</span><button type="button" disabled={busy} onClick={()=>void revoke(k.id)}>Da, revocă</button><button type="button" disabled={busy} onClick={()=>setConfirmId(null)}>Renunță</button></div> : <button type="button" className="mcp-secondary" disabled={busy} onClick={()=>setConfirmId(k.id)}>Revocă</button>)}</div>)}</div>
        </>}
      </div>
      <div className="mcp-setup">
        <h3>Alege aplicația</h3>
        <div className="mcp-client-picker" role="group" aria-label="Aplicația AI"><button type="button" aria-pressed={client === "codex"} onClick={()=>setClient("codex")}>Codex</button><button type="button" aria-pressed={client === "claude"} onClick={()=>setClient("claude")}>Claude Code</button></div>
        <p>Salvează cheia generată în variabila de mediu <code>AC_MEDIA_MCP_KEY</code> a mediului din care pornești agentul.</p>
        <p>{client === "codex" ? "Adaugă configurația de mai jos în fișierul ~/.codex/config.toml, apoi pornește Codex din același mediu." : "Adaugă această configurație în fișierul .mcp.json al proiectului, apoi pornește Claude Code din același mediu."}</p>
        <pre tabIndex={0} aria-label="Configurație MCP"><code>{config}</code></pre>
        <button type="button" className="mcp-secondary" onClick={()=>void copy(config,"Configurație")}><Copy size={16} />Copiază configurația</button>
        <div className="mcp-endpoint"><span>Server MCP · Streamable HTTP</span><code>{endpoint}</code></div>
        <p className="mcp-compatibility">Configurația folosește o cheie Bearer. Clienții care cer exclusiv OAuth au nevoie de un conector suplimentar.</p>
        <a className="enterprise-text-link" href={client === "claude" ? "https://code.claude.com/docs/en/mcp" : "https://developers.openai.com/codex/mcp"} target="_blank" rel="noreferrer">Documentația aplicației <ArrowUpRight size={16} /></a>
      </div>
    </div>
    <p className="mcp-copy-status" role="status">{copyStatus}</p>
    <div className="mcp-permission-note"><ShieldCheck size={22} /><p>Agentul vede doar datele contului asociat cheii. Propunerile de buget așteaptă aprobarea ta în platformă. Poți revoca accesul oricând.</p></div>
  </section>;
}
