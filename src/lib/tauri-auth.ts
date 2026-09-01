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
 *      of an `https://` page. `client.ts` sets `flowType: 'pkce'`, so
 *      this call also generates a PKCE code_verifier and stores it via
 *      `tauriSecureStorage` (the OS keychain) before returning the URL --
 *      a short-lived single-use `code` travels through the browser and
 *      the OS, never the actual access/refresh tokens.
 *   2. Open that URL in the user's REAL system browser
 *      (`@tauri-apps/plugin-opener`) -- a standard, trusted browser
 *      context Google's policy allows.
 *   3. The system browser completes the Google + Supabase OAuth dance and
 *      redirects to `vinco://auth-callback?code=...`. The OS hands that
 *      URL to this app two different ways depending on whether it was
 *      already running -- see `initTauriDeepLinkAuth` below, which
 *      handles both -- and `handleCallbackUrl` exchanges the code for a
 *      session via `supabase.auth.exchangeCodeForSession`, reading back
 *      the code_verifier stored in step 1. Same call the web build's
 *      Supabase client makes internally after its own redirect completes
 *      (also PKCE, since `flowType` is a client-wide setting).
 *
 * Nothing here talks to Google or Supabase directly beyond calls the web
 * client already makes (`signInWithOAuth`, `exchangeCodeForSession`); no
 * new backend surface, no service-role or other privileged credential is
 * ever touched by this module -- it only ever handles the same
 * short-lived user access/refresh token pair the web build's
 * `onAuthStateChange` already sees after every sign-in, and even that
 * pair never appears in a URL under PKCE (only the single-use code does).
 *
 * `vinco://auth-callback` requires a matching entry in Supabase Auth's
 * allowed redirect URLs (Authentication -> URL Configuration -> Redirect
 * URLs in the Supabase dashboard) -- not added by this change, no access
 * to make that change from here. Google Cloud Console's OAuth client does
 * NOT need this URL: Google only ever redirects to Supabase's own fixed
 * `https://<project-ref>.supabase.co/auth/v1/callback`, already
 * registered there (proven by the web flow already working) -- Supabase
 * is what performs the *second* redirect to `redirectTo`, and that step
 * is gated by Supabase's own allow-list, not Google's. Until
 * `vinco://auth-callback` is on that list, Supabase's callback silently
 * falls back to its configured Site URL instead of the app's own scheme
 * -- exactly the "browser lands on the web dashboard, desktop app never
 * hears back" symptom this module exists to fix the app side of.
 */
import { getCurrent, onOpenUrl } from "@tauri-apps/plugin-deep-link";
import { openUrl } from "@tauri-apps/plugin-opener";
import { toast } from "sonner";

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
  // No further action here: initTauriDeepLinkAuth's listener picks up the
  // callback once the system browser redirects back (or, if the user
  // closed the app in the meantime, its getCurrent() check on next
  // launch does), and __root.tsx's onAuthStateChange subscription reacts
  // to the resulting SIGNED_IN event the same way either build does.
}

/**
 * Handles one `vinco://auth-callback?...` URL, however it arrived.
 * Exported for tests -- see tauri-auth.test.ts.
 */
export async function handleAuthCallbackUrl(url: string): Promise<void> {
  if (!url.startsWith(DESKTOP_OAUTH_REDIRECT_URL)) return;

  let params: URLSearchParams;
  try {
    params = new URL(url).searchParams;
  } catch {
    console.error("[tauri-auth] could not parse callback URL:", url);
    return;
  }

  // Google/Supabase report a failed authorization this way (consent
  // denied, misconfigured client, etc.) rather than omitting `code` --
  // surfacing it is the difference between a clear error and the
  // "click Google again" loop this flow was originally reported with.
  const errorDescription = params.get("error_description") ?? params.get("error");
  if (errorDescription) {
    toast.error(errorDescription);
    return;
  }

  const code = params.get("code");
  if (!code) {
    console.error("[tauri-auth] callback URL had neither an error nor a code:", url);
    return;
  }

  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) toast.error(error.message);
}

let deepLinkAuthInitialized = false;

/** Call once at app startup under Tauri (see __root.tsx). No-op on web. */
export async function initTauriDeepLinkAuth(): Promise<void> {
  if (deepLinkAuthInitialized) return;
  deepLinkAuthInitialized = true;

  // Scenario: the app was closed, the user finished sign-in in the
  // browser, and the vinco:// link cold-started this process. The OS
  // still hands the launch URL to the app, but as a CLI argument/launch
  // parameter, not a live event -- onOpenUrl's listener below only fires
  // for links that arrive *after* it's registered, so it would never see
  // this one. getCurrent() is the plugin's documented way to also check
  // "was this process itself started by a deep link".
  const launchUrls = await getCurrent();
  for (const url of launchUrls ?? []) {
    await handleAuthCallbackUrl(url);
  }

  // Scenario: the app was already running (Windows/Linux: the second,
  // about-to-exit process's argv, forwarded here by
  // tauri-plugin-single-instance's "deep-link" feature -- see
  // src-tauri/src/lib.rs; macOS/iOS: the OS delivers it to the running
  // instance directly). Fires for every callback for the rest of this
  // run.
  await onOpenUrl((urls) => {
    for (const url of urls) void handleAuthCallbackUrl(url);
  });
}
