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
 * This adapter calls into `src-tauri/src/keychain.rs`, which stores each
 * value in the OS's own secure credential facility -- Windows Credential
 * Manager, macOS Keychain, or the Linux Secret Service -- via the Rust
 * `keyring` crate. That is the same protection every other desktop
 * application on the machine uses for its own secrets, and (on Windows
 * and macOS) OS-managed encryption at rest, not just OS file
 * permissions.
 *
 * An earlier version of this adapter used `@tauri-apps/plugin-store`
 * (a JSON file under the OS per-app data directory) as a deliberately
 * named first step, with this exact upgrade named as the follow-up --
 * see DESKTOP_ARCHITECTURE.md's original "DESKTOP STORAGE" section. That
 * plugin has been removed now that this replaces it; nothing else in the
 * app depended on it.
 *
 * Nothing privileged ever passes through here: only the short-lived
 * Supabase user access/refresh token pair the web build already keeps in
 * `localStorage`. No service-role key, database credential, or other
 * secret is ever read, written, or in scope here -- the desktop app
 * remains a public OAuth client, exactly like the web app.
 */
import { invoke } from "@tauri-apps/api/core";

import type { SupportedStorage } from "@supabase/supabase-js";

export const tauriSecureStorage: SupportedStorage = {
  async getItem(key: string) {
    const value = await invoke<string | null>("keychain_get", { key });
    return value ?? null;
  },
  async setItem(key: string, value: string) {
    await invoke("keychain_set", { key, value });
  },
  async removeItem(key: string) {
    await invoke("keychain_delete", { key });
  },
};
