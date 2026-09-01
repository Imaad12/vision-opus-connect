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

const REQUIRED = ["VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY"];

const mode = process.env["NODE_ENV"] === "development" ? "development" : "production";
const env = { ...loadEnv(mode, process.cwd(), ""), ...process.env };

const missing = REQUIRED.filter((key) => !env[key]);

if (missing.length > 0) {
  console.error(
    `\n[check-desktop-env] Missing required env var(s): ${missing.join(", ")}\n\n` +
      "The desktop build bakes these into the app bundle at build time via\n" +
      "Vite's import.meta.env. Without them, `tauri build` still succeeds\n" +
      "and produces a working-looking .app/.dmg, but the app crashes\n" +
      "immediately on launch -- TanStack's root error boundary shows\n" +
      '"This page didn\'t load" -- because the Supabase client throws the\n' +
      "first time it's touched.\n\n" +
      "Fix: copy .env.example to .env in the project root and fill in\n" +
      "real values from the Supabase Dashboard (Project Settings -> API),\n" +
      "then re-run `bun run tauri:build`.\n",
  );
  process.exit(1);
}

console.log("[check-desktop-env] Required Supabase env vars present.");
