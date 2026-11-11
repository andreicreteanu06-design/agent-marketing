/**
 * Client subtire peste API-ul ppc_agent_server (FastAPI, alt port/domeniu -
 * vezi CORSMiddleware din ppc_agent_server/app.py). NEXT_PUBLIC_API_URL
 * implicit http://localhost:8000 (server-ul rulat local, vezi README).
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const OFFLINE_MESSAGE =
  "Nu se poate contacta serverul. Verifică conexiunea și încearcă din nou.";

/** Eroarea unui raspuns ne-2xx, cu mesajul serverului ("detail") cand exista. */
async function apiError(response: Response): Promise<ApiError> {
  let detail = response.statusText || "A apărut o eroare neașteptată.";
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const rawDetail = (body as { detail: unknown }).detail;
      if (typeof rawDetail === "string") {
        detail = rawDetail;
      } else if (Array.isArray(rawDetail)) {
        // Erorile de validare (422) vin ca lista, cate una per camp; mesajul
        // nostru e precedat de prefixul Pydantic "Value error, ".
        const messages = rawDetail
          .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : null))
          .filter((msg): msg is string => msg !== null)
          .map((msg) => msg.replace(/^Value error, /, ""));
        if (messages.length > 0) detail = messages.join(" ");
      }
    }
  } catch {
    // raspuns fara corp JSON valid - pastreaza statusText
  }
  return new ApiError(response.status, detail);
}

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    throw new ApiError(0, OFFLINE_MESSAGE);
  }

  if (!response.ok) throw await apiError(response);

  // 204 (ex. deconectarea unei integrari) nu are corp - response.json() ar arunca.
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export function signup(input: { name: string; email: string; password: string }): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/api/v1/signup", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function login(input: { email: string; password: string }): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/api/v1/login", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export interface ClientAccountInfo {
  id: number;
  name: string;
  target_domain: string;
  geo: string;
  language: string;
  google_ads_customer_id: string;
  meta_ad_account_id: string;
  tiktok_advertiser_id: string;
  /** Numele brandului, pentru verificarile GEO din audit. Gol = dedus din domeniu. */
  brand_name: string;
  max_daily_spend: string;
  default_lead_value: string;
  objective: string;
  created_at: string;
}

export interface ClientUserInfo {
  id: number;
  email: string;
  client_account_id: number;
  created_at: string;
}

export interface MeResponse {
  user: ClientUserInfo;
  account: ClientAccountInfo;
  google_ads_connected: boolean;
  meta_connected: boolean;
  tiktok_connected: boolean;
  chatgpt_connected: boolean;
}

