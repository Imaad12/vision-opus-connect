# VINCO Desktop (Tauri 2) — Architecture

Status: local proof-of-concept scaffolded and build-verified in this repo
(`src-tauri/`). Not deployed, not signed, not distributed. Production
Cloudflare/Render/Supabase/Google OAuth configuration is untouched.

```
                  VINCO API
               FastAPI/Postgres
                     |
          +----------+----------+
          |          |          |
         Web       Windows     macOS
      Cloudflare    Tauri       Tauri
                   .exe         .dmg
```

## 1. Current frontend build architecture

This is a TanStack Start app, built via `@lovable.dev/vite-tanstack-config`
(`vite.config.ts`), a wrapper around TanStack Start's own Vite plugin plus
Nitro. The **web** production build (`bun run build`) runs Nitro with its
default `cloudflare-module` preset, producing `.output/server/*.mjs` (a
Cloudflare Worker `fetch` handler, wrapping `src/server.ts`) and
`.output/public/` (static assets the Worker serves). This is what's
deployed to Cloudflare today; nothing about it changes in this phase.

Critically: **every route already declares `ssr: false`** —
`index.tsx`, `auth.tsx`, and the whole `_authenticated` route subtree (set
in an earlier performance round). Nothing in this app currently renders
server-side; the Nitro/Worker layer exists to serve the app's static
assets and API-proxy-free HTML shell at the edge, not to render pages.

## 2. Exact Tauri compatibility issue found

Tauri has no server runtime — it loads a `frontendDist` directory directly
into its webview via a custom protocol. It cannot run `.output/server`'s
Cloudflare Worker code. Two things had to be true for a desktop build to
work, and both were verified against this exact source tree (see
"Verification" below), not assumed:

- **Nitro must be skipped for desktop.** `@lovable.dev/vite-tanstack-config`
  exposes `nitro: false` for exactly this ("self-hosted projects choose
  their own target"). With every route already `ssr: false`, disabling
  Nitro changes nothing about what's rendered.
- **A real `index.html` must exist.** This was the actual surprise:
  disabling Nitro alone was *not* sufficient — TanStack Start's own Vite
  plugin still runs in full-stack mode by default and emits **no**
  `index.html` at all in the client output (confirmed: `dist/client/`
  had JS/CSS chunks and nothing else). TanStack Start has a first-class
  answer for this — `tanstackStart({ spa: { enabled: true } })`, its
  "SPA shell" mode — which prerenders one standalone HTML file
  (`dist/client/_shell.html`) meant to be served for every client-side
  route. A small script copies it to `index.html` after each desktop
  build (`scripts/copy-desktop-shell.mjs`).

## 3. Recommended Tauri 2 structure (as scaffolded)

```
vision-opus-connect/
├── src/                      # UNCHANGED — same routes, components, API
│                              # client, React Query logic, auth logic
│   ├── lib/
│   │   ├── tauri-auth.ts     # NEW — desktop-only Google OAuth flow
│   │   └── tauri-storage.ts  # NEW — desktop-only session storage adapter
│   ├── integrations/supabase/client.ts  # 1-line conditional (see §4)
│   ├── routes/__root.tsx     # +4 lines: registers the deep-link listener
│   └── components/sign-in-card.tsx  # +1 branch: desktop vs. web OAuth call
├── scripts/
│   └── copy-desktop-shell.mjs
├── src-tauri/                # NEW — the only genuinely new codebase,
│   ├── Cargo.toml            # and it's Rust config/shell, not app logic
│   ├── tauri.conf.json
│   ├── capabilities/default.json
│   ├── icons/                # placeholder Tauri icons — see §11
│   └── src/lib.rs
├── vite.config.ts            # +9 lines: VINCO_TARGET=desktop branch
└── package.json               # +4 scripts, +5 deps (see §10)
```

No `desktop/` frontend package, no second `src/`, no forked router or
component tree. `src-tauri/` is Rust glue around the *same* built web
assets — Tauri's own recommended layout for exactly this scenario.

## 4. Exact files that changed (this proof-of-concept)

| File | Change |
|---|---|
| `vite.config.ts` | Added a `VINCO_TARGET=desktop` branch: `nitro: false` + `tanstackStart({ spa: { enabled: true } })`. Web build path (no env var) is byte-for-byte unaffected. |
| `package.json` | Added `build:desktop`, `tauri`, `tauri:dev`, `tauri:build` scripts; added `@tauri-apps/{api,cli,plugin-deep-link,plugin-opener,plugin-store}` and `cross-env` as deps. |
| `scripts/copy-desktop-shell.mjs` | New. Copies the SPA shell to `index.html` after a desktop build. |
| `src/integrations/supabase/client.ts` | **1 line changed**: `storage` picks `tauriSecureStorage` when `isTauri()`, else the existing `localStorage` (web unchanged). Everything else in this generated file is untouched. |
| `src/lib/tauri-storage.ts` | New. Supabase-compatible storage adapter backed by `@tauri-apps/plugin-store`. |
| `src/lib/tauri-auth.ts` | New. Desktop Google OAuth flow (system browser + deep link) — see §6. |
| `src/routes/__root.tsx` | +4 lines: registers the deep-link callback listener once, only under Tauri. |
| `src/components/sign-in-card.tsx` | +1 branch in `signIn()`: calls the desktop OAuth flow under Tauri, otherwise the exact same call as before. |
| `src-tauri/**` | New Tauri project (Cargo.toml, tauri.conf.json, capabilities, icons, `src/lib.rs`). |

No route, component, API client, React Query hook, or business-logic file
was duplicated or forked.

## 5. How web and desktop builds coexist

One source tree, one `package.json`, two build outputs, selected by an
env var read once in `vite.config.ts`:

- `bun run build` → unchanged → `.output/` (Cloudflare Worker + assets).
- `bun run build:desktop` → `dist/client/index.html` + hashed JS/CSS,
  no server bundle. `src-tauri/tauri.conf.json`'s `beforeBuildCommand`
  runs exactly this before every `tauri build`.
- `bun run dev` (port 8080) serves both: the web dev flow uses it
  directly; `tauri dev` points its `devUrl` at the same running server
  (`beforeDevCommand` sets `VINCO_TARGET=desktop` first, though in dev
  mode Nitro/SPA-mode don't engage at all — Vite's dev server already
  serves a plain SPA-shaped app).

A developer runs `bun run build` for web, `bun run tauri:build` for
desktop, from the same checkout, same `git commit`. That is this phase's
literal success criterion.

## 6. Authentication approach

**Problem:** Google's OAuth policy blocks sign-in from embedded webviews
("disallowed_useragent") — Tauri's window is one, so the web build's
in-window redirect (`signInWithOAuth` → `window.location = <google-url>`)
cannot be reused inside Tauri as-is.

**Recommended (and implemented) flow**, all in `src/lib/tauri-auth.ts`:

1. `supabase.auth.signInWithOAuth({ provider: "google", options:
   { redirectTo: "vinco://auth-callback", skipBrowserRedirect: true } })`
   — asks Supabase for the Google authorize URL without navigating
   anywhere.
2. Open that URL in the **system browser** via `@tauri-apps/plugin-opener`
   — a real, trusted browser context Google's policy allows.
3. Google → Supabase completes the OAuth exchange and redirects to
   `vinco://auth-callback#access_token=...&refresh_token=...`.
4. The OS hands that URL to the already-running app via
   `@tauri-apps/plugin-deep-link`'s `onOpenUrl` listener (registered once
   in `__root.tsx`), which parses the fragment and calls
   `supabase.auth.setSession({ access_token, refresh_token })` — the same
   call the web client's own internals make after its redirect.

