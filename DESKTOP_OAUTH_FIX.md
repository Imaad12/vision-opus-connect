# VINCO Desktop — OAuth callback bug: diagnosis and fix

Status: root cause found, code fixed and tested locally, one Supabase
dashboard change still required before a real end-to-end test is
possible. Not yet verified against a real Google/Supabase network round
trip (this sandbox has no route to `supabase.co`) — see §10.

## 1. Exact root cause

**Supabase Auth's redirect URL allow-list did not (and could not) contain
`vinco://auth-callback`.**

Tracing the original flow: `signInWithOAuth({ redirectTo:
"vinco://auth-callback", skipBrowserRedirect: true })` asks Supabase's
GoTrue `/authorize` endpoint for a login URL. That endpoint redirects the
browser to **Google**, but with `redirect_uri` set to **Supabase's own**
fixed callback (`https://<project-ref>.supabase.co/auth/v1/callback`) —
never to `vinco://auth-callback` directly; a third-party OAuth provider
only ever knows about the identity provider's own callback URL, not the
app's. Google redirects back to that Supabase URL, and Supabase's
callback handler is what then decides where to send the browser *next*,
using the `redirect_to` value from the original request — but **only if
that URL is on the Auth "Redirect URLs" allow-list** (Authentication ->
URL Configuration, in the Supabase dashboard). If it isn't, Supabase does
not error — it silently falls back to the configured **Site URL** (the
web app's own dashboard). That fallback is exactly the reported symptom:
"Browser redirects to the WEB application's dashboard... remains on the
dashboard." The desktop app was never being contacted at all; it wasn't
a deep-link delivery problem, the deep link was never issued.

Google Cloud Console needs **no change** for this: Google's authorized
redirect URI is Supabase's fixed HTTPS callback, already correctly
registered (proven by the web flow already working with the same OAuth
client).

**A second, independent bug** was found while tracing "Scenario B" (the
app closed, then cold-started by the callback): the original
`initTauriDeepLinkAuth` only registered `@tauri-apps/plugin-deep-link`'s
`onOpenUrl` — a listener for URLs that arrive *after* it's registered.
The plugin's own documentation is explicit that this is not sufficient:
"Use `getCurrent` on app load to check whether your app was started via a
deep link." The original code never called `getCurrent()`, so even with
the Supabase allow-list fixed, a cold-started launch would silently drop
the callback.

**A third, platform-specific bug**: the deep-link plugin's own README
states plainly that on Windows and Linux, "the OS will spawn a new
instance of your app with the URL as a CLI argument" unless
`tauri-plugin-single-instance` (with its `deep-link` feature) is also
installed — without it, clicking the callback link while the app is
already running would open a second, unauthenticated window instead of
completing sign-in in the first one. Not installed originally.

## 2. Exact files changed

| File | Change |
|---|---|
| `src/integrations/supabase/client.ts` | Added `flowType: 'pkce'` (§5). |
| `src/lib/tauri-auth.ts` | Rewritten: PKCE `code`/`error` query-param parsing instead of implicit `#access_token` fragment parsing; added `getCurrent()` cold-start handling; error surfacing via `toast.error`. |
| `src/lib/tauri-auth.test.ts` | New. 8 unit tests for the callback-parsing/routing logic (§9). |
| `src/components/sign-in-card.tsx` | Added an effect that navigates to `/dashboard` as soon as `signedIn` becomes true, instead of requiring a second manual click. |
| `src-tauri/src/lib.rs` | Registered `tauri_plugin_single_instance` (first plugin, per its own requirement). |
| `src-tauri/Cargo.toml` | Added `tauri-plugin-single-instance` (`deep-link` feature). |
| `vitest.config.ts`, `package.json` (`test` script, `vitest` devDependency) | New — this repo had no JS unit-test runner before. |
| `.github/workflows/desktop-build.yml` | Added a `bun run test` step to `frontend-checks`. |

## 3. Exact OAuth flow before

```
sign-in-card.tsx
  -> tauri-auth.ts: signInWithOAuth({ redirectTo: "vinco://auth-callback",
                                       skipBrowserRedirect: true })
     (implicit flow -- no flowType set, auth-js defaults to 'implicit')
  -> system browser opens Supabase's authorize URL
  -> Google
  -> Supabase's fixed HTTPS callback
  -> Supabase checks "vinco://auth-callback" against its redirect
     allow-list -- NOT PRESENT -> falls back to the Site URL
  -> browser lands on the WEB app's /dashboard, with tokens in the
     fragment (#access_token=...) -- for the WEB client, not the desktop
     one
  -> desktop app's onOpenUrl listener never fires (no deep link was ever
     issued) -- app stays on the sign-in screen forever
```

## 4. Exact OAuth flow after

```
sign-in-card.tsx
  -> tauri-auth.ts: signInWithOAuth({ redirectTo: "vinco://auth-callback",
                                       skipBrowserRedirect: true })
     (PKCE flow -- client.ts now sets flowType: 'pkce'; a code_verifier is
     generated and stored via tauriSecureStorage, the OS keychain, before
     the URL is even returned)
  -> system browser opens Supabase's authorize URL
  -> Google
  -> Supabase's fixed HTTPS callback
  -> Supabase checks "vinco://auth-callback" against its redirect
     allow-list -- MUST be present now (§11 -- not yet done, dashboard
     access required)
  -> vinco://auth-callback?code=<single-use-code>&sb_flow_id=<id>
  -> OS delivers this to the app two ways, both now handled:
     - already running: onOpenUrl fires directly (macOS/iOS), or
       tauri-plugin-single-instance intercepts the second launch on
       Windows/Linux and re-emits it as the same onOpenUrl event
     - was closed: getCurrent() on next launch returns the URL that
       cold-started this process
  -> handleAuthCallbackUrl(url) in tauri-auth.ts:
     - error/error_description present -> toast.error(...), stop
     - code present -> supabase.auth.exchangeCodeForSession(code)
       (reads the stored code_verifier itself, via the legacy-key
       fallback path auth-js uses when no explicit flowId is passed --
       verified by reading @supabase/auth-js's source, not assumed)
  -> exchangeCodeForSession saves the session and fires SIGNED_IN
  -> __root.tsx's existing onAuthStateChange subscription (unchanged)
     invalidates the router + React Query cache
  -> sign-in-card.tsx's new effect sees signedIn become true and
     navigates to /dashboard automatically
```

## 5. PKCE, not implicit

Switched `flowType` from auth-js's default (`'implicit'`) to `'pkce'` in
`client.ts` — a client-wide setting, so it applies to both builds.
Reasoning:

- The user's instruction was explicit: use PKCE if it's the appropriate
  mechanism for a native/public client. It is — RFC 8252 (OAuth for
  native apps) recommends it specifically because a custom URL scheme
  redirect is less protected than an HTTPS one, and implicit flow's
  tokens-directly-in-the-URL shape is more exposed there (e.g. via
  process argv on the Windows/Linux cold-start path this bug already
  involves).
- **Confirmed safe for the web build** by reading `@supabase/auth-js`
  directly: `detectSessionInUrl: true` (the default, unchanged) already
  auto-detects and exchanges a `?code=` on page load the same way it
  auto-detects `#access_token=` — this is existing, built-in behavior,
  not something added here. No web-side code changed.
- **Confirmed the verifier lookup works for a single-flow desktop app**
  by reading `retrievePKCEVerifier` in auth-js's `helpers.js`: when no
  explicit `flowId` is passed to `exchangeCodeForSession`, it falls back
  to a fixed legacy storage key that every flow start also writes
  ("mirrors the most recently started flow") — exactly matching this
  app's one-flow-at-a-time usage, so `exchangeCodeForSession(code)` with
  no extra options is correct, not a corner case that happens to work.

## 6. How the callback reaches Tauri

Two paths, both required (this was bug #2 and #3 above):

- **App already running:** `@tauri-apps/plugin-deep-link`'s `onOpenUrl`
  listener, registered once at startup in `__root.tsx`. On Windows/Linux
  this only works because `tauri-plugin-single-instance` (registered
  first in `src-tauri/src/lib.rs`, its own documented requirement, with
  the `deep-link` feature) intercepts what would otherwise be a second
  app process and forwards its launch URL into the same `onOpenUrl`
  event — verified by reading that plugin's source
  (`deep_link.handle_cli_arguments(...)` runs before the single-instance
  callback whenever the feature is enabled). On macOS/iOS the OS routes a
  repeat launch to the running instance already; the plugin is a no-op
  there.
- **App was closed (cold start):** `getCurrent()`, called once at the
  very start of `initTauriDeepLinkAuth`, per the deep-link plugin's own
  documented pattern for this exact scenario.

## 7. How the session is established

`supabase.auth.exchangeCodeForSession(code)` — the standard auth-js PKCE
exchange call, unchanged from what the web build's own internals already
call (auth-js does this automatically for the web build via
`detectSessionInUrl`; the desktop build calls it explicitly because
there's no page navigation for that auto-detection to hook into). Saves
the session, fires `SIGNED_IN` on `onAuthStateChange` — the same event
both builds already listened for before this fix.

## 8. How secure persistence works

Unchanged from the previous phase's hardening: `tauriSecureStorage`
(`src/lib/tauri-storage.ts`) backed by `src-tauri/src/keychain.rs`'s
Windows Credential Manager / macOS Keychain / Linux Secret Service
commands. Not reintroduced `tauri-plugin-store`, per instruction. The
PKCE `code_verifier` generated in step 1 of the flow is written to and
read from this same store (it's just another key auth-js asks the
configured `storage` adapter to hold) — so it survives the same app
close/reopen and machine-restart scenarios the session tokens do,
which is what makes the cold-start scenario (§6) work correctly.

## 9. Tests performed

**Automated (new — this repo had none before):** `vitest`,
`src/lib/tauri-auth.test.ts`, 8 tests covering
`handleAuthCallbackUrl`/`initTauriDeepLinkAuth` with the real Supabase
client, `sonner`, and the Tauri plugins mocked out (pure logic, no
network, no Tauri runtime needed):

- ignores a URL that isn't the vinco:// callback
- exchanges the code from a successful callback
- surfaces `error_description` (falls back to `error`) via `toast.error`
  without attempting an exchange
- does nothing for a callback with neither a code nor an error
- surfaces a failed exchange (expired/reused code) via `toast.error`
- doesn't throw on a malformed callback URL
- `initTauriDeepLinkAuth` processes a cold-start launch URL from
  `getCurrent()`

All 8 pass; added `bun run test` to `.github/workflows/desktop-build.yml`
so this doesn't regress silently.

**Manual, this sandbox:**
- `tsc --noEmit`, `eslint` (clean on every changed/new file — pre-existing,
  unrelated prettier findings in the auto-generated `client.ts` and in
  `sign-in-card.tsx`'s untouched JSX confirmed via `git stash`, not
  introduced here), web build, desktop build — all pass.
- `cargo check` / `cargo build --release` / `cargo test` (the existing
  keychain mock tests, still 3/3) — all pass with the new
  `tauri-plugin-single-instance` dependency wired in.
- Relaunched the compiled release binary under `xvfb-run` — runs
  stably, no crash.
- Launched a **debug** build with `vinco://auth-callback?code=test` as a
  literal CLI argument (simulating exactly how Windows/Linux deliver a
  cold-start deep link, per the plugin's own documented mechanism) — the
  app started and ran without error or crash.

**What was NOT tested, and why, rather than claiming otherwise:** an
actual Google sign-in round trip. This sandbox has no network route to
`accounts.google.com` or `supabase.co`, and — more fundamentally —
Supabase's redirect allow-list doesn't have `vinco://auth-callback` yet
(§11), so even with network access the flow would still fail at exactly
the step this fix addresses. I also could not directly observe the
webview's JavaScript console during the CLI-argument smoke test (no
console-to-terminal bridge in this headless setup), so "the app didn't
crash when given that argument" is confirmed; "the JS side definitely
called `exchangeCodeForSession`" rests on the unit tests plus reading the
plugin's source, not on watching it happen live. §12 has the exact steps
to close that gap on a real Mac.

## 10. Whether Google end-to-end is proven

**No — explicitly not claiming it.** Proven: the code compiles, the unit
tests for the callback-parsing logic pass, the app launches (including
with a simulated cold-start URL argument) without crashing, and the root
cause is identified with source-level evidence (not inferred from
symptoms alone). Not proven: an actual browser round trip through Google
and Supabase reaching the desktop app's dashboard, which requires both
network access this sandbox doesn't have and the dashboard change in
§11 that hasn't been made yet.

## 11. Supabase dashboard configuration you must change

**One change, in the Supabase dashboard for this project**
(`cvonhorkglqizsxdlulp`):

1. Authentication -> URL Configuration -> **Redirect URLs**
2. Add `vinco://auth-callback`
3. Save

No Google Cloud Console change needed (§1). No other Supabase setting
needs to change. I don't have dashboard access to make this myself.

## 12. Exact steps to test the fixed .dmg

1. Make the Supabase dashboard change in §11.
2. Pull this fix and rebuild: `bun run tauri:build` (produces a new,
   still-unsigned `.dmg` — same as the previous build, no signing added
   this phase).
3. Install the new build over (or alongside) the previous one.
4. **Scenario A (app open):** Launch VINCO, click "Sign in with Google"
   on the login screen, complete Google auth in the system browser. It
   should redirect to a blank-ish `vinco://auth-callback?code=...` page
   (or show a "redirecting" browser page, depending on browser) and then
   the already-open VINCO window should become the dashboard, signed in
   — no extra click needed.
5. **Scenario B (app closed):** Quit VINCO fully. Click "Sign in with
   Google" is no longer possible from a closed app, so instead: sign out
   from a previous successful sign-in (or use a second Google account) to
   get back to the login screen, click sign in, then **quit VINCO before
   finishing** the browser step, complete Google auth in the browser
   anyway, and confirm the `vinco://` link relaunches VINCO straight to
   an authenticated dashboard.
6. Confirm persistence: quit VINCO, reopen it — should land on the
   dashboard already signed in (no login screen). Restart the Mac if you
   want to confirm the OS keychain entry survives a reboot, not just an
   app relaunch.
7. If step 4 or 5 instead shows an error toast, that error message is the
   next concrete thing to report back — it will name what's still wrong
   (e.g. "requested path is invalid" usually means §11 wasn't saved, or
   was saved with a typo).

## Not done this phase (per explicit instruction)

No PostgreSQL, Render, Cloudflare, database schema, RBAC, API business
logic, production domain, code-signing, or mobile changes. No repository
consolidation.
