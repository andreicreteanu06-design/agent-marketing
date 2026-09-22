/**
 * Client subtire peste API-ul seo_geo_agent - agent AI SEPARAT de ppc_agent_server
 * (alt proces, alt port, vezi seo_geo_agent/app.py din radacina proiectului).
 * NEXT_PUBLIC_SEO_GEO_API_URL implicit http://localhost:8001. Foloseste acelasi
 * token de client (Bearer, din lib/auth.ts) ca restul site-ului - seo_geo_agent
 * valideaza acelasi JWT emis de ppc_agent_server, fara un al doilea login.
 *
 * Doua familii de functii, pentru cele doua moduri ale agentului:
 * - analyzeSeoGeo -> analiza prin LLM (o parere argumentata);
 * - startAudit/getAuditStatus/getAuditResults -> auditul determinist (crawl real,
 *   probleme verificabile). Trei apeluri, nu unul, fiindca un crawl dureaza:
 *   pornesti, intrebi de progres, iei raportul. Vezi seo_geo_agent/router.py.
 */
const SEO_GEO_API_BASE_URL = process.env.NEXT_PUBLIC_SEO_GEO_API_URL ?? "http://localhost:8001";

export class SeoGeoApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function seoGeoFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${SEO_GEO_API_BASE_URL}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    throw new SeoGeoApiError(
      0,
      "Nu se poate contacta serverul de analiză. Verifică conexiunea și încearcă din nou."
    );
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
          // Forma FastAPI/Pydantic pentru 422 (validare): o lista de erori per
          // camp, nu un string simplu - vezi seo_geo_agent/schemas.py.
          const messages = rawDetail
            .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : null))
            .filter((msg): msg is string => msg !== null);
          if (messages.length > 0) detail = messages.join(" ");
        }
      }
    } catch {
      // raspuns fara corp JSON valid - pastreaza statusText
    }
    throw new SeoGeoApiError(response.status, detail);
  }

  return response.json() as Promise<T>;
}

/* -------------------------------------------------------------------------- */
/* Analiza prin LLM                                                            */
/* -------------------------------------------------------------------------- */

export interface ActionableSuggestion {
  category: string;
  current_issue: string;
  exact_fix: string;
}

export interface AnalysisResponse {
  seo_score: number;
  geo_score: number;
  seo_suggestions: ActionableSuggestion[];
  geo_suggestions: ActionableSuggestion[];
}

export interface AnalysisRequestInput {
  domain: string;
  client_reports?: string;
  target_audience?: string;
}

export function analyzeSeoGeo(token: string, input: AnalysisRequestInput): Promise<AnalysisResponse> {
  return seoGeoFetch<AnalysisResponse>("/api/v1/seo-geo/analyze", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
}

/* -------------------------------------------------------------------------- */
/* Audit determinist                                                           */
/* -------------------------------------------------------------------------- */

export type IssueSeverity = "critical" | "warning" | "info";
export type IssuePillar = "seo" | "geo";
export type AuditStatus = "running" | "completed" | "failed";
export type PageFetchClass = "ok" | "blocked" | "rate_limited" | "error";

export interface AffectedPage {
  page_url: string;
  /** Valorile masurate acolo (lungimi, status-uri, URL-uri tinta) - dovada problemei. */
  details: Record<string, unknown>;
}

export interface IssueGroup {
  issue_type: string;
  severity: IssueSeverity;
  pillar: IssuePillar;
  title: string;
  explanation: string;
  how_to_fix: string;
  count: number;
  affected_pages: AffectedPage[];
}

export interface AuditPageRow {
  url: string;
  status_code: number;
  fetch_class: PageFetchClass;
  title: string;
  meta_description: string;
  word_count: number;
  h1_count: number;
  images_total: number;
  images_missing_alt: number;
  internal_links: number;
  response_time_ms: number;
  is_indexable: boolean;
  has_structured_data: boolean;
  crawl_depth: number | null;
  in_sitemap: boolean;
  issue_count: number;
}

export interface PillarScore {
  score: number;
  checks_run: number;
  checks_failed: number;
}

export interface AuditSummary {
  pages_crawled: number;
  /** false = crawl-ul s-a oprit din buget, deci raportul e partial. */
  completed: boolean;
  robots_txt_found: boolean;
  llms_txt_found: boolean;
  sitemap_urls_found: number;
  critical_count: number;
  warning_count: number;
  info_count: number;
  blocked_pages: number;
  rate_limited_pages: number;
  started_at: string;
  finished_at: string;
}

export interface AuditResults {
  audit_id: string;
  domain: string;
  start_url: string;
  brand: string;
  summary: AuditSummary;
  seo: PillarScore;
  geo: PillarScore;
  issues: IssueGroup[];
  pages: AuditPageRow[];
}

export interface AuditStarted {
  audit_id: string;
  status: AuditStatus;
  domain: string;
}

export interface AuditStatusResponse {
  audit_id: string;
  status: AuditStatus;
  crawled: number;
  queued: number;
  max_pages: number;
  error: string | null;
}

export interface AuditRequestInput {
  domain: string;
  max_pages?: number;
  brand?: string;
}

export function startAudit(token: string, input: AuditRequestInput): Promise<AuditStarted> {
  return seoGeoFetch<AuditStarted>("/api/v1/seo-geo/audit", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
}

export function getAuditStatus(token: string, auditId: string): Promise<AuditStatusResponse> {
  return seoGeoFetch<AuditStatusResponse>(`/api/v1/seo-geo/audit/${auditId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export function getAuditResults(token: string, auditId: string): Promise<AuditResults> {
  return seoGeoFetch<AuditResults>(`/api/v1/seo-geo/audit/${auditId}/results`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

/** Cat asteptam intre doua interogari de stare. Crawl-ul avanseaza in secunde, nu in milisecunde. */
export const AUDIT_POLL_INTERVAL_MS = 1500;