export function getMe(token: string): Promise<MeResponse> {
  return apiFetch<MeResponse>("/api/v1/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export interface CredentialsUpdateInput {
  google_ads_refresh_token?: string;
  meta_access_token?: string;
  tiktok_access_token?: string;
  chatgpt_ads_api_key?: string;
}

export interface CredentialsUpdateResponse {
  updated_fields: string[];
}

export function updateCredentials(
  token: string,
  input: CredentialsUpdateInput
): Promise<CredentialsUpdateResponse> {
  return apiFetch<CredentialsUpdateResponse>("/api/v1/me/credentials", {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
}

/* -------------------------------------------------------------------------- */
/* Site-ul clientului (Setari)                                                 */
/* -------------------------------------------------------------------------- */

export interface SiteSettingsInput {
  /** Salvat de server ca origine: "artingauto.ro" devine "https://artingauto.ro". */
  target_domain?: string;
  brand_name?: string;
}

export function updateSiteSettings(token: string, input: SiteSettingsInput): Promise<ClientAccountInfo> {
  return apiFetch<ClientAccountInfo>("/api/v1/me/site", {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
}

/* -------------------------------------------------------------------------- */
/* Integrari Google (Search Console, Analytics 4)                              */
/* -------------------------------------------------------------------------- */

export type IntegrationName = "gsc" | "ga4";

export interface IntegrationState {
  connected: boolean;
  /** "sc-domain:exemplu.ro" / URL la Search Console, ID numeric la GA4. Gol = neales. */
  property_id: string;
}

export interface IntegrationsStatus {
  /** false = serverul n-are client OAuth Google, deci conectarea nu poate porni. */
  oauth_configured: boolean;
  gsc: IntegrationState;
  ga4: IntegrationState;
}

export interface IntegrationProperty {
  id: string;
  label: string;
}

export function getIntegrations(token: string): Promise<IntegrationsStatus> {
  return apiFetch<IntegrationsStatus>("/api/v1/integrations", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

/** URL-ul ecranului de consimtamant Google; site-ul navigheaza direct acolo. */
export function getIntegrationAuthUrl(token: string, name: IntegrationName): Promise<{ auth_url: string }> {
  return apiFetch<{ auth_url: string }>(`/api/v1/integrations/${name}/auth-url`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export function getIntegrationProperties(token: string, name: IntegrationName): Promise<IntegrationProperty[]> {
  return apiFetch<IntegrationProperty[]>(`/api/v1/integrations/${name}/properties`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export function updateIntegration(
  token: string,
  name: IntegrationName,
  propertyId: string
): Promise<IntegrationState> {
  return apiFetch<IntegrationState>(`/api/v1/integrations/${name}`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ property_id: propertyId }),
  });
}

export function disconnectIntegration(token: string, name: IntegrationName): Promise<void> {
  return apiFetch<void>(`/api/v1/integrations/${name}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
}

/* -------------------------------------------------------------------------- */
/* Trafic & Pozitii (GA4 + Search Console + Keyword Planner)                   */
/* -------------------------------------------------------------------------- */

export type SeoSourceKey = "ga4" | "gsc" | "keyword_planner";
/** live = datele clientului; demo = simulate (sursa neconectata); unavailable = conectata, dar picata. */
export type SeoSourceStatus = "live" | "demo" | "not_connected" | "unavailable";
export type SeoMetricKey =
  | "sessions"
  | "pageviews"
  | "engagement_rate"
  | "clicks"
  | "impressions"
  | "ctr"
  | "position";

export interface SeoTimeSeriesPoint {
  date: string;
  /** null = sursa nu are date pentru graficul asta, nu "zero". */
  sessions: number | null;
  pageviews: number | null;
  engagement_rate: number | null;
  clicks: number | null;
  impressions: number | null;
  ctr: number | null;
  position: number | null;
}

export interface SeoMetricSummary {
  key: SeoMetricKey;
  label: string;
  source: "ga4" | "gsc";
  value: number | null;
  previous: number | null;
  change_pct: number | null;
  /** Pozitia e mai buna cand SCADE. */
  better_when: "up" | "down";
  format: "number" | "percent" | "position";
}

export interface SeoKeywordRank {
  keyword: string;
  position: number;
  previous_position: number | null;
  /** Pozitii castigate (pozitiv = a urcat); null la cuvintele noi. */
  change: number | null;
  trend: "up" | "down" | "stable" | "new";
  clicks: number;
  impressions: number;
  ctr: number;
  search_volume: number | null;
  url: string | null;
}

export interface SeoInsight {
  id: string;
  rule: string;
  kind: "alert" | "opportunity" | "info";
  priority: "high" | "medium" | "low";
  title: string;
  detail: string;
  action: string;
  evidence: Record<string, string>;
  subject: string | null;
}

export interface SeoIntelligence {
  version: 1;
  domain: string;
  period: { start: string; end: string; days: number };
  previous_period: { start: string; end: string; days: number };
  generated_at: string;
  /** true daca cel putin o sursa afisata e demonstrativa. */
  is_demo: boolean;
  sources: { key: SeoSourceKey; label: string; status: SeoSourceStatus; note: string | null }[];
  summary: SeoMetricSummary[];
  timeseries: SeoTimeSeriesPoint[];
  keywords: SeoKeywordRank[];
  ai_recommendations: SeoInsight[];
  recommendations_engine: "rules";
  data_gaps: string[];
}

export function getSeoIntelligence(token: string, days: 7 | 28 | 90): Promise<SeoIntelligence> {
  return apiFetch<SeoIntelligence>(`/api/v1/seo/intelligence?days=${days}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

/* -------------------------------------------------------------------------- */
/* Regina (CMO) - chatul deliberat de consiliu                                 */
/* -------------------------------------------------------------------------- */

export type CouncilTopic = "budget" | "channel" | "profitability" | "audience" | "creative" | "general";
/** Verdictul CFO-ului, calculat determinist din cifrele contului. */
export type FinancialStatus = "profitable" | "unprofitable" | "no_benchmark" | "insufficient_data";
/** llm = formulat de model; template = raspunsul determinist (fara cheie, eroare, text respins). */
export type MessageSource = "llm" | "template";

export interface CouncilOpinion {
  member: "strategist" | "cfo" | "technician" | "researcher" | "cpo";
  title: string;
  opinion: string;
  source: MessageSource;
  model: string | null;
  fallback_reason: string | null;
}

export interface CouncilRuling {
  topic: CouncilTopic;
  /** Platforma pe care clientul NU are inca reclame si despre care a intrebat. */
  new_channel: string | null;
  financial_status: FinancialStatus;
  brand_status: "ok" | "insufficient_data";
  decision: string;
  /** Ideile care trec de ambele scaune (brand + CFO). */
  approved: string[];
  /** Ideile creative taiate de CFO, fiecare cu motivul. */
  cut: string[];
  /** De ce a pus Tehnicianul veto (tracking picat, site lent pe mobil); null = fara veto. */
  veto: string | null;
  /** Ideile care ar fi trecut de brand si de CFO, oprite de veto-ul Tehnicianului. */
  vetoed: string[];
  /** Contextul pietei pentru intrebare (Researcher-ul), doar din surse reale. */
  market_context?: string | null;
  /** Verdictul CPO-ului pe oferta, cand intervine (CPA peste tinta, pozitionare de ascutit). */
  offer?: string | null;
  /** Disputele transate de reguli: materialul rundei de replici. */
  conflicts?: CouncilConflict[];
  /** Cand se rediscuta ce s-a taiat sau oprit; null = nimic taiat. */
  reopen_when?: string | null;
}

export type CouncilMember = CouncilOpinion["member"];
export type ConflictKind = "veto" | "money_vs_brand" | "market_vs_money" | "offer_vs_message";

/** O disputa din consiliu, transata de regula (decizia nu se negociaza). */
export interface CouncilConflict {
  kind: ConflictKind;
  /** Cine a pierdut disputa - raspunde in runda de replici. */
  challenger: CouncilMember;
  /** Cine a castigat-o. */
  respondent: CouncilMember;
  issue: string;
  rule: string;
  /** Cand revine pe masa - o conditie masurabila, din date. */
  reopen_when: string;
  rebuttal: string;
}

/** Replica unui membru care a pierdut o disputa, catre colegul care a castigat-o. */
export interface CouncilRebuttal {
  member: CouncilMember;
  title: string;
  replying_to: CouncilMember;
  replying_to_title: string;
  conflict: ConflictKind;
  rebuttal: string;
  reopen_when: string;
  source: MessageSource;
  model: string | null;
  fallback_reason: string | null;
}

/** green = verde, amber = la limita, red = rosu, unknown = fara date (nu se ghiceste). */
export type HealthStatus = "green" | "amber" | "red" | "unknown";

/** Raportul Tehnicianului (ppc_agent_server/services/technician.py), calculat determinist. */
export interface TechnicianDirective {
  client_account_id: number;
  status: HealthStatus;
  tracking_status: HealthStatus;
  speed_status: HealthStatus;
  tracking: {
    key: string;
    label: string;
    status: HealthStatus;
    finding: "ok" | "conversions_stopped" | "traffic_stopped" | "never_converted" | "too_little_data";
    evidence: string;
    last_conversion: string | null;
    silent_days: number;
    fix: string | null;
  }[];
  mobile_speed: {
    status: HealthStatus;
    url: string | null;
    measured_at: string | null;
    metrics: {
      key: "lcp" | "cls" | "tbt" | "performance_score";
      label: string;
      value: string;
      threshold: string;
      rating: "good" | "needs_improvement" | "poor";
    }[];
    evidence: string;
    fixes: string[];
  };
  /** money = nicio decizie pe bani (tracking picat); spend = nicio cheltuiala in plus (site lent). */
  veto: "none" | "spend" | "money";
  veto_reason: string | null;
  summary: string;
  recommendations: string[];
  notes: string[];
  generated_at: string;
}

/** Psihologia cumparatorului (ppc_agent_server/services/cognitive.py), calculata determinist. */
export interface CognitiveProfile {
  /** Kahneman: Sistemul 1 (rapid, intuitiv) sau 2 (cantarit). */
  decision_mode: {
    system: "system_1" | "system_2" | "mixed";
    deliberative_share: number;
    label: string;
    evidence: string;
    needs: string[];
  };
  barrier: {
    kind: "friction" | "trust" | "perceived_value" | "none" | "unknown";
    label: string;
    evidence: string;
    remedy: string;
  };
  /** Elaboration Likelihood Model: argumente (centrala) sau semnale rapide (periferica). */
  persuasion_route: { route: "central" | "peripheral" | "dual"; label: string; cues: string[] };
  lever: string;
  summary: string;
}

export interface QueenChatReply {
  client_account_id: number;
  /** Raspunsul sintetizat de Regina, de aratat clientului. */
  reply: string;
  source: MessageSource;
  model: string | null;
  fallback_reason: string | null;
  topic: CouncilTopic;
  ruling: CouncilRuling;
  opinions: CouncilOpinion[];
  /** null cand nu exista inca un client ideal (date insuficiente). */
  psychology: CognitiveProfile | null;
  financial_status: FinancialStatus;
  directive_status: "ok" | "insufficient_data";
  generated_at: string;
  /** Raportul Tehnicianului; null cand consiliul a deliberat fara el. */
  technical: TechnicianDirective | null;
  /** Contextul pietei (Researcher-ul); null cand consiliul a deliberat fara el. */
  market?: MarketDirective | null;
  /** Contextul Istoric pe care l-a primit consiliul (memoria), cate un rand. */
  history?: string[];
  /** Verdictul CPO-ului pe oferta: pozitionarea, povestea, mutarile dupa RICE. */
  product?: ProductDirective | null;
  /** Runda de replici: cine a pierdut o disputa ii raspunde celui care a castigat-o. */
  rebuttals?: CouncilRebuttal[];
}

/** Oferta si pozitionarea (ppc_agent_server/services/cpo.py), calculate determinist. */
export interface ProductDirective {
  client_account_id: number;
  status: "fit" | "message_gap" | "positioning_gap" | "offer_gap" | "pivot" | "unknown";
  /** CFO-ul a gasit CPA-ul peste tinta: CPO-ul a judecat oferta. */
  cpa_alarm: boolean;
  verdict: string;
  focus: string | null;
  best_fit: string | null;
  positioning: string;
  story: string;
  /** Mutarile de oferta, ordonate dupa RICE (Reach x Impact x Confidence / Effort). */
  moves: {
    kind: "pivot" | "reposition" | "offer_test" | "message";
    text: string;
    reach: number;
    impact: number;
    confidence: number;
    effort: number;
    rice: number;
  }[];
  summary: string;
  generated_at: string;
}

/**
 * Contextul pietei (ppc_agent_server/services/researcher.py), doar din surse reale:
 * Google Trends si cautarea pe web. Ce lipseste ramane "unknown", nu se inventeaza.
 */
export interface MarketDirective {
  client_account_id: number;
  market: string;
  period_days: number;
  competitor_activity: {
    pressure: "rising" | "stable" | "easing" | "unknown";
    evidence: string;
    implication: string;
    cpc_change: number | null;
    competitors_before: number | null;
    competitors_now: number | null;
    client_share_change: number | null;
    top_mover: string | null;
  };
  market_trend: {
    direction: "growing" | "flat" | "declining" | "unknown";
    season: "peak" | "rising" | "cooling" | "low" | "normal" | "unknown";
    change: number | null;
    year_over_year: number | null;
    evidence: string;
    window: string;
  };
  social_sentiment: {
    rising: { theme: string; example: string; growth: number; mentions: number }[];
    evidence: string;
  };
  /** Cautarea reala pe web: nisa si orasul clientului, fragmentele gasite (cu site-ul). */
  niche: string;
  location: string;
  web_status: "ok" | "empty" | "failed" | "off";
  web_findings: { query: string; title: string; snippet: string; source: string }[];
  opportunity: string;
  summary: string;
  notes: string[];
  generated_at: string;
}

/** Limita serverului (ppc_agent_server/services/council.py, MAX_QUESTION_CHARS). */
export const QUEEN_MAX_QUESTION_CHARS = 1000;

/**
 * O intrebare pentru Regina. Serverul isi consulta consiliul (strategia de brand,
 * CFO-ul, Tehnicianul, Researcher-ul si CPO-ul) inainte sa raspunda - cateva secunde
 * cand vocea LLM e configurata.
 */
export function askQueen(token: string, message: string): Promise<QueenChatReply> {
  return apiFetch<QueenChatReply>("/api/v1/queen/chat", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ message }),
  });
}

/** Etapele deliberarii, in ordinea in care le anunta serverul. */
export type CouncilStage = "context" | "deliberation" | "rebuttals" | "synthesis";

export interface QueenStreamHandlers {
  onStage?: (stage: CouncilStage) => void;
  /** Un membru al consiliului a vorbit (in ordinea in care termina, nu fix). */
  onOpinion?: (opinion: CouncilOpinion) => void;
  onRebuttal?: (rebuttal: CouncilRebuttal) => void;
  /** Un fragment din sinteza Reginei, pe masura ce o scrie modelul: CIORNA. */
  onToken?: (text: string) => void;
}

function sseEvent(block: string): { name: string; data: unknown } | null {
  let name = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // comentariu: consiliul inca delibereaza
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (data.length === 0) return null;
  try {
    return { name, data: JSON.parse(data.join("\n")) as unknown };
  } catch {
    return null;
  }
}

/**
 * Aceeasi intrebare, in flux (Server-Sent Events, POST /api/v1/queen/chat cu
 * Accept: text/event-stream): etapele, fiecare parere cand e gata, sinteza Reginei
 * token cu token si, la final, raspunsul valabil - intors de functie, care
 * inlocuieste ciorna (poate fi cel determinist, daca modelul a picat sau a scris
 * ceva ce nu e in date). EventSource nu poate trimite POST cu token, deci fetch.
 */
export async function askQueenStream(
  token: string,
  message: string,
  handlers: QueenStreamHandlers = {},
  signal?: AbortSignal
): Promise<QueenChatReply> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/queen/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ message }),
      signal,
    });
  } catch (err: unknown) {
    if (signal?.aborted) throw err;
    throw new ApiError(0, OFFLINE_MESSAGE);
  }
  if (!response.ok) throw await apiError(response);
  // Un server (sau proxy) care raspunde JSON: acelasi raspuns, fara flux.
  const type = response.headers.get("content-type") ?? "";
  if (!type.includes("text/event-stream") || !response.body) {
    return (await response.json()) as QueenChatReply;
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let reply: QueenChatReply | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const event = sseEvent(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
      if (!event) continue;
      const data = event.data as Record<string, unknown>;
      if (event.name === "stage") handlers.onStage?.(data.stage as CouncilStage);
      else if (event.name === "opinion") handlers.onOpinion?.(data as unknown as CouncilOpinion);
      else if (event.name === "rebuttal") handlers.onRebuttal?.(data as unknown as CouncilRebuttal);
      else if (event.name === "token") handlers.onToken?.(String(data.text ?? ""));
      else if (event.name === "reply") reply = data as unknown as QueenChatReply;
      else if (event.name === "error") {
        throw new ApiError(503, String(data.detail ?? "Consiliul nu a putut răspunde acum."));
      }
    }
  }
  if (!reply) {
    throw new ApiError(0, "Conexiunea s-a închis înainte de răspuns. Încearcă din nou.");
  }
  return reply;
}

/* MCP access uses dedicated agent keys, never the browser's login token in client configuration. */
export interface McpKey { id: number; name: string; created_at: string; revoked_at: string | null; }
export interface CreatedMcpKey extends McpKey { key: string; mcp_url: string; }
export const MCP_ENDPOINT = `${API_BASE_URL.replace(/\/$/, "")}/api/v1/mcp/stream`;
export function listMcpKeys(token: string, signal?: AbortSignal): Promise<McpKey[]> {
  return apiFetch<McpKey[]>("/api/v1/me/mcp-keys", { headers: { Authorization: `Bearer ${token}` }, signal });
}
export function createMcpKey(token: string, name: string): Promise<CreatedMcpKey> {
  return apiFetch<CreatedMcpKey>("/api/v1/me/mcp-keys", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ name }) });
}
export function revokeMcpKey(token: string, id: number): Promise<McpKey> {
  return apiFetch<McpKey>(`/api/v1/me/mcp-keys/${id}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
}

export type NativeField = { name: string; label: string; type: string; required: boolean; default: string | number | boolean | null; maxLength?: number };
export type NativeConfig = { enabled: boolean; delivery_mode: "review" | "automatic"; company_name: string; team_email: string; company_context: string; stock_threshold: number; review_days: number; onboarding_reminder_days: number; onboarding_checkin_days: number; timezone: string };
export type NativeWorkflow = { id: string; title: string; scheduled: boolean; fields: NativeField[]; example: Record<string, unknown>; config: NativeConfig; webhook_url: string | null; webhook_key_set: boolean };
export type NativePlan = { stage: string; summary: string; steps: string[]; skipped: boolean; messages: {recipient: string; subject: string; body: string; requires_review: boolean}[]; output: Record<string, unknown> };
export type NativeRun = { id: number; workflow: string; status: string; error: string | null; created_at: string; result: Partial<NativePlan> };
export type NativeMessage = { id: number; run_id: number; workflow: string; recipient: string; subject: string; body: string; status: string; requires_review: boolean; error: string | null };
export type NativeRecord = { id: number; workflow: string; external_id: string; payload: Record<string, unknown> };
export type NativeOverview = { email_ready: boolean; workflows: NativeWorkflow[]; runs: NativeRun[]; messages: NativeMessage[]; records: NativeRecord[] };
const NATIVE_PATH = "/api/v1/me/automations";
export function getNativeAutomations(token: string, signal?: AbortSignal): Promise<NativeOverview> {
  return apiFetch(NATIVE_PATH, { headers: { Authorization: `Bearer ${token}` }, signal });
}
export function nativeAutomationAction<T>(token: string, path: string, method = "POST", body?: unknown): Promise<T> {
  return apiFetch<T>(NATIVE_PATH + path, { method, headers: { Authorization: `Bearer ${token}` }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
}