**Session persistence / refresh tokens:** the Supabase JS client's
`autoRefreshToken: true` already handles token refresh identically on
both builds — that logic is entirely inside `@supabase/supabase-js` and
was not touched. What differs is *where* the session is written to disk
(§8).

**Logout:** `supabase.auth.signOut()` is unchanged and works on both
builds — it clears whatever `storage` adapter is configured, whichever
one that is.

**Deep-link/callback handling:** `tauri-plugin-deep-link` registers the
`vinco://` scheme (declared in `tauri.conf.json`, self-registered at
runtime on Windows/Linux, via `Info.plist` on macOS). No web server, no
localhost callback port, no new backend endpoint.

**Not privileged:** this flow only ever handles the same short-lived user
access/refresh token pair the web build's `onAuthStateChange` already
receives after every sign-in. It never touches Supabase's service-role
key or any other privileged credential — those exist only in the FastAPI
backend's server-side environment, never in any frontend build.

**What is explicitly NOT done in this phase:** registering
`vinco://auth-callback` as an authorized redirect URI in Google Cloud
Console, or as an allowed redirect URL in Supabase Auth's dashboard.
Without that one-time dashboard change on both sides, the flow reaches
Google fine but the final redirect back to the app will fail — exactly
as the web build's own redirect would if its URL weren't registered. This
is a config change on Google's and Supabase's dashboards, not code, and
is deliberately left for whenever real desktop distribution is approved.

## 7. API configuration approach

Unchanged from the web build's own pattern: `src/lib/api.ts` reads
`VITE_API_URL` at build time (already env-configurable, already defaults
to `http://localhost:8000`, already documented in `.env.example`). The
desktop build reads the identical variable — no separate desktop API
client, no direct database or Supabase-table access from the desktop
process, no business logic added to `src-tauri/`. Every request the
desktop app makes goes to the same FastAPI backend the web app calls,
authenticated with the same bearer token pattern.

