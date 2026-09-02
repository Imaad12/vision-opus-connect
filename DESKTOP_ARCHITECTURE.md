# VINCO Desktop (Tauri 2) — Architecture

**Current state:** desktop shows the same native VINCO username/password
login as web by default (`src/components/sign-in-card.tsx`, no
`isTauri()` branching) — see the root `README.md`'s "Native login and
user management" section. Google OAuth for desktop, and everything it
required (`src/lib/tauri-auth.ts`, `tauri-plugin-deep-link`, the
`vinco://` URL scheme in `tauri.conf.json`/`lib.rs`, PKCE) has been
**removed entirely**, not merely parked — see `DESKTOP_AUTH_MVP.md`'s own
superseded banner for that history. Session storage is the plain-JSON
`session_store.rs` file described in §8's "Superseded" callout below, not
the original OS-keychain design §8 otherwise describes historically. CI
builds unsigned Windows/macOS installer artifacts on every push (see
`.github/workflows/desktop-build.yml`); this is otherwise still an
internal-testing build, not yet code-signed/notarized for public
distribution.

The rest of this document is a running history of how desktop auth and
storage evolved — later "Superseded"/"Current state" notes correct
earlier sections rather than the whole file being rewritten each time.
Where a section conflicts with the banner above, the banner is current.

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
│   ├── icons/                # placeholder Tauri icons — see §12
│   └── src/
│       ├── lib.rs
│       └── keychain.rs       # NEW — OS-keychain Tauri commands, see §8
├── .github/workflows/
│   └── desktop-build.yml     # NEW — Windows/macOS CI artifacts, see §13
├── vite.config.ts            # +9 lines: VINCO_TARGET=desktop branch
└── package.json               # scripts/deps, see §11
```

No `desktop/` frontend package, no second `src/`, no forked router or
component tree. `src-tauri/` is Rust glue around the *same* built web
assets — Tauri's own recommended layout for exactly this scenario.

## 4. Exact files that changed (this proof-of-concept)

| File | Change |
|---|---|
| `vite.config.ts` | Added a `VINCO_TARGET=desktop` branch: `nitro: false` + `tanstackStart({ spa: { enabled: true } })`. Web build path (no env var) is byte-for-byte unaffected. |
| `package.json` | Added `build:desktop`, `tauri`, `tauri:dev`, `tauri:build` scripts; added `@tauri-apps/{api,cli,plugin-deep-link,plugin-opener}` and `cross-env` as deps. |
| `scripts/copy-desktop-shell.mjs` | New. Copies the SPA shell to `index.html` after a desktop build. |
| `src/integrations/supabase/client.ts` | **1 line changed**: `storage` picks `tauriSecureStorage` when `isTauri()`, else the existing `localStorage` (web unchanged). Everything else in this generated file is untouched. |
| `src/lib/tauri-storage.ts` | New. Supabase-compatible storage adapter — calls the OS-keychain Tauri commands in `src-tauri/src/keychain.rs` (§8). |
| `src/lib/tauri-auth.ts` | New. Desktop Google OAuth flow (system browser + deep link) — see §6. |
| `src/routes/__root.tsx` | +4 lines: registers the deep-link callback listener once, only under Tauri. |
| `src/components/sign-in-card.tsx` | +1 branch in `signIn()`: calls the desktop OAuth flow under Tauri, otherwise the exact same call as before. |
| `src-tauri/**` | New Tauri project (Cargo.toml, tauri.conf.json, capabilities, icons, `src/lib.rs`, `src/keychain.rs`). |
| `.github/workflows/desktop-build.yml` | New. CI artifact builds for Windows/macOS — see §13. |

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

**Superseded — see `DESKTOP_OAUTH_FIX.md`.** The flow originally
described here (implicit flow, tokens in the callback URL fragment,
`onOpenUrl` only) shipped in the first .dmg and had a real bug: the
callback never reached the app at all, landing the browser on the web
dashboard instead. `DESKTOP_OAUTH_FIX.md` has the full diagnosis, the
corrected PKCE-based flow, cold-start (`getCurrent()`) and
already-running (`tauri-plugin-single-instance`) callback handling, and
the exact Supabase dashboard change still required. §7 onward below are
still current.

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

## 8. Desktop storage — hardened to the OS credential store (superseded, see below)

> **Superseded.** The OS-keychain approach this section describes was
> replaced: on an unsigned/ad-hoc-signed build, macOS ties a Keychain
> item's "always allow" grant to the requesting app's code-signing
> identity, and an ad-hoc signature's identity changes with every
> rebuild — so the OS authorization prompt reappeared on every single
> new build, with no code-level fix short of a stable code-signing
> certificate (a one-time manual macOS-side setup step, not yet done).
> `src-tauri/src/keychain.rs` was replaced by
> `src-tauri/src/session_store.rs` — the same three-command shape
> (`session_store_get`/`_set`/`_delete`), now backed by a plain JSON
> file under the OS per-app data directory instead of `keyring`/OS
> Keychain. This is the same protection level the web build's
> `localStorage` already has (OS-user-level file permissions), just
> without the OS-managed encryption-at-rest and access prompt a real
> keychain additionally provides. `src/lib/tauri-storage.ts`'s export
> is now `tauriDesktopStorage`. The rest of this section is kept as a
> historical record of why OS-keychain storage was chosen originally;
> it no longer describes the current implementation.

**Status: implemented, not just recommended (historical).** The original scaffold used
`@tauri-apps/plugin-store` (a JSON file under the OS per-app data
directory) as a deliberately named first step, with real OS-keychain
protection explicitly called out as the follow-up rather than guessed at.
That follow-up is now in place.

**What changed:** `src-tauri/src/keychain.rs` is a small Rust module (no
plugin, ~50 lines) exposing three Tauri commands —
`keychain_get`/`keychain_set`/`keychain_delete` — built on the
[`keyring`](https://crates.io/crates/keyring) crate, which wraps each
platform's real OS credential facility:

| Platform | Backend | Cargo feature |
|---|---|---|
| Windows | Windows Credential Manager | `windows-native` |
| macOS | Keychain | `apple-native` |
| Linux | Secret Service (D-Bus, GNOME Keyring/KWallet) | `sync-secret-service` |

Each is selected per-target in `Cargo.toml` (`[target.'cfg(target_os =
"...")'.dependencies]`), so a given platform's binary only links the
backend it actually uses. `src/lib/tauri-storage.ts` now calls these
commands via `@tauri-apps/api/core`'s `invoke()` instead of the file-based
plugin, which has been removed entirely (`tauri-plugin-store` and
`@tauri-apps/plugin-store` are no longer dependencies — nothing else used
them).

**Why this, not `tauri-plugin-stronghold`:** Stronghold is Tauri's other
official "secure storage" option, but it's an encrypted *vault file*
(its own Argon2-derived key + AES), not the OS's own credential store —
the instruction asked specifically for "the operating system's secure
credential facilities," which points at Credential Manager/Keychain/
Secret Service themselves. `keyring` talks to those directly.

**Why a small custom command layer instead of a pre-built plugin:**
`tauri-plugin-store`/`-deep-link`/`-opener` are official, actively
maintained Tauri-org plugins; there is no equivalent official OS-keychain
plugin. Wrapping `keyring` directly in ~50 lines of Rust is small enough
to review in full, keeps the dependency surface to one well-known crate
(15M+ downloads, used by 1Password's CLI and others) instead of a
smaller third-party Tauri wrapper, and stays fully within "produce-safe,
public-client" scope — the commands only ever move the same opaque
access/refresh token strings the web build already puts in
`localStorage`.

**Tested, not just assumed to compile:** `keyring` always compiles in a
platform-independent mock credential store specifically for this purpose
(its own documented feature). `src-tauri/src/keychain.rs` has 3 `cargo
test` regression tests using it — see §"Verification" below, including
one real bug the mock caught and one real limitation of the mock itself,
found and documented while writing them, not assumed away.

## 9. Windows packaging

- **Dev build:** `bun run tauri:dev` — launches the Tauri window against
  the Vite dev server (WebView2, already present on modern Windows).
- **Production build:** `bun run tauri:build` on a Windows machine/runner
  produces an `.exe` and an NSIS or WiX `.msi` installer (Tauri's
  `bundle.targets: "all"`, already set).
- **Application icon:** wired (`src-tauri/icons/icon.ico` + the
  `Square*Logo.png` set for the Start Menu tile) — currently the generic
  placeholder Tauri generated, not VINCO-branded (§12).
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
  placeholder-icon caveat as Windows (§12).
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
`@tauri-apps/plugin-deep-link`, `@tauri-apps/plugin-opener`, `cross-env`
(dev), `vitest` (dev, `DESKTOP_OAUTH_FIX.md`). (`@tauri-apps/plugin-store`
was added, then removed once §8's keychain hardening replaced it.) Rust:
`tauri-plugin-single-instance` added alongside the OAuth fix — see that
doc for why.

Rust (`src-tauri/Cargo.toml`): `tauri`, `tauri-plugin-log` (already
scaffolded by `tauri init`), `tauri-plugin-deep-link`,
`tauri-plugin-opener` (auth flow, §6), and `keyring` (OS credential
store, §8 — added per-target, not a blanket dependency).

System (this sandbox only, to compile/verify locally):
`libwebkit2gtk-4.1-dev`, `libjavascriptcoregtk-4.1-dev`,
`libsoup-3.0-dev`, `libayatana-appindicator3-dev`, `librsvg2-dev` — the
standard Tauri Linux dev dependencies (`webkit2gtk` provides Tauri's
Linux webview, and `sync-secret-service` needs D-Bus dev headers for the
keychain backend). The CI workflow (§13) installs the same set; a real
Linux dev machine would need it too. Windows/macOS use their native
WebView2/WKWebView and Credential Manager/Keychain instead and need no
equivalent install.

## 12. App identity — reviewed, kept

| Field | Value | |
|---|---|---|
| `productName` | `VINCO ERP` | Matches the app's own established short name (`t("app.short")` in `src/lib/i18n`, already used in every page's browser-tab title) — not invented for this phase. |
| `identifier` | `com.visioncontracting.vinco` | Reverse-DNS of the real company name ("Vision Contracting Co." — `t("app.name")`), independent of any purchased domain. This is a bundle/app namespace, not a URL — it does not need `visioncontracting.com` to exist or be owned, and nothing about the later domain-migration phase (`app.<domain>`/`api.<domain>`) touches it. Permanent; not something that phase will need to unwind. |
| `version` | `0.1.0` | Pre-release desktop scaffold; `package.json` has no version field to reconcile against (private app, not published to a registry). |

Not ambiguous enough to need a decision from you — kept as set in the
previous phase, not changed here.

**Icons (§13 covers where to drop real assets):** the icon set in
`src-tauri/icons/` is `tauri init`'s generic placeholder logo, not
VINCO-branded — no VINCO logo asset was available to generate real icons
from, and no time was spent designing one now, per instruction. Once a
source logo exists (ideally a 1024×1024 PNG), regenerating every
platform size is one command: `bunx tauri icon path/to/vinco-logo.png`
— it overwrites everything under `src-tauri/icons/` (32×32/128×128 PNGs,
`icon.ico`, `icon.icns`, the Windows Store tile `Square*.png` set) from
that one source. Nothing else in `tauri.conf.json` needs to change — the
`bundle.icon` array already points at those exact filenames.

## 13. GitHub Actions: cross-platform CI artifacts

`.github/workflows/desktop-build.yml`, triggered manually
(`workflow_dispatch`) or on a push/PR touching frontend or `src-tauri/`
code. Three jobs:

1. **`frontend-checks`** (ubuntu-latest, no Rust): `tsc --noEmit`, the web
   build (`bun run build`), and the desktop build (`bun run build:desktop`)
   — proves both build targets still work from the same source tree on
   every change, per instruction #4. Fails in ~1 minute if either breaks,
   before the expensive platform jobs even start.
2. **`rust-checks`** (ubuntu-latest): `cargo check` + `cargo test` for
   `src-tauri`, including `keychain.rs`'s mock-backed regression tests
   (§8). Cheapest possible signal that the Rust side is sound.
3. **`build-desktop`** (matrix, depends on both jobs above passing):
   the actual installer builds —

   | Runner | Target | Produces |
   |---|---|---|
   | `windows-latest` | native x64 | `.exe` (NSIS) + `.msi` (WiX) — both come free from the existing `bundle.targets: "all"` |
   | `macos-latest` | `aarch64-apple-darwin` | `.app` + `.dmg` (Apple Silicon) |
   | `macos-latest` | `x86_64-apple-darwin` (cross-compiled) | `.app` + `.dmg` (Intel) |

   Intel is cross-compiled from the same Apple Silicon runner via
   `rustup target add x86_64-apple-darwin` + `tauri build --target
   x86_64-apple-darwin` — standard for Rust/Tauri, no second (pricier)
   Intel runner needed. Each job uploads its whole `bundle/` output
   directory as a build artifact (`actions/upload-artifact`, 14-day
   retention) rather than a hardcoded filename — Tauri names artifacts
   from `productName` + `version` (§12: `VINCO ERP` / `0.1.0`), and the
   exact string (spaces, arch suffix, NSIS vs. WiX naming) can only be
   confirmed by an actual run, which this sandbox cannot produce (no
   Windows/macOS runner here) — see §D of the report below.

**Explicitly not done by this workflow:** no GitHub Release is created,
no signing identity is configured (builds are unsigned — Windows/macOS
will show an "unknown publisher" warning), nothing is published anywhere.
It only uploads artifacts to the workflow run itself, downloadable from
the Actions tab.

**One setup step required before this workflow can run successfully:**
add `VITE_SUPABASE_PUBLISHABLE_KEY` as a repository secret (Settings →
Secrets and variables → Actions → **Secrets**) — the same real anon key
already in `.env`/the web build's public bundle, not a new credential.
Optionally add `VITE_API_URL` as a repository **variable** (same menu,
Variables tab) if you want CI builds to point somewhere other than
`localhost:8000`. Neither was added by this change — I don't have
repository-secrets access, and creating one is a GitHub settings change,
not a code change.

## 14. Risks

- **Supabase Auth dashboard config is a hard external dependency.** The
  deep-link flow is complete on the app side, but sign-in cannot fully
  succeed until `vinco://auth-callback` is added to Supabase Auth's
  redirect URL allow-list — this was in fact the exact root cause of the
  first .dmg's login-loop bug; see `DESKTOP_OAUTH_FIX.md`. Google Cloud
  Console needs no change (Google only ever redirects to Supabase's own
  fixed HTTPS callback, already registered).
- **CORS.** The desktop origin (`tauri://localhost` /
  `http://tauri.localhost`) needs adding to the backend's
  `CORS_ALLOWED_ORIGINS` before API calls succeed end-to-end from a real
  desktop build (§7) — a Render env var change, not code.
- **`localStorage`→Tauri-storage swap is a one-line, hand-maintained
  exception in an auto-generated file** (`src/integrations/supabase/
  client.ts`, marked "do not edit directly"). Clearly commented so a
  future regeneration of that file knows to re-apply it; still worth
  flagging as the one place this phase touches Lovable-managed codegen.
- **Signing/notarization credentials are real, non-trivial procurement
  items** (a Windows code-signing cert; Apple Developer Program
  membership, $99/yr) — nobody has purchased or configured either yet;
  neither is needed for local dev/testing or for the CI artifact builds
  in §13, both are required before any installer can be distributed to
  a real user without OS security warnings.
- **Linux Secret Service isn't always present.** §8's `keyring`
  integration is only exercised via its mock backend in this sandbox and
  in CI (§13) — no D-Bus Secret Service daemon is running in either. This
  doesn't affect Windows/macOS (Credential Manager/Keychain are always
  present on those OSes), and Linux desktop distribution isn't a current
  target; it would only matter for a developer building on a minimal
  Linux machine, and even then `keyring` falls back to its mock store
  rather than failing outright if no keystore feature applies.
- **CI needs one manual setup step first** — the `VITE_SUPABASE_
  PUBLISHABLE_KEY` repo secret (§13) — before `desktop-build.yml` can run
  to completion. This is expected to be the actual next blocker, not
  code.
- **Placeholder icons/branding.** Fine for local dev and CI artifacts;
  must be replaced before any real installer is distributed (§12).
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
- **This phase**, after replacing `@tauri-apps/plugin-store` with the
  OS-keychain commands (§8): `cargo test` for `src-tauri/src/keychain.rs`
  — initially **2 of 5 tests failed** (`set_then_get_roundtrips`,
  `set_overwrites_previous_value`), flaky on parallel reruns. Root-caused
  to two distinct, real issues rather than patched around:
  1. `set_default_credential_builder` installs a *fresh* mock store on
     every call, and Rust runs tests in parallel by default — racing
     tests could wipe each other's data. Fixed with a `std::sync::Once`
     guard so it installs exactly once per test binary.
  2. Deeper issue, in the mock backend itself: its own docs say "no
     persistence other than in the entry itself" — two separate
     `Entry::new(service, key)` calls for the same key are NOT backed by
     a shared store under the mock (unlike a real OS keychain, which
     *is* shared across separate `Entry` objects). `keychain_get`/`_set`/
     `_delete` each construct a fresh `Entry` per call — correct for a
     real backend, but not something the mock can round-trip-test. Tests
     were rewritten to check what the mock *can* verify honestly: the
     error-mapping logic (`NoEntry` → `None`/`Ok(())`) through the actual
     commands, and a full set/get/overwrite/delete cycle against
     `keyring::Entry` directly (the same API my commands call, reused
     across calls the way a real backend supports). Reran 5× — stable,
     3/3 passing every time.
  3. Rebuilt the release binary and relaunched it under `xvfb-run` again
     after this change: still runs stably, no crash, confirming the
     keychain swap didn't regress the app-launch verification above.
- `bunx eslint` on every new/changed frontend file (`tauri-auth.ts`,
  `tauri-storage.ts`, `__root.tsx`, `vite.config.ts`,
  `copy-desktop-shell.mjs`) — clean. (`sign-in-card.tsx` and
  `integrations/supabase/client.ts` carry pre-existing, unrelated
  prettier findings from before this phase — confirmed via `git stash`,
  not introduced by this change.)
- `.github/workflows/desktop-build.yml` — validated as parseable YAML
  (`python3 -c "import yaml; yaml.safe_load(...)"`); the actual Windows/
  macOS runner jobs cannot be executed from this sandbox (no such
  runners here) — see §D of the report for what that means concretely.

Nothing in this phase touched production Cloudflare, Render, Supabase,
Google Cloud, or PostgreSQL configuration.
