/**
 * Stocare token JWT per-vizitator (localStorage) - doar pe client, niciodata
 * pe server (SSR). Nu e o sesiune securizata production-grade (un cookie
 * httponly ar fi mai potrivit contra XSS), dar site-ul nu are alt state de
 * server inca; suficient pentru fluxul curent (semnare -> conectare conturi).
 */
const TOKEN_KEY = "ac-media-token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // localStorage indisponibil (mod privat etc.) - sesiunea curenta tot
    // functioneaza in memorie, doar nu supravietuieste unui refresh.
  }
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // vezi setToken
  }
}
