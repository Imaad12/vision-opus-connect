// Fails the web (Cloudflare) production build early and loudly if its
// required env vars are missing, instead of silently shipping a bundle
// that builds and deploys cleanly but is broken for every real user.
//
// This repo's own Cloudflare Pages project config -- build command,
// output directory, and every VITE_* env var -- lives entirely outside
// this repo (Cloudflare's dashboard; see INFRASTRUCTURE_INVENTORY.md),
// so nothing here can inspect or fix that dashboard directly. What this
// CAN do is make it impossible for a missing env var there to produce a
// silently-broken deploy: src/lib/api.ts previously fell back to
// `http://localhost:8000` whenever VITE_API_URL was unset or blank --
// correct behavior for local dev, but if that same fallback ever fired
// in a real Cloudflare build (VITE_API_URL never configured, or
// configured blank), every visitor's browser would try to reach
// localhost and get nothing, surfacing as a generic, undiagnosable
// "Load failed" with zero indication of why. That runtime fallback is
// now production-mode-only-strict (see api.ts) as defense in depth; this
// script is the first, loudest line of defense -- failing the build
// itself, before anything ships.
//
// Uses Vite's own loadEnv so this checks exactly what the following
// `vite build` will actually see (same .env/.env.local/envDir rules),
// rather than re-implementing env-file parsing.
import { loadEnv } from "vite";

import { checkSupabaseKey } from "./supabase-env-checks.mjs";

const REQUIRED = ["VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY", "VITE_API_URL"];

const mode = process.env["NODE_ENV"] === "development" ? "development" : "production";
const env = { ...loadEnv(mode, process.cwd(), ""), ...process.env };

const missing = REQUIRED.filter((key) => !env[key] || env[key].trim() === "");

if (missing.length > 0) {
  console.error(
    `\n[check-web-env] Missing required env var(s): ${missing.join(", ")}\n\n` +
      "These are baked into the bundle at build time via Vite's import.meta.env\n" +
      "and must be set wherever this build actually runs (locally: .env; in\n" +
      "production: the Cloudflare Pages project's Settings -> Environment\n" +
      "variables -- this repo has no wrangler.toml/wrangler.json, so nothing\n" +
      "here controls that except this check).\n\n" +
      (missing.includes("VITE_API_URL")
        ? "VITE_API_URL specifically: src/lib/api.ts's fallback to\n" +
          "http://localhost:8000 is for local development only (VINCO_TARGET !=\n" +
          "production). Shipping a real deploy without this set would silently\n" +
          "point every browser at localhost -- refusing to build instead of doing\n" +
          "that.\n\n"
        : "") +
      "Fix: set these in the Cloudflare Pages dashboard for this project (or in\n" +
      ".env for a local production-mode build), then rebuild.\n",
  );
  process.exit(1);
}

const warnings = checkSupabaseKey(env["VITE_SUPABASE_URL"], env["VITE_SUPABASE_PUBLISHABLE_KEY"]).map(
  (w) => `VITE_SUPABASE_PUBLISHABLE_KEY ${w}`,
);

if (warnings.length > 0) {
  console.warn(
    `\n[check-web-env] VITE_SUPABASE_PUBLISHABLE_KEY looks suspicious (not blocking the ` +
      `build, since this can't be fully verified without a live request to Supabase):\n\n` +
      warnings.map((w) => `  - ${w}`).join("\n") +
      "\n\nDouble-check Project Settings -> API in the Supabase Dashboard for the project " +
      `at ${env["VITE_SUPABASE_URL"]} and compare against your Cloudflare Pages env vars.\n`,
  );
} else {
  console.log("[check-web-env] Required env vars present and structurally valid.");
}

// Only refuse a localhost VITE_API_URL when actually running inside a
// real Cloudflare Pages build (it sets these itself -- not something a
// local `.env` can spoof) -- a developer's own machine legitimately
// points at localhost:8000 for local dev, matching .env.example, and
// `bun run build` (a plain production-mode Vite build) is also how you'd
// sanity-check that build locally. Only a real Cloudflare deploy shipping
// localhost to real visitors' browsers is the actual production bug.
const isRealCloudflareBuild = Boolean(process.env["CF_PAGES_URL"] || process.env["CF_PAGES_BRANCH"]);

if (
  isRealCloudflareBuild &&
  (env["VITE_API_URL"].includes("localhost") || env["VITE_API_URL"].includes("127.0.0.1"))
) {
  console.error(
    `\n[check-web-env] VITE_API_URL is set to "${env["VITE_API_URL"]}", which points at ` +
      "localhost/127.0.0.1, inside what looks like a real Cloudflare Pages build (CF_PAGES_* " +
      "env vars present). That is never correct for a production web deploy -- every " +
      "visitor's own browser would try to reach their own machine, not the real backend. " +
      "Set it to the deployed backend's real URL " +
      "(https://vision-contracting-profit.onrender.com today) in the Cloudflare Pages " +
      "dashboard's Settings -> Environment variables.\n",
  );
  process.exit(1);
}
