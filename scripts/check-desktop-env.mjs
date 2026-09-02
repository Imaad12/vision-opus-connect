// Fails the desktop build early and loudly if the Supabase env vars it
// needs are missing, instead of silently shipping a `.app`/`.dmg` that
// packages and installs cleanly but crashes on first render. Root cause
// (see DESKTOP_RUNTIME_ERROR_FIX.md): the desktop shell's SSR/prerender
// pass never runs React effects, so a build with no VITE_SUPABASE_URL /
// VITE_SUPABASE_PUBLISHABLE_KEY still exits 0 -- the throw only happens
// once a real browser/webview hydrates the page and __root.tsx's effect
// touches the lazily-initialized Supabase client.
//
// Uses Vite's own loadEnv so this checks exactly what the following
// `vite build` will actually see (same .env/.env.local/envDir rules),
// rather than re-implementing env-file parsing.
import { loadEnv } from "vite";

import { checkSupabaseKey } from "./supabase-env-checks.mjs";

// VITE_API_URL deliberately not required here (unlike check-web-env.mjs):
// api.ts's own localhost fallback is fine for a desktop dev build, and a
// real desktop release build's value is a deployment concern, checked
// manually rather than blocking every local `tauri:dev` run.
const REQUIRED = ["VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY"];

// VITE_DESKTOP_DEV_EMAIL / VITE_DESKTOP_DEV_PASSWORD (src/lib/
// tauri-dev-auth.ts) are NOT required: desktop now uses the same native
// VINCO username/password login form as web (src/components/
// sign-in-card.tsx) by default -- nothing in the UI calls the old
// auto-login path anymore, on any build, so a production desktop build
// no longer needs these at all. They remain optional/unused inputs for
// anyone still invoking signInDesktopDevAccount() by hand as a dev
// utility.

const mode = process.env["NODE_ENV"] === "development" ? "development" : "production";
const env = { ...loadEnv(mode, process.cwd(), ""), ...process.env };

const missing = REQUIRED.filter((key) => !env[key]);

if (missing.length > 0) {
  console.error(
    `\n[check-desktop-env] Missing required env var(s): ${missing.join(", ")}\n\n` +
      "The desktop build bakes these into the app bundle at build time via\n" +
      "Vite's import.meta.env.\n\n" +
      "The build still succeeds and produces a working-looking .app/.dmg,\n" +
      "but the app crashes immediately on launch -- TanStack's root error\n" +
      'boundary shows "This page didn\'t load" -- because the Supabase\n' +
      "client throws the first time it's touched.\n\n" +
      "Fix: copy .env.example to .env in the project root and fill in\n" +
      "real values, then re-run `bun run tauri:build`.\n",
  );
  process.exit(1);
}

// Catches a different, later-stage failure than "missing": present but
// wrong values. Both the desktop build and the Supabase client itself
// happily accept a placeholder, truncated, or wrong-project key -- the
// build still exits 0 and the app still renders its login screen (the
// Supabase client only throws on a *missing* value, see above), so
// nothing surfaces this until a real Google sign-in attempt fails with
// Supabase's own "Invalid API key" (a gateway-level rejection of the
// `apikey` header, unrelated to OAuth/PKCE mechanics -- see
// DESKTOP_OAUTH_INVALID_KEY_FIX.md). None of these checks can prove a
// key is *correct* (that requires a real request to Supabase), but they
// catch the two concrete failure shapes a copy-paste mistake produces:
// a stub/placeholder value, and a key that names a different project
// than SUPABASE_URL.
const url = env["VITE_SUPABASE_URL"];
const key = env["VITE_SUPABASE_PUBLISHABLE_KEY"];
const warnings = checkSupabaseKey(url, key).map((w) => `VITE_SUPABASE_PUBLISHABLE_KEY ${w}`);

if (warnings.length > 0) {
  console.warn(
    `\n[check-desktop-env] VITE_SUPABASE_PUBLISHABLE_KEY looks suspicious (not blocking the ` +
      `build, since this can't be fully verified without a live request to Supabase):\n\n` +
      warnings.map((w) => `  - ${w}`).join("\n") +
      "\n\nDouble-check Project Settings -> API in the Supabase Dashboard for the project " +
      `at ${url} and compare against your .env.\n`,
  );
} else {
  console.log("[check-desktop-env] Required Supabase env vars present and structurally valid.");
}
