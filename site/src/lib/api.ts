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

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    throw new ApiError(0, "Nu se poate contacta serverul. Verifică conexiunea și încearcă din nou.");
  }

  if (!response.ok) {
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
    throw new ApiError(response.status, detail);
  }

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
  member: "strategist" | "cfo";
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
  financial_status: FinancialStatus;
  directive_status: "ok" | "insufficient_data";
  generated_at: string;
}

/** Limita serverului (ppc_agent_server/services/council.py, MAX_QUESTION_CHARS). */
export const QUEEN_MAX_QUESTION_CHARS = 1000;

/**
 * O intrebare pentru Regina. Serverul isi consulta consiliul (strategia de brand
 * + CFO-ul) inainte sa raspunda - cateva secunde cand vocea LLM e configurata.
 */
export function askQueen(token: string, message: string): Promise<QueenChatReply> {
  return apiFetch<QueenChatReply>("/api/v1/queen/chat", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ message }),
  });
}
