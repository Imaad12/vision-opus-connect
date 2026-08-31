/**
 * Google sign-in for the desktop (Tauri) build.
 *
 * Google's OAuth policy disallows sign-in from an embedded webview (the
 * "disallowed_useragent" error) -- Tauri's window IS an embedded webview,
 * so the web app's plain `signInWithOAuth` (which navigates the current
 * window straight to Google) cannot be reused as-is under Tauri. This
 * module is the desktop-only alternative:
 *
 *   1. Ask Supabase for the Google authorize URL without letting it
 *      navigate anywhere (`skipBrowserRedirect: true`), with `redirectTo`
 *      pointed at the app's own `vinco://auth-callback` deep link instead
 *      of an `https://` page.
 *   2. Open that URL in the user's REAL system browser
 *      (`@tauri-apps/plugin-opener`) -- a standard, trusted browser
 *      context Google's policy allows.
 *   3. The system browser completes the Google + Supabase OAuth dance and
 *      redirects to `vinco://auth-callback#access_token=...`. The OS
 *      hands that URL back to this already-running app via
 *      `@tauri-apps/plugin-deep-link`'s `onOpenUrl` listener (registered
 *      once, in `initTauriDeepLinkAuth` below), which extracts the tokens
 *      and calls `supabase.auth.setSession(...)` itself -- the exact same
 *      call the web build's Supabase client makes internally after its
 *      own redirect completes.
 *
 * Nothing here talks to Google or Supabase directly beyond calls the web
 * client already makes (`signInWithOAuth`, `setSession`); no new backend
 * surface, no service-role or other privileged credential is ever
 * touched by this module -- it only ever handles the same short-lived
 * user access/refresh token pair the web build's `onAuthStateChange`
 * already sees after every sign-in.
 *
 * `vinco://auth-callback` requires a matching entry in Google Cloud
 * Console's OAuth client "Authorized redirect URIs" and in Supabase
 * Auth's allowed redirect URLs -- neither is added by this change (see
 * DESKTOP_ARCHITECTURE.md); until that dashboard configuration exists,
 * `signInWithGoogleDesktop` will reach Google fine but the final redirect
 * back to the app will fail, exactly as it would on the web build if its
 * own redirect URL weren't registered.
 */
import { onOpenUrl } from "@tauri-apps/plugin-deep-link";
import { openUrl } from "@tauri-apps/plugin-opener";

import { supabase } from "@/integrations/supabase/client";

export const DESKTOP_OAUTH_REDIRECT_URL = "vinco://auth-callback";

export async function signInWithGoogleDesktop(): Promise<void> {
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: DESKTOP_OAUTH_REDIRECT_URL,
      skipBrowserRedirect: true,
    },
  });
  if (error) throw error;
  if (!data.url) throw new Error("Supabase did not return an OAuth URL.");
  await openUrl(data.url);
  // No further action here: the deep-link listener registered by
  // `initTauriDeepLinkAuth` picks up the callback once the system
  // browser redirects back, and `onAuthStateChange` (already wired in
  // __root.tsx for the web build too) reacts to the resulting SIGNED_IN
  // event the same way either build got there.
}

function parseCallbackUrl(url: string): { access_token: string; refresh_token: string } | null {
  let fragment: string;
  try {
    fragment = new URL(url).hash.replace(/^#/, "");
  } catch {
    return null;
  }
  const params = new URLSearchParams(fragment);
  const access_token = params.get("access_token");
  const refresh_token = params.get("refresh_token");
  if (!access_token || !refresh_token) return null;
  return { access_token, refresh_token };
}

/** Call once at app startup under Tauri (see __root.tsx). No-op on web. */
export async function initTauriDeepLinkAuth(): Promise<void> {
  await onOpenUrl(async (urls) => {
    for (const url of urls) {
      if (!url.startsWith(DESKTOP_OAUTH_REDIRECT_URL)) continue;
      const tokens = parseCallbackUrl(url);
      if (!tokens) continue;
      const { error } = await supabase.auth.setSession(tokens);
      if (error) console.error("[tauri-auth] setSession failed:", error);
    }
  });
}
