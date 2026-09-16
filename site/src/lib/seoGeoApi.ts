/**
 * Client subtire peste API-ul seo_geo_agent - agent AI SEPARAT de ppc_agent_server
 * (alt proces, alt port, vezi seo_geo_agent/app.py din radacina proiectului).
 * NEXT_PUBLIC_SEO_GEO_API_URL implicit http://localhost:8001. Foloseste acelasi
 * token de client (Bearer, din lib/auth.ts) ca restul site-ului - seo_geo_agent
 * valideaza acelasi JWT emis de ppc_agent_server, fara un al doilea login.
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
  client_reports: string;
  target_audience?: string;
}

export function analyzeSeoGeo(token: string, input: AnalysisRequestInput): Promise<AnalysisResponse> {
  return seoGeoFetch<AnalysisResponse>("/api/v1/seo-geo/analyze", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
}
