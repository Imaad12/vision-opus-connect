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
 * `@tauri-apps/plugin-store` instead persists to a JSON file under the
 * OS's per-app data directory (e.g. `%APPDATA%\com.visioncontracting.vinco\`
 * on Windows, `~/Library/Application Support/com.visioncontracting.vinco/`
 * on macOS) -- protected by normal OS user-account file permissions, not
 * readable by other applications or other OS users. That is a real
 * improvement over an in-webview store without adding a new dependency
 * surface (no OS keychain prompt, no separate secrets-management crate).
 *
 * It is NOT full OS-keychain-grade encryption at rest (Windows Credential
 * Manager / macOS Keychain via `tauri-plugin-keyring` or
 * `tauri-plugin-stronghold` would be). That upgrade is a reasonable next
 * hardening step once the desktop app is actually shipping to users,
 * deliberately not pulled in for this first proof-of-concept -- per the
 * "do not implement blindly" instruction, this starts with the simpler,
 * well-supported option and documents the stronger one rather than
 * guessing at how much security investment this deserves on day one.
 */
import { LazyStore } from "@tauri-apps/plugin-store";

import type { SupportedStorage } from "@supabase/supabase-js";

const SESSION_STORE_FILE = "vinco-session.json";

const store = new LazyStore(SESSION_STORE_FILE);

export const tauriSecureStorage: SupportedStorage = {
  async getItem(key: string) {
    const value = await store.get<string>(key);
    return value ?? null;
  },
  async setItem(key: string, value: string) {
    await store.set(key, value);
    await store.save();
  },
  async removeItem(key: string) {
    await store.delete(key);
    await store.save();
  },
};
