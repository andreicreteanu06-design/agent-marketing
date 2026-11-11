"use client";

import { ShinyButton } from "@/components/ui/shiny-button";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowUpRight, ArrowClockwise, Lightning, ShieldCheck } from "@phosphor-icons/react/dist/ssr";
import { ApiError, getNativeAutomations, nativeAutomationAction, type NativeConfig, type NativeField, type NativeOverview, type NativePlan, type NativeWorkflow } from "@/lib/api";
import { getToken } from "@/lib/auth";

const STATUS: Record<string,string> = { queued:"În așteptare", running:"În pregătire", prepared:"Mesaje pregătite", skipped:"Nu este necesară o acțiune", failed:"Pregătire eșuată", pending:"De aprobat", ready:"Aprobat, așteaptă trimiterea", sending:"În curs de trimitere", sent:"Trimis", blocked:"Configurare necesară", uncertain:"Livrare de verificat", cancelled:"Anulat" };
const initialValues = (w: NativeWorkflow) => Object.fromEntries(w.fields.map(f=>[f.name,f.default ?? ""]));

export function AutomationWorkspace() {
  const [data,setData] = useState<NativeOverview | null>(null);
  const [status,setStatus] = useState<"loading"|"guest"|"ready"|"error">("loading");
  const [slug,setSlug] = useState("leaduri");
  const [values,setValues] = useState<Record<string,unknown>>({});
  const [config,setConfig] = useState<NativeConfig | null>(null);
  const [eventId,setEventId] = useState("");
  const [editing,setEditing] = useState<number | null>(null);
  const [plan,setPlan] = useState<NativePlan | null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const [secret,setSecret] = useState<{key:string;url:string} | null>(null);
  const [revealed,setRevealed] = useState(false);
  const [keyConfirm,setKeyConfirm] = useState(false);

  const load = useCallback(async (initial=false, signal?:AbortSignal) => {
    const token=getToken();
    if(!token) {setStatus("guest");return;}
    try {
      const result=await getNativeAutomations(token,signal);
      if(signal?.aborted)return;
      setData(result);setStatus("ready");
      if(initial) {
        const requested=new URLSearchParams(window.location.search).get("flux");
        const first=result.workflows.find(w=>w.id===requested) ?? result.workflows[0];
        setSlug(first.id);setConfig(first.config);setValues(initialValues(first));setEventId(crypto.randomUUID());
      }
    } catch(err) {
      if(signal?.aborted)return;
      if(err instanceof ApiError && err.status===401) {setSecret(null);setData(null);setStatus("guest");}
      else {setStatus("error");setError(err instanceof Error?err.message:"Nu am putut încărca automatizările.");}
    }
  },[]);
  useEffect(()=>{
    const controller=new AbortController();
    // Initial authenticated read. No workflow activation or credential creation.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(true,controller.signal);
    return ()=>controller.abort();
  },[load]);

  async function action(work: (token:string)=>Promise<void>) {
    const token=getToken();if(!token){setStatus("guest");setSecret(null);return;}
    if(busy)return;
    setBusy(true);setError("");setNotice("");
    try {await work(token);}
    catch(err){if(err instanceof ApiError&&err.status===401){setSecret(null);setData(null);setStatus("guest");}else setError(err instanceof Error?err.message:"Acțiunea nu a reușit.");}
    finally {setBusy(false);}
  }
  const workflow=data?.workflows.find(w=>w.id===slug);
  function select(w:NativeWorkflow) {
    setSlug(w.id);setConfig(w.config);setValues(initialValues(w));setEditing(null);setPlan(null);setSecret(null);setKeyConfirm(false);setRevealed(false);setEventId(crypto.randomUUID());setError("");setNotice("");
  }
  function payload() {
    return Object.fromEntries((workflow?.fields ?? []).map(f=>[f.name,f.type === "checkbox" ? Boolean(values[f.name]) : f.type === "number" && !f.required && values[f.name] === "" ? null : values[f.name]]));
  }
  async function preview() {await action(async token=>{setPlan(await nativeAutomationAction<NativePlan>(token,`/${slug}/preview`,"POST",{event_id:eventId,data:payload()}));setNotice("Previzualizare: niciun mesaj trimis și nicio înregistrare salvată. Textele AI se pregătesc la rulare.");});}
  async function submit(e:FormEvent<HTMLFormElement>) {
    e.preventDefault();await action(async token=>{
      if(editing!==null) {await nativeAutomationAction(token,`/records/${editing}`,"PUT",payload());setNotice("Date actualizate. Ciornele vechi au fost anulate; etapele viitoare vor folosi datele noi.");}
      else {const result=await nativeAutomationAction<{duplicate:boolean}>(token,`/${slug}/events`,"POST",{event_id:eventId,data:payload()});setNotice(result.duplicate?"Acest eveniment există deja. Nu am creat o rulare dublă.":"Eveniment înregistrat. Urmărește rezultatul și mesajele în istoric.");}
      setPlan(null);await load();
    });
  }
  function field(f:NativeField) {
    const id="native-"+f.name;
    if(f.type==="checkbox") return <label className="native-check" key={f.name}><input id={id} type="checkbox" checked={Boolean(values[f.name])} onChange={e=>setValues(v=>({...v,[f.name]:e.target.checked}))} disabled={busy}/><span>{f.label}</span></label>;
    return <label key={f.name} className={f.type==="textarea"?"native-field native-field--wide":"native-field"} htmlFor={id}><span>{f.label}{!f.required&&" (opțional)"}</span>{f.type==="textarea"?<textarea id={id} rows={4} value={String(values[f.name]??"")} onChange={e=>setValues(v=>({...v,[f.name]:e.target.value}))} required={f.required} maxLength={f.maxLength} disabled={busy}/>:<input id={id} type={f.type} value={String(values[f.name]??"")} onChange={e=>setValues(v=>({...v,[f.name]:e.target.value}))} required={f.required} maxLength={f.maxLength} step={f.type==="number"?"any":undefined} min={f.type==="number"?0:undefined} disabled={busy|| (editing!==null&&["order_id","invoice_id"].includes(f.name))}/>}</label>;
  }

  if(status==="loading")return <p className="native-empty" role="status">Se încarcă automatizările…</p>;
  if(status==="guest")return <section className="native-guest"><ShieldCheck size={28}/><h2>Procesele tale, în contul tău.</h2><p>Autentifică-te pentru configurare, previzualizări și istoric. Fiecare flux pornește în modul cu aprobare.</p><div><Link className="enterprise-button" href="/login">Autentificare <ArrowUpRight size={18}/></Link><Link className="enterprise-text-link" href="/servicii/automatizari#automatizari">Explorează cele 9 fluxuri</Link></div></section>;
  if(status==="error"||!workflow||!config||!data)return <section className="native-empty"><p role="alert">{error||"Automatizările nu sunt disponibile acum."}</p><button className="mcp-secondary" onClick={()=>void load(true)}>Reîncearcă</button></section>;
  const messages=data.messages.filter(m=>m.workflow===slug);
  const runs=data.runs.filter(r=>r.workflow===slug);
  const records=data.records.filter(r=>r.workflow===slug);

  return <div className="native-workspace">
    <div className="native-toolbar"><Link href="/cont" className="enterprise-text-link">← Contul meu</Link><button className="mcp-secondary" disabled={busy} onClick={()=>void action(async()=>{await load();setNotice("Istoric actualizat.");})}><ArrowClockwise size={17}/>Actualizează</button></div>
    <div className="native-note"><Lightning size={20}/><p>Execuție direct în AC Media. {data.email_ready?"Transportul de email este configurat pe server.":"Emailul nu este activ pe server. Poți previzualiza și pregăti mesaje; trimiterea necesită configurarea SMTP."}</p></div>
    <div className="workflow-filters" role="group" aria-label="Alege fluxul">{data.workflows.map(w=><button key={w.id} aria-pressed={slug===w.id} disabled={busy} onClick={()=>select(w)}>{w.title}</button>)}</div>
    <div className="native-status" aria-live="polite">{error?<p className="native-error" role="alert">{error}</p>:notice?<p>{notice}</p>:busy?<p>Se procesează…</p>:null}</div>
    <section className="native-panel"><div className="native-panel__heading"><h2>{workflow.title}</h2><span>{workflow.config.enabled?"Activ":"Pe pauză"}</span></div>
      <details className="native-settings"><summary>Configurare și mod de trimitere</summary><form onSubmit={e=>{e.preventDefault();void action(async token=>{await nativeAutomationAction(token,`/${slug}/settings`,"PUT",config);await load();setNotice("Setările fluxului au fost salvate.");});}}>
        <div className="native-fields"><label className="native-field"><span>Numele firmei</span><input required maxLength={150} value={config.company_name} onChange={e=>setConfig({...config,company_name:e.target.value})}/></label><label className="native-field"><span>Emailul echipei</span><input type="email" required value={config.team_email} onChange={e=>setConfig({...config,team_email:e.target.value})}/></label><label className="native-field native-field--wide"><span>Contextul firmei pentru răspunsuri</span><textarea rows={3} maxLength={8000} value={config.company_context} onChange={e=>setConfig({...config,company_context:e.target.value})}/></label><label className="native-field"><span>Trimiterea mesajelor</span><select value={config.delivery_mode} onChange={e=>setConfig({...config,delivery_mode:e.target.value as NativeConfig["delivery_mode"]})}><option value="review">Le verific înainte de trimitere</option><option value="automatic">Automat pentru mesaje standard</option></select></label>{slug==="stoc"&&<label className="native-field"><span>Prag implicit de stoc</span><input type="number" min={0} value={config.stock_threshold} onChange={e=>setConfig({...config,stock_threshold:Number(e.target.value)})}/></label>}{slug==="reviewuri"&&<label className="native-field"><span>Zile după livrare</span><input type="number" min={1} max={365} value={config.review_days} onChange={e=>setConfig({...config,review_days:Number(e.target.value)})}/></label>}{slug==="onboarding"&&<><label className="native-field"><span>Memento după câte zile</span><input type="number" min={1} max={90} value={config.onboarding_reminder_days} onChange={e=>setConfig({...config,onboarding_reminder_days:Number(e.target.value)})}/></label><label className="native-field"><span>Verificarea colaborării după câte zile</span><input type="number" min={2} max={365} value={config.onboarding_checkin_days} onChange={e=>setConfig({...config,onboarding_checkin_days:Number(e.target.value)})}/></label></>}</div>
        <p className="native-help">Răspunsurile AI, conținutul de marketing și mesajele de recrutare cer întotdeauna verificare. Modul automat se aplică mesajelor standard, după activarea fluxului.</p><label className="native-check"><input type="checkbox" checked={config.enabled} onChange={e=>setConfig({...config,enabled:e.target.checked})}/><span>Activează primirea evenimentelor și verificările periodice</span></label><ShinyButton type="submit"  disabled={busy}>Salvează setările</ShinyButton>
      </form></details>
      <form className="native-event" onSubmit={submit}><div className="native-event__heading"><h3>{editing!==null?"Actualizează înregistrarea":"Adaugă un eveniment"}</h3><button type="button" className="enterprise-text-link" disabled={busy} onClick={()=>{setValues(workflow.example);setEditing(null);setEventId(crypto.randomUUID());setPlan(null);}}>Folosește un exemplu</button></div>{editing===null&&<label className="native-field"><span>Referință unică (pentru evitarea dublurilor)</span><input required pattern="[a-zA-Z0-9_.:\-]+" maxLength={160} value={eventId} onChange={e=>setEventId(e.target.value)} disabled={busy}/></label>}<div className="native-fields">{workflow.fields.map(field)}</div><div className="native-actions"><button type="button" className="mcp-secondary" disabled={busy} onClick={e=>{if(e.currentTarget.form?.reportValidity())void preview();}}>Previzualizează procesul</button><ShinyButton type="submit"  disabled={busy||(!workflow.config.enabled&&editing===null)}>{editing!==null?"Salvează modificările":"Înregistrează și pregătește"}</ShinyButton>{editing!==null&&<button type="button" className="mcp-secondary" disabled={busy} onClick={()=>select(workflow)}>Eveniment nou</button>}</div>{!workflow.config.enabled&&<p className="native-help">Fluxul este pe pauză. Previzualizarea rămâne disponibilă.</p>}</form>
      {plan&&<div className="native-preview"><h3>{plan.summary}</h3><ol>{plan.steps.map((step,i)=><li key={i}>{step}</li>)}</ol>{plan.messages.map((m,i)=><details key={i}><summary>{m.subject} · {m.recipient}</summary><pre>{m.body}</pre></details>)}</div>}
    </section>
    <section className="native-panel"><div className="native-panel__heading"><h2>Mesajele acestui flux</h2><span>{messages.filter(m=>m.status==="pending").length} de aprobat</span></div><p className="native-help">Verifică destinatarul și conținutul înainte de aprobare.</p>{messages.length===0?<p className="native-empty">Mesajele apar aici după prima rulare.</p>:messages.map(m=><article key={m.id} className="native-message"><div><h3>{m.subject}</h3><p>Către {m.recipient}</p><span className={"native-badge native-badge--"+m.status}>{STATUS[m.status]??m.status}</span></div><details><summary>Citește mesajul</summary><pre>{m.body}</pre></details>{m.error&&<p className="native-help">{m.error}</p>}{["pending","blocked"].includes(m.status)&&<button disabled={busy||!data.email_ready} className="mcp-secondary" onClick={()=>void action(async token=>{const result=await nativeAutomationAction<{status:string}>(token,`/messages/${m.id}/approve`);await load();setNotice(STATUS[result.status]??"Stare actualizată.");})}>Aprobă și trimite</button>}{["pending","blocked","ready"].includes(m.status)&&<button disabled={busy} className="enterprise-text-link" onClick={()=>void action(async token=>{await nativeAutomationAction(token,`/messages/${m.id}/cancel`);await load();setNotice("Mesaj anulat.");})}>Anulează mesajul</button>}</article>)}</section>
    <div className="native-history-grid"><section className="native-panel"><div className="native-panel__heading"><h2>Istoricul rulărilor</h2>{workflow.scheduled&&<button className="mcp-secondary" disabled={busy} onClick={()=>void action(async token=>{await nativeAutomationAction(token,"/check-due");await load();setNotice("Scadențele au fost verificate.");})}>Verifică scadențele</button>}</div><p className="native-help">Ultimele 50 de rulări din cont. Verificările automate necesită workerul platformei pornit.</p>{runs.length===0?<p className="native-empty">Nicio rulare încă.</p>:runs.map(r=><div className="native-run" key={r.id}><strong>#{r.id} · {STATUS[r.status]??r.status}</strong><small>{new Date(r.created_at).toLocaleString("ro-RO")}</small><p>{r.error||r.result.summary}</p>{r.status==="failed"&&<button className="mcp-secondary" disabled={busy} onClick={()=>void action(async token=>{await nativeAutomationAction(token,`/runs/${r.id}/retry`);await load();})}>Reîncearcă pregătirea</button>}</div>)}</section><section className="native-panel"><h2>Înregistrări salvate</h2><p className="native-help">Ultimele 100 din cont. Actualizează plata unei facturi sau completarea formularului pentru a opri mementourile.</p>{records.length===0?<p className="native-empty">Datele vor fi păstrate aici, în aplicație.</p>:records.map(r=><div className="native-record" key={r.id}><span>{r.external_id}</span><button className="mcp-secondary" disabled={busy} onClick={()=>{setValues(r.payload);setEditing(r.id);setEventId(r.external_id);setPlan(null);setNotice("Înregistrarea este încărcată în formularul de mai sus.");}}>Editează</button></div>)}</section></div>
    <details className="native-panel native-webhook"><summary>Conectează un formular, magazin sau serviciu de email</summary><p>Aplicația sursă trimite evenimente direct către AC Media. Fiecare flux are o cheie separată; un eveniment repetat nu creează o rulare dublă.</p>{workflow.webhook_url&&<code>{workflow.webhook_url}</code>}<p className="native-help">Un serviciu de email trebuie configurat să trimită mesajele primite prin acest webhook. Această pagină nu citește automat căsuța Gmail.</p>{secret&&<div className="mcp-new-key"><label htmlFor="native-hook-key">Cheia este afișată o singură dată</label><input id="native-hook-key" type={revealed?"text":"password"} readOnly value={secret.key} autoComplete="off"/><div><button className="mcp-secondary" onClick={()=>setRevealed(v=>!v)}>{revealed?"Ascunde":"Arată"}</button><button className="mcp-secondary" onClick={()=>void action(async()=>{await navigator.clipboard.writeText(secret.key);setNotice("Cheia a fost copiată.");})}>Copiază cheia</button><button className="mcp-secondary" onClick={()=>{setSecret(null);setRevealed(false);}}>Am salvat cheia</button></div></div>}{keyConfirm?<div className="native-actions"><p>Cheia veche va înceta să funcționeze.</p><button className="mcp-secondary" disabled={busy} onClick={()=>void action(async token=>{const result=await nativeAutomationAction<{key:string;webhook_url:string}>(token,`/${slug}/webhook-key`);setSecret({key:result.key,url:result.webhook_url});setRevealed(false);setKeyConfirm(false);await load();})}>Confirmă cheia nouă</button><button className="mcp-secondary" onClick={()=>setKeyConfirm(false)}>Renunță</button></div>:<div className="native-actions"><button className="mcp-secondary" disabled={busy} onClick={()=>{if(workflow.webhook_key_set)setKeyConfirm(true);else void action(async token=>{const result=await nativeAutomationAction<{key:string;webhook_url:string}>(token,`/${slug}/webhook-key`);setSecret({key:result.key,url:result.webhook_url});setRevealed(false);await load();});}}>{workflow.webhook_key_set?"Înlocuiește cheia":"Creează cheia webhook"}</button>{workflow.webhook_key_set&&<button className="mcp-secondary" disabled={busy} onClick={()=>void action(async token=>{await nativeAutomationAction(token,`/${slug}/webhook-key`,"DELETE");setSecret(null);await load();setNotice("Accesul prin webhook a fost revocat.");})}>Revocă accesul</button>}</div>}<details><summary>Format pentru echipa tehnică</summary><p className="native-help">POST cu antetul Authorization: Bearer CHEIA_WEBHOOK. Păstrează event_id identic când reîncerci același eveniment.</p><pre>{JSON.stringify({event_id:"eveniment-unic-123",data:workflow.example},null,2)}</pre></details></details>
  </div>;
}
