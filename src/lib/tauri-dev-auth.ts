/**
 * Desktop MVP auto-login -- TEMPORARY, internal-development only.
 *
 * Google OAuth (src/lib/tauri-auth.ts) is parked for now: no browser
 * redirect, no vinco://auth-callback, no PKCE. Until VINCO has its own
 * username/password/role system for the desktop app (see
 * DESKTOP_AUTH_MVP.md), the desktop build instead signs in automatically,
 * at launch, as ONE dedicated internal Supabase account -- so the app can
 * open straight to the dashboard while still going through the exact same
 * backend/RBAC path every other session already uses.
 *
 * This is deliberately NOT a new auth architecture:
 *   - The credential pair is a normal Supabase email/password login
 *     (`signInWithPassword`), the same mechanism Supabase auth already
 *     supports -- just invoked by code instead of typed into a form.
 *   - The resulting session is a completely normal Supabase session:
 *     `src/lib/api.ts` forwards its access_token as a Bearer header
 *     exactly as it does for any human-signed-in session, and the backend
 *     (`app/api/deps.py`) verifies it against Supabase's JWKS and checks
 *     permissions via Supabase's own `can()` function, unmodified.
 *   - The account's permissions come entirely from the existing
 *     `user_roles`/`role_permissions` tables in Supabase, exactly like
 *     any other user -- this does not grant any capability the backend
 *     doesn't already know how to check.
 *   - Nothing here ever touches a service-role key, a fabricated JWT, or
 *     any backend code -- see DESKTOP_AUTH_MVP.md for what was
 *     considered and ruled out, and why.
 *
 * The credential pair itself is read from env vars baked in at desktop
 * build time (VITE_DESKTOP_DEV_EMAIL / VITE_DESKTOP_DEV_PASSWORD, see
 * .env.example and scripts/check-desktop-env.mjs), never hardcoded or
 * committed -- same convention as VITE_SUPABASE_URL/KEY.
 */
import { supabase } from "@/integrations/supabase/client";

function logDevAuthDiagnostic(event: string, data: Record<string, unknown> = {}): void {
  console.info(`[tauri-dev-auth] ${event}`, data);
}

/**
 * Signs in as the desktop MVP's dedicated internal account, unless a
 * session already exists (e.g. restored from the OS keychain on a warm
 * launch -- see src/lib/tauri-storage.ts). Call once at desktop app
 * startup; safe to call again (a no-op once a session exists).
 */
export async function signInDesktopDevAccount(): Promise<void> {
  const { data } = await supabase.auth.getSession();
  if (data.session) {
    logDevAuthDiagnostic("existing_session_found", {});
    return;
  }

  const email = import.meta.env["VITE_DESKTOP_DEV_EMAIL"] as string | undefined;
  const password = import.meta.env["VITE_DESKTOP_DEV_PASSWORD"] as string | undefined;
  if (!email || !password) {
    throw new Error(
      "VITE_DESKTOP_DEV_EMAIL / VITE_DESKTOP_DEV_PASSWORD are not set. See DESKTOP_AUTH_MVP.md " +
        "for how to create the desktop MVP's internal Supabase account and configure .env.",
    );
  }

  logDevAuthDiagnostic("sign_in_started", {});
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    logDevAuthDiagnostic("sign_in_failed", {
      name: error.name,
      message: error.message,
      status: error.status,
    });
    throw error;
  }
  logDevAuthDiagnostic("sign_in_succeeded", {});
}
