/**
 * Thin client for the Vision Contracting backend's FastAPI layer.
 *
 * Auth is the same Supabase session the rest of the app already uses --
 * this just forwards the access token as a bearer credential, exactly as
 * `api-architecture.md` (backend repo) describes: the backend verifies it
 * against Supabase's JWKS and checks permissions via Supabase's own
 * `can()` function using this same token, never a separate login.
 */
import { supabase } from "@/integrations/supabase/client";

// `??` alone isn't enough here: an env var that resolves to an empty
// string (present but blank, e.g. a Cloudflare variable set with no
// value) is not nullish, so `?? fallback` would silently leave
// API_BASE_URL as "" -- turning every request into a same-origin
// relative fetch (against whatever origin served the page) instead of
// hitting the backend at all. Blank must be treated as unset too.
const rawApiUrl = import.meta.env["VITE_API_URL"] as string | undefined;
const API_BASE_URL = rawApiUrl && rawApiUrl.trim() !== "" ? rawApiUrl : "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(await authHeaders()),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body (e.g. a proxy/network failure page) -- fall
      // back to the status text rather than throwing a parse error.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function withQuery(path: string, params?: Record<string, string | undefined>): string {
  if (!params) return path;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, value);
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

export const api = {
  get: <T>(path: string, params?: Record<string, string | undefined>) =>
    request<T>(withQuery(path, params)),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
};