**Still required before real desktop sign-in works end-to-end** (not done
now, listed here since it was asked to be documented, not implemented):
add the desktop app's origin to the backend's `CORS_ALLOWED_ORIGINS` env
var on Render (already a comma-separated list, see
`app/core/config.py` — a config change, not a code change) once the
final desktop distribution shape is decided. Tauri's origin is
`tauri://localhost` (macOS/Linux) / `http://tauri.localhost` (Windows).

## 8. Desktop storage: recommendation

**Recommendation: yes, introduce Tauri-backed storage for desktop,
implemented as `src/lib/tauri-storage.ts`.** Reasoning, not just
default-to-the-fancier-option:

- The web build's `localStorage` is fine there — the browser profile
  already is the OS-level privacy/security boundary for that origin.
- Tauri's webview also has a `localStorage`, but it's an internal detail
  of the embedded runtime (WebView2/WKWebView), not a place a user or IT
  admin would expect an app's session token to live, and it isn't
  necessarily covered by the same "clear browsing data" tooling someone
  might use to intentionally wipe a leaked credential.
- `@tauri-apps/plugin-store` persists to a JSON file in the OS per-app
  data directory (e.g. `%APPDATA%\com.visioncontracting.vinco\` on
  Windows), protected by ordinary OS user-account file permissions —
  a real improvement over an in-webview store, with no new dependency
  surface (no OS keychain integration, no extra crate to vet).

**What this is not:** OS-keychain-grade encryption at rest. That would be
`tauri-plugin-stronghold` or a keyring plugin (Windows Credential
Manager / macOS Keychain), a reasonable next hardening step once the app
is actually shipping to real users — not pulled in here per "do not
implement blindly": this starts with the simpler, well-supported option
and names the stronger one rather than guessing how much security
investment day one deserves.

## 9. Windows packaging

- **Dev build:** `bun run tauri:dev` — launches the Tauri window against
  the Vite dev server (WebView2, already present on modern Windows).
- **Production build:** `bun run tauri:build` on a Windows machine/runner
  produces an `.exe` and an NSIS or WiX `.msi` installer (Tauri's
  `bundle.targets: "all"`, already set).
- **Application icon:** wired (`src-tauri/icons/icon.ico` + the
  `Square*Logo.png` set for the Start Menu tile) — currently the generic
  placeholder Tauri generated, not VINCO-branded (§11).
- **Signing:** needs a Windows code-signing certificate (Authenticode) —
  not obtained or configured in this phase, per instruction. Tauri's
  bundler accepts a cert via config once one exists.
- **Future auto-updates:** Tauri's official `tauri-plugin-updater` is the
  standard path — needs a signed update manifest hosted somewhere (a
  static JSON file works; Cloudflare, already in use for the web app, is
  a natural fit). Not scaffolded in this phase — it needs the signing
  cert first.

## 10. macOS packaging

- **Dev build:** `bun run tauri:dev` — launches against WKWebView
  (built into macOS, no extra runtime to install).
- **Production build:** `bun run tauri:build` on a macOS machine/runner
  produces a proper `.app` bundle and `.dmg`.
- **Application icon:** wired (`src-tauri/icons/icon.icns`) — same
  placeholder-icon caveat as Windows (§11).
- **Signing / notarization:** needs an Apple Developer Program membership
  and a Developer ID Application certificate — not obtained in this
  phase, per instruction. Tauri's bundler handles `codesign` +
  `notarytool` submission once those credentials are configured.
- **Future auto-updates:** same `tauri-plugin-updater` as Windows, one
  updater manifest serving both platforms.

Neither installer can actually be produced from this Linux sandbox —
Tauri bundles for the OS it runs on, so `.exe`/`.msi` need a Windows
build machine or CI runner, and `.dmg`/notarization need a macOS one
(this is standard for every cross-platform desktop toolchain, not a
Tauri limitation). What *was* verified here is the part that doesn't
need those OSes: the Rust project compiles and the desktop web build is
structurally correct (§ Verification below). The two-line answer for
real releases is a CI matrix (`windows-latest`, `macos-latest`) each
running `bun run tauri:build`.

## 11. Dependencies added

JS (`package.json`): `@tauri-apps/cli` (dev), `@tauri-apps/api`,
`@tauri-apps/plugin-deep-link`, `@tauri-apps/plugin-opener`,
`@tauri-apps/plugin-store`, `cross-env` (dev).

Rust (`src-tauri/Cargo.toml`): `tauri`, `tauri-plugin-log` (already
scaffolded by `tauri init`), plus `tauri-plugin-deep-link`,
`tauri-plugin-opener`, `tauri-plugin-store` (added for the auth flow).

System (this sandbox only, to compile/verify locally):
`libwebkit2gtk-4.1-dev`, `libjavascriptcoregtk-4.1-dev`,
`libsoup-3.0-dev`, `libayatana-appindicator3-dev`, `librsvg2-dev` — the
standard Tauri Linux dev dependencies (`webkit2gtk` provides Tauri's
Linux webview). A real Linux desktop build/distribution would need the
same on any dev machine or CI runner; Windows/macOS use their native
WebView2/WKWebView instead and need no equivalent install.

**Icons:** the icon set in `src-tauri/icons/` is `tauri init`'s generic
placeholder logo, not VINCO-branded — no VINCO logo asset was available
to generate real icons from. Once one exists, `tauri icon
<path-to-1024x1024-png>` regenerates every platform size from a single
source image; nothing else needs to change.

## 12. Risks

- **Google OAuth dashboard config is a hard external dependency.** The
  deep-link flow is complete on the app side, but sign-in cannot fully
  succeed until `vinco://auth-callback` is registered in Google Cloud
  Console and Supabase Auth's redirect allow-list — a decision explicitly
  left for whenever real distribution is approved (§6).
- **CORS.** The desktop origin (`tauri://localhost` /
  `http://tauri.localhost`) needs adding to the backend's
  `CORS_ALLOWED_ORIGINS` before API calls succeed end-to-end from a real
  desktop build (§7) — a Render env var change, not code.
- **`localStorage`→Tauri-store swap is a one-line, hand-maintained
  exception in an auto-generated file** (`src/integrations/supabase/
  client.ts`, marked "do not edit directly"). Clearly commented so a
  future regeneration of that file knows to re-apply it; still worth
  flagging as the one place this phase touches Lovable-managed codegen.
- **Signing/notarization credentials are real, non-trivial procurement
  items** (a Windows code-signing cert; Apple Developer Program
  membership, $99/yr) — nobody has purchased or configured either yet;
  neither is needed for local dev/testing, both are required before any
  installer can be distributed to a real user without OS security
  warnings.
- **Session-storage hardening.** `@tauri-apps/plugin-store` is a real
  improvement over in-webview `localStorage` but not OS-keychain-grade
  encryption (§8) — acceptable for a local proof-of-concept, worth
  revisiting before shipping to end users who might have other local
  applications or users with file access on the same machine.
- **Placeholder icons/branding.** Fine for local dev; must be replaced
  before any real installer is distributed (§11).
- **Mobile is not blocked.** Tauri 2 (unlike Tauri 1) supports iOS/Android
  from the same `src-tauri/` project — nothing in this scaffold (the
  `spa` build mode, the deep-link auth flow, the storage adapter pattern)
  is desktop-specific in a way that would need reworking for a future
  mobile target; it is simply not being built now, per instruction.

## Verification performed (this sandbox)

- `bun run build` (web/Cloudflare) — unchanged, still succeeds.
- `bun run build:desktop` — succeeds; produces `dist/client/index.html` +
  hashed assets, no server bundle.
- The desktop build's static output was served locally and loaded in
  headless Chromium: the sign-in screen renders fully (title, hero copy,
  language toggle, "Open workspace" button) with **zero page errors**.
  The one console error (`net::ERR_CONNECTION_RESET` on Supabase's
  `getUser()` call) is this sandbox's network policy blocking
  `supabase.co`, not an application defect — the same call the web build
  already makes.
- `npx tsc --noEmit` — clean, including the new Tauri/auth/storage code.
- `cd src-tauri && cargo check` — clean; the Rust project (with the
  opener/deep-link/store plugins wired in) compiles against this
  sandbox's installed webkit2gtk.
- `npx tauri build --no-bundle` (a real, release-mode Rust compile of
  the whole Tauri shell, skipping only the OS-specific installer
  packaging step) — **succeeded**: `Finished release profile [optimized]
  target(s) in 3m 10s`, producing a real Linux binary at
  `src-tauri/target/release/app`.
- Launching that binary under `xvfb-run` (a virtual display, since this
  sandbox has no real screen) initially **panicked** during startup:
  registering the `vinco://` deep-link scheme failed with "No such file
  or directory" — this sandbox has no proper XDG desktop-integration
  environment (no display manager, no `~/.local/share/applications`
  setup) for the plugin to write into. This was a real robustness gap,
  not just a sandbox quirk: an OS-level registration failure shouldn't
  be able to crash the whole app on a real, more locked-down machine
  either, so `src-tauri/src/lib.rs` now logs a warning instead of
  propagating that error. Rebuilt, relaunched: the app **ran stably for
  the full test window with no crash**, loading the real built frontend
  through Tauri's `frontendDist` — the only output was a harmless
  "DRI3/EGL" GPU-acceleration warning from this sandbox having no GPU,
  not an application error.

Nothing in this phase touched production Cloudflare, Render, Supabase,
Google Cloud, or PostgreSQL configuration.
