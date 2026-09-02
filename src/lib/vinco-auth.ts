/**
 * Native VINCO username/password sign-in -- shared by the web login form
 * and the desktop app (both render the same login screen; see
 * src/components/sign-in-card.tsx).
 *
 * Employees only ever see and type a username. Supabase Auth itself
 * requires an email-shaped identifier, so a native VINCO account's real
 * Supabase email is always `<username>@vinco.local` -- a synthetic,
 * never-reachable address, never shown to the employee. This constant
 * MUST match the backend's `USERNAME_EMAIL_DOMAIN`
 * (backend/app/services/user_service.py) exactly: both sides derive the
 * same address from the same username rather than one looking it up
 * from the other, so login needs no extra round trip before calling
 * Supabase directly.
 *
 * This calls `supabase.auth.signInWithPassword` directly -- the password
 * is never sent to VINCO's own backend, only to Supabase. A successful
 * sign-in produces a completely normal Supabase session: `src/lib/api.ts`
 * forwards its access_token as a Bearer header exactly like any other
 * session, and the backend verifies/authorizes it unchanged.
 */
import type { AuthError } from "@supabase/supabase-js";

import { supabase } from "@/integrations/supabase/client";

export const USERNAME_EMAIL_DOMAIN = "vinco.local";

export function usernameToEmail(username: string): string {
  return `${username.trim().toLowerCase()}@${USERNAME_EMAIL_DOMAIN}`;
}

export type SignInFailureKind = "empty" | "invalid_credentials" | "inactive" | "network";

export type SignInResult = { ok: true } | { ok: false; kind: SignInFailureKind };

/**
 * Classifies a failed sign-in by structurally inspecting the error's
 * `name`/`code` (this app only depends on the public `@supabase/
 * supabase-js` package, which doesn't re-export auth-js's internal
 * `AuthRetryableFetchError`/`isAuthApiError` helpers to import directly,
 * so duck-typing the same fields their own `toJSON()` exposes is the
 * stable, public-surface way to do this) rather than assuming every
 * failure is a bad password.
 *
 * - `name === "AuthRetryableFetchError"`: a network-level failure
 *   (offline, DNS, timeout, CORS) -- Supabase's own request never
 *   completed at all.
 * - `code === "user_banned"`: GoTrue's documented code for a banned/
 *   deactivated account -- confirmed present in current Supabase Auth
 *   versions, but community-reported as inconsistent across older/other
 *   deployments (some return the exact same generic "Invalid login
 *   credentials" for a banned account as for a wrong password, with no
 *   distinguishing code at all). When present, used; when absent, an
 *   inactive account is genuinely indistinguishable from a wrong
 *   password from here, and correctly falls through to that message --
 *   not a bug, a real limitation of what Supabase's API exposes.
 * - Anything else: treated as wrong username/password, deliberately not
 *   distinguishing "no such user" from "wrong password" (doing so would
 *   let an attacker enumerate valid usernames).
 */
function classifySignInError(error: AuthError): SignInFailureKind {
  if (error.name === "AuthRetryableFetchError") return "network";
  if (error.code === "user_banned") return "inactive";
  return "invalid_credentials";
}

export async function signInWithUsernamePassword(
  username: string,
  password: string,
): Promise<SignInResult> {
  const trimmed = username.trim();
  if (!trimmed || !password) {
    return { ok: false, kind: "empty" };
  }

  const { error } = await supabase.auth.signInWithPassword({
    email: usernameToEmail(trimmed),
    password,
  });

  if (error) {
    return { ok: false, kind: classifySignInError(error) };
  }

  return { ok: true };
}
