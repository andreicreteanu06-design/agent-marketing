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
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // raspuns fara corp JSON valid - pastreaza statusText
    }
    throw new ApiError(response.status, detail);
  }

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
