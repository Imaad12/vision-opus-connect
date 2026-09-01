/**
 * Supabase session storage for the desktop (Tauri) build only.
 *
 * The web app stores its Supabase session in `localStorage`, which is
 * fine there -- the webview/browser profile is already the OS-level
 * privacy boundary. A Tauri app's webview also has a `localStorage`, but
 * it's an implementation detail of the embedded webview (WebView2 on
 * Windows, WKWebView on macOS) rather than a place a user or IT admin
 * would expect an application's credentials to live, and it's not
 * necessarily covered by the same "clear browsing data" tooling a user
 * might use to intentionally wipe leaked secrets.
 *
 * This adapter calls into `src-tauri/src/session_store.rs`, which stores
 * each value in a plain JSON file under the OS's own per-app data
 * directory. It previously used the OS's secure credential facility
 * (Windows Credential Manager / macOS Keychain / Linux Secret Service,
 * via the Rust `keyring` crate) instead -- switched away from that
 * because, on an unsigned/ad-hoc-signed build, macOS ties a Keychain
 * item's "always allow" grant to the requesting app's code-signing
 * identity, and an ad-hoc signature's identity changes with every
 * rebuild (it's derived from the binary's own bytes). The result was an
 * OS authorization prompt on every single new build, with no code-level
 * fix available short of a stable code-signing certificate -- a one-time
 * manual macOS-side setup step outside what this codebase controls (see
 * DESKTOP_ARCHITECTURE.md's signing notes). This trades away the OS's
 * managed encryption-at-rest and its "which app may read this" prompt in
 * exchange for the app actually launching on every build; it is not a
 * step down from what the web build already does -- see below.
 *
 * Nothing privileged ever passes through here: only the short-lived
 * Supabase user access/refresh token pair the web build already keeps in
 * `localStorage`, protected there only by OS-user-level file/profile
 * permissions -- the same protection level this file's JSON store has.
 * No service-role key, database credential, or other secret is ever
 * read, written, or in scope here -- the desktop app remains a public
 * OAuth client, exactly like the web app, and every request still
 * carries a real Supabase-issued JWT, verified server-side exactly as
 * before. Nothing about backend authentication changes.
 */
import { invoke } from "@tauri-apps/api/core";

import type { SupportedStorage } from "@supabase/supabase-js";

export const tauriDesktopStorage: SupportedStorage = {
  async getItem(key: string) {
    const value = await invoke<string | null>("session_store_get", { key });
    return value ?? null;
  },
  async setItem(key: string, value: string) {
    await invoke("session_store_set", { key, value });
  },
  async removeItem(key: string) {
    await invoke("session_store_delete", { key });
  },
};
