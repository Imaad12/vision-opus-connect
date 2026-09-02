/**
 * Native VINCO username/password sign-in -- shared by the web login form
 * and (once migrated, see Phase 8 in the request that added this) the
 * desktop app.
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
 * This calls `supabase.auth.signInWithPassword` directly (the same
 * mechanism `tauri-dev-auth.ts`'s desktop auto-login already uses) --
 * the password is never sent to VINCO's own backend, only to Supabase.
 * A successful sign-in produces a completely normal Supabase session:
 * `src/lib/api.ts` forwards its access_token as a Bearer header exactly
 * like any other session, and the backend verifies/authorizes it
 * unchanged.
 */
import { supabase } from "@/integrations/supabase/client";

export const USERNAME_EMAIL_DOMAIN = "vinco.local";

export function usernameToEmail(username: string): string {
  return `${username.trim().toLowerCase()}@${USERNAME_EMAIL_DOMAIN}`;
}

export type SignInResult = { ok: true } | { ok: false; message: string };

export async function signInWithUsernamePassword(
  username: string,
  password: string,
): Promise<SignInResult> {
  const trimmed = username.trim();
  if (!trimmed || !password) {
    return { ok: false, message: "Enter your username and password." };
  }

  const { error } = await supabase.auth.signInWithPassword({
    email: usernameToEmail(trimmed),
    password,
  });

  if (error) {
    // Supabase's own message for both "no such user" and "wrong
    // password" is the same generic "Invalid login credentials" --
    // deliberately not distinguished further here (confirming which
    // one it was would let an attacker enumerate valid usernames).
    return { ok: false, message: "Incorrect username or password." };
  }

  return { ok: true };
}
