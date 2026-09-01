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

const REQUIRED = [
  "VITE_SUPABASE_URL",
  "VITE_SUPABASE_PUBLISHABLE_KEY",
  // Desktop MVP auto-login (see DESKTOP_AUTH_MVP.md): with no login
  // screen, a build missing these can never reach the dashboard at all --
  // failing the build now is strictly better than shipping a .dmg that
  // launches straight into an unrecoverable "sign-in failed" loop.
  "VITE_DESKTOP_DEV_EMAIL",
  "VITE_DESKTOP_DEV_PASSWORD",
];

const mode = process.env["NODE_ENV"] === "development" ? "development" : "production";
const env = { ...loadEnv(mode, process.cwd(), ""), ...process.env };

const missing = REQUIRED.filter((key) => !env[key]);

if (missing.length > 0) {
  console.error(
    `\n[check-desktop-env] Missing required env var(s): ${missing.join(", ")}\n\n` +
      "The desktop build bakes these into the app bundle at build time via\n" +
      "Vite's import.meta.env.\n\n" +
      "If VITE_SUPABASE_URL / VITE_SUPABASE_PUBLISHABLE_KEY are missing:\n" +
      "the build still succeeds and produces a working-looking .app/.dmg,\n" +
      "but the app crashes immediately on launch -- TanStack's root error\n" +
      'boundary shows "This page didn\'t load" -- because the Supabase\n' +
      "client throws the first time it's touched.\n\n" +
      "If VITE_DESKTOP_DEV_EMAIL / VITE_DESKTOP_DEV_PASSWORD are missing:\n" +
      "the desktop MVP has no login screen to fall back to (see\n" +
      "DESKTOP_AUTH_MVP.md) -- the app would launch straight into a\n" +
      '"sign-in failed" retry loop with no way to authenticate.\n\n' +
      "Fix: copy .env.example to .env in the project root and fill in\n" +
      "real values (see DESKTOP_AUTH_MVP.md for how to create the\n" +
      "desktop MVP's dedicated Supabase account), then re-run\n" +
      "`bun run tauri:build`.\n",
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
function projectRefFromUrl(url) {
  try {
    return new URL(url).hostname.split(".")[0];
  } catch {
    return undefined;
  }
}

function projectRefFromLegacyJwt(key) {
  // Legacy Supabase anon/service_role keys are JWTs: header.payload.sig,
  // base64url-encoded. Decoding the payload to read its `ref` claim needs
  // no signature verification/secret -- it's not a security check, just
  // reading a public field to compare against SUPABASE_URL's subdomain.
  const parts = key.split(".");
  if (parts.length !== 3) return undefined;
  try {
    const payload = JSON.parse(Buffer.from(parts[1], "base64url").toString("utf8"));
    return typeof payload.ref === "string" ? payload.ref : undefined;
  } catch {
    return undefined;
  }
}

const url = env["VITE_SUPABASE_URL"];
const key = env["VITE_SUPABASE_PUBLISHABLE_KEY"];
const urlRef = projectRefFromUrl(url);
const warnings = [];

const isNewFormatKey = key.startsWith("sb_publishable_") || key.startsWith("sb_secret_");
const isLegacyJwtKey = key.startsWith("eyJ");

if (key.startsWith("sb_secret_")) {
  warnings.push(
    "VITE_SUPABASE_PUBLISHABLE_KEY looks like a Supabase SECRET key (sb_secret_...), " +
      "not a publishable/anon key. A secret key must never ship in a client bundle " +
      "(desktop or web) -- use the publishable key from Project Settings -> API instead.",
  );
} else if (!isNewFormatKey && !isLegacyJwtKey) {
  warnings.push(
    `VITE_SUPABASE_PUBLISHABLE_KEY (length ${key.length}) matches neither known Supabase ` +
      "key format (legacy JWT starting \"eyJ\", or new sb_publishable_...). This is " +
      "consistent with a placeholder/stub value rather than a real key copied from the " +
      "Supabase Dashboard.",
  );
} else if (isLegacyJwtKey) {
  const keyRef = projectRefFromLegacyJwt(key);
  if (keyRef && urlRef && keyRef !== urlRef) {
    warnings.push(
      `VITE_SUPABASE_PUBLISHABLE_KEY is a valid-looking JWT for project "${keyRef}", but ` +
        `VITE_SUPABASE_URL points at project "${urlRef}". A key from a different Supabase ` +
        'project is exactly what produces "Invalid API key" once a real request reaches ' +
        "Supabase (e.g. during Google sign-in's exchangeCodeForSession call) -- the build " +
        "and the login screen both look fine regardless, since neither talks to Supabase " +
        "with this key until then.",
    );
  }
}

if (key.length < 40) {
  warnings.push(
    `VITE_SUPABASE_PUBLISHABLE_KEY is only ${key.length} characters -- shorter than any ` +
      "real Supabase publishable/anon key. Likely a placeholder or a copy-paste that got " +
      "truncated.",
  );
}

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
