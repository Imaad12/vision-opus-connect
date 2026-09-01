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

// Deliberately visible in the browser console (not a secret -- just the
// backend base URL) so a build-time env-injection problem is provable
// from the deployed site itself: open DevTools on the live app and this
// line shows exactly what VITE_API_URL resolved to in *this* bundle,
// with no dependency on dashboard access or on trusting a redeploy
// actually picked up a new value.
if (typeof window !== "undefined") {
  console.info(`[vinco] API_BASE_URL = ${API_BASE_URL}`);
}

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

// Without this, a hung backend connection (dropped network, a stuck
// request on the server) leaves fetch() pending forever -- every
// useQuery/useMutation built on `request()` would then spin its loading
// state indefinitely, with no error to show and no way for the user to
// recover short of restarting the app. 30s is generous for this app's
// actual endpoints (dashboard's own aggregation queries, the slowest
// path, complete in low single-digit seconds -- see the dashboard
// performance work) while still bounding the worst case.
const REQUEST_TIMEOUT_MS = 30_000;

// The backend (app/api/deps.py) only ever returns 401 for a missing or
// invalid/expired bearer token -- never for a permission failure (that's
// 403). So on 401 the right move is always the same: drop the stale
// session so the app's existing SIGNED_OUT handling (__root.tsx's
// onAuthStateChange -> router.invalidate()) redirects through /auth,
// where the desktop build re-authenticates automatically (see
// tauri-dev-auth.ts) and the web build shows its normal sign-in screen --
// instead of every page on a stale/expired session showing the same
// opaque "Missing bearer token" error with no way out.
let handlingUnauthorized = false;
function handleUnauthorized(): void {
  if (handlingUnauthorized) return;
  handlingUnauthorized = true;
  void supabase.auth.signOut().finally(() => {
    handlingUnauthorized = false;
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(await authHeaders()),
        ...init?.headers,
      },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "TimeoutError") {
      // Deliberately does not say "try again" for a write: whether the
      // backend received and applied it before the connection died is
      // unknown, and re-submitting blind risks a duplicate invoice/PO/
      // payment/etc. A GET is always safe to just retry.
      throw new ApiError(
        0,
        method === "GET"
          ? "Request timed out. Check your connection and try again."
          : "Request timed out. This may or may not have been saved -- check before retrying.",
      );
    }
    throw err;
  }

  if (response.status === 401) handleUnauthorized();

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
