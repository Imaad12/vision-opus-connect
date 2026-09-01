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
const hasApiUrl = Boolean(rawApiUrl && rawApiUrl.trim() !== "");

// scripts/check-web-env.mjs (and check-desktop-env.mjs's equivalent)
// already fail the BUILD if this is missing -- this is defense in depth
// for the one thing that check can't see: whatever actually invokes the
// build in Cloudflare's own dashboard. Neither this repo nor this build
// controls that command (no wrangler.toml -- see
// INFRASTRUCTURE_INVENTORY.md), so if it ever bypasses `bun run build`
// (and its env-check prefix) the localhost fallback below would
// otherwise ship silently to every real visitor's browser. Refusing
// outright, the same way src/integrations/supabase/client.ts already
// throws on a missing Supabase URL/key -- caught by the same root error
// boundary, which renders `error.name: error.message` directly on
// screen instead of every page quietly failing with an opaque "Load
// failed" and no indication why. Exported as a plain function (rather
// than inlined) so this logic is unit-testable without fighting
// module-load-time import.meta.env semantics.
export function assertApiUrlConfiguredInProduction(hasUrl: boolean, isProd: boolean): void {
  if (!hasUrl && isProd) {
    throw new Error(
      "VITE_API_URL is not set in this production build. Refusing to silently default to " +
        "http://localhost:8000 -- that would be reachable from nobody's browser but the " +
        "machine that built it. Set VITE_API_URL wherever this build's environment is " +
        "configured (the Cloudflare Pages dashboard's Settings -> Environment variables for " +
        "the web deploy) and rebuild.",
    );
  }
}

// import.meta.env.PROD is false under vitest (mode "test") and under
// plain `vite dev`, so local development keeps the existing localhost
// default unaffected.
assertApiUrlConfiguredInProduction(hasApiUrl, import.meta.env.PROD);

const API_BASE_URL = hasApiUrl ? (rawApiUrl as string) : "http://localhost:8000";

// Deliberately visible in the browser console (not a secret -- just the
// backend base URL) so a build-time env-injection problem is provable
// from the deployed site itself: open DevTools on the live app and this
// line shows exactly what VITE_API_URL resolved to in *this* bundle,
// with no dependency on dashboard access or on trusting a redeploy
// actually picked up a new value.
if (typeof window !== "undefined") {
  console.info(`[vinco] API_BASE_URL = ${API_BASE_URL}`);
}

// Distinguishes what actually happened, since a raw browser fetch error
// gives no HTTP status at all and every webview/browser reports it with
// the same opaque, non-diagnostic message ("Load failed" in WKWebView,
// "Failed to fetch" in Chrome) whether the cause was DNS, a dropped
// connection, or a blocked CORS preflight -- there is no way for JS to
// tell those apart, so `kind` names what IS known instead of guessing.
export type ApiErrorKind = "http" | "timeout" | "network";

export class ApiError extends Error {
  status: number;
  kind: ApiErrorKind;
  method: string;
  path: string;

  constructor(status: number, message: string, kind: ApiErrorKind, method: string, path: string) {
    super(message);
    this.status = status;
    this.kind = kind;
    this.method = method;
    this.path = path;
  }

  /** One-line, human-readable summary safe to render directly in the UI. */
  describe(): string {
    const where = `${this.method} ${this.path}`;
    if (this.kind === "timeout") return `${where} — ${this.message}`;
    if (this.kind === "network") {
      return `${where} — no response from the server (${this.message}). This means the ` +
        "request never got an HTTP response at all: check your network connection, that " +
        "the API is reachable, and (for the desktop app) that its origin is allowed by " +
        "the backend's CORS configuration.";
    }
    const hint = HTTP_STATUS_HINTS[this.status];
    return `${where} — HTTP ${this.status}${hint ? ` (${hint})` : ""}: ${this.message}`;
  }
}

const HTTP_STATUS_HINTS: Record<number, string> = {
  401: "session expired or invalid — signing out",
  403: "insufficient permissions",
  404: "endpoint not found on the deployed backend",
  422: "invalid data",
  500: "server error",
};

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
        "timeout",
        method,
        path,
      );
    }
    // fetch() rejected with no Response at all: DNS failure, refused
    // connection, TLS error, or a blocked CORS preflight all look
    // identical from here (every browser/webview reports them with the
    // same opaque message, e.g. WKWebView's bare "Load failed") -- there
    // is no API to ask which one happened, so this names the endpoint
    // and the raw browser message instead of pretending to know more.
    const raw = err instanceof Error ? err.message : String(err);
    throw new ApiError(0, raw, "network", method, path);
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
    throw new ApiError(response.status, detail, "http", method, path);
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
