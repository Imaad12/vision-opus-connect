# VINCO Desktop — "This page didn't load" runtime failure

The `.dmg` built and installed fine (that investigation is closed — see
`DESKTOP_DMG_BUILD_FIX.md`). This is a separate, later-stage bug: the
installed app launches but immediately shows a generic error page
instead of the sign-in screen.

## DESKTOP RUNTIME DIAGNOSIS

```
App launches:          YES
index.html loads:      YES
main JS loads:          YES
CSS loads:              YES (Google Fonts request failed in my sandbox —
                        network-only, non-fatal, unrelated: see §9)
router initializes:     YES
root route renders:     NO  -- root errorComponent renders instead
login route renders:    NO  -- never reached; the crash happens in the
                        root layout's own effect, before any route's
                        content matters
Supabase initializes:   NO  -- throws synchronously on first access
first JS exception:     Error: Missing Supabase environment variable(s):
                        SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY. Connect
                        Supabase in Lovable Cloud.
                          at createSupabaseClient
                          (src/integrations/supabase/client.ts)
first failed resource:  none required for the crash (the Google Fonts
                        stylesheet failed in my sandbox for unrelated
                        network reasons -- the page still renders fine
                        without it once Supabase is configured; see §9)
root cause:             VITE_SUPABASE_URL / VITE_SUPABASE_PUBLISHABLE_KEY
                        were not available to Vite when the desktop
                        bundle was built, so both are baked into the
                        shipped JS as undefined. See §1-§8 for how this
                        was proven, not assumed.
```

## 1-2. Reproduced from current HEAD, inspected the artifact

Clean-rebuilt `bun run build:desktop` from HEAD. `dist/client/` contains
exactly one HTML file, `index.html` (copied from the SPA-mode shell
`_shell.html` by `scripts/copy-desktop-shell.mjs`), plus a flat
`assets/` directory of hashed JS/CSS chunks, `favicon.ico`, and
`robots.txt`. No sign of a hybrid artifact: `dist/server/` also exists
(TanStack Start's SSR build always runs, since it also produces the
prerendered shell — see §4), but Tauri's `frontendDist` in
`tauri.conf.json` only points at `dist/client`, and nothing in
`dist/client` references anything under `dist/server`.

`dist/client/index.html`'s `<head>` references exactly one local
stylesheet (`/assets/styles-*.css`) and preloads six local JS chunks
(`/assets/index-*.js`, `/assets/rolldown-runtime-*.js`,
`/assets/i18n-*.js`, `/assets/use-auth-*.js`, `/assets/routes-*.js`,
`/assets/sign-in-card-*.js`) plus one external Google Fonts stylesheet.
Every one of those local files exists under `dist/client/assets/` --
checked directly, not assumed.

## 3, 5, 6. Does Tauri's custom protocol actually break asset loading?

This is where I want to be precise about what I could and couldn't test
directly. I have no macOS environment, so I can't drive the real Tauri
custom-protocol webview. What I *could* do, and did, per your
instruction #6: serve the **exact** `dist/client` directory (the same
bytes Tauri bundles) with a plain static file server, and load it in
real headless Chromium, capturing every console message, thrown
exception, and failed network request.

First run -- against a build made **without** `VITE_SUPABASE_URL` /
`VITE_SUPABASE_PUBLISHABLE_KEY` available (see §8 for why I built it
that way) -- reproduced your exact screenshot, byte for byte:

```
=== BODY TEXT ===
This page didn't load

Something went wrong on our end. You can try refreshing or head back home.

Try again
Go home

=== CONSOLE ===
[error] [Supabase] Missing Supabase environment variable(s): SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY. Connect Supabase in Lovable Cloud.
[error] Error: Missing Supabase environment variable(s): SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY. Connect Supabase in Lovable Cloud.
    at Ca (assets/i18n-*.js)              <- minified createSupabaseClient
    at Object.get (assets/i18n-*.js)      <- the `supabase` Proxy's get-trap
    at assets/index-*.js                  <- __root.tsx's RootComponent effect
    ...React internals (Dl/El = fiber commit/effect machinery)...
```

Second run -- identical build, only difference: `VITE_SUPABASE_URL` /
`VITE_SUPABASE_PUBLISHABLE_KEY` present -- same static files served the
same way, same headless Chromium:

```
=== BODY TEXT ===
VC
VINCO ERP
Vision Contracting Co.
...
Sign in with Google
...

=== CONSOLE ===
(no JS exceptions)
```

Same artifact, same protocol-equivalent static serving, same browser.
The only variable that changed between a broken run and a working run
was whether Supabase's env vars existed at build time. That is direct,
reproduced evidence -- not an assumption -- that Tauri's custom
protocol, asset paths, the SPA shell, and the router are not the
problem: the identical files render correctly once the one real
precondition is met.

(Root-relative `/assets/...` paths, dynamically imported route chunks,
and the favicon all loaded with 200s in both runs -- confirmed from the
same captured network log, trimmed above for length.)

## 4. Is this a hybrid SSR+SPA artifact?

No, and the `-vv` output that mentioned both "building client
environment" and "building ssr environment" is expected, not a bug.
TanStack Start's SPA mode (`spa: { enabled: true }` in `vite.config.ts`,
added for the desktop target specifically) works by running the normal
SSR pipeline **once, at build time**, capturing whatever HTML it
produces for `/`, and writing that as a static file (`_shell.html` --
`_shell` is literally the plugin's own default output name, confirmed
by reading `@tanstack/start-plugin-core`'s schema source). The `dist/
server` build that appears in the log is that one-time SSR pass, not
something Tauri or an installed app ever runs -- it's not shipped in
the `.app`/`.dmg` at all. So "hybrid" isn't quite right: it's "SSR used
once, at build time, to generate a static file" -- a supported, intended
TanStack Start feature, not an accidental leftover.

The real problem is a **consequence** of that design, though, and it's
worth stating plainly: because the one-time SSR pass never executes a
React `useEffect` (SSR never runs effects, only render), a build with
missing Supabase env vars still produces a syntactically valid
`_shell.html` and exits 0. The `Missing Supabase environment
variable(s)` throw only happens once a real browser (or webview)
hydrates the page and runs `RootComponent`'s effect. That's exactly
why `bun run tauri:build:verbose` completing successfully, and the
`.app`/`.dmg` existing, proved nothing about whether the app would
actually render -- packaging success and runtime correctness are
different questions here, and only the second one was broken.

## 7-8. The actual exception, and why it happens

`src/routes/__root.tsx`'s `RootComponent` runs this on mount:

```ts
useEffect(() => {
  const { data: sub } = supabase.auth.onAuthStateChange((event) => { ... });
  return () => sub.subscription.unsubscribe();
}, [router, queryClient]);
```

`supabase` (`src/integrations/supabase/client.ts`) is a lazy `Proxy` --
`createSupabaseClient()` only runs the first time any property is
accessed. That function reads `import.meta.env['VITE_SUPABASE_URL']`
and `import.meta.env['VITE_SUPABASE_PUBLISHABLE_KEY']` (both are Vite
build-time constants, baked permanently into the compiled bundle, not
readable/settable after the fact) and, if either is missing, throws
synchronously:

```ts
if (!SUPABASE_URL || !SUPABASE_PUBLISHABLE_KEY) {
  throw new Error(`Missing Supabase environment variable(s): ${missing.join(', ')}. Connect Supabase in Lovable Cloud.`);
}
```

That throw happens inside the very first commit of `RootComponent`,
which is exactly what `__root.tsx`'s own `errorComponent` exists to
catch -- and its copy is, word for word, "This page didn't load /
Something went wrong on our end. You can try refreshing or head back
home." That's not a coincidental resemblance to "TanStack's generic
error page": it *is* this app's own root error boundary, defined right
next to the code that threw.

**Why the build didn't warn you:** `VITE_SUPABASE_URL` and
`VITE_SUPABASE_PUBLISHABLE_KEY` come from a `.env` file in the project
root (see `.env.example`), and `.env` is (correctly) `.gitignore`d --
confirmed via `git check-ignore -v .env`. It is never in a fresh clone
and has to be created locally, per machine, before building. Nothing
before this fix checked that `.env` existed or was complete before
`bun run tauri:build` ran, so a machine without it produces a fully
valid-looking, installable `.app`/`.dmg` that is silently broken.

## 9. Web vs. desktop -- first divergence

The web build reads the same env vars the same way and would show the
same broken screen if they were missing there too -- this is not a
desktop-specific code bug. The reason it surfaced on desktop first is
operational, not architectural: the web deployment's `VITE_SUPABASE_URL`
/ `VITE_SUPABASE_PUBLISHABLE_KEY` are already configured once in
Cloudflare's build environment and never touched again, while a local
desktop build depends on a developer's machine having its own `.env`
every time. (The unrelated Google Fonts failure in my test run is a
sandbox network restriction -- no outbound access to
`fonts.googleapis.com` here -- not something present on your Mac or
relevant to the crash; I called it out only because your instructions
asked for every failed request, not because it explains anything.)

## The fix

Added `scripts/check-desktop-env.mjs`, run as the first step of
`build:desktop` (before `vite build`):

```json
"build:desktop": "node scripts/check-desktop-env.mjs && cross-env VINCO_TARGET=desktop vite build && node scripts/copy-desktop-shell.mjs"
```

It calls Vite's own `loadEnv()` (so it checks exactly what the
following `vite build` will actually see -- same `.env`/`.env.local`
rules, not a reimplementation) merged with `process.env` (so CI's
`env:`-injected values, which never go through a `.env` file, are
honored too), and requires `VITE_SUPABASE_URL` and
`VITE_SUPABASE_PUBLISHABLE_KEY` to be present. If either is missing, it
prints the exact fix and exits 1 -- **before** Rust ever compiles
anything -- instead of letting `tauri build` spend several minutes
producing an installable artifact that's broken on launch.

This doesn't change what gets shipped when the env vars *are* present
(verified: output is byte-identical in content, only the normal
per-build asset hashes differ) -- it only turns a silent, late,
confusing failure into an immediate, actionable one.

### What you need to do on your Mac

Copy `.env.example` to `.env` in the project root and fill in real
values from the Supabase Dashboard (Project Settings -> API), then
re-run `bun run tauri:build`. If `.env` already exists there, check
which of the two Supabase values is actually empty -- `cat .env` and
compare against `.env.example`'s key names.

## Files changed

| File | Change |
|---|---|
| `scripts/check-desktop-env.mjs` (new) | Preflight check: fails the desktop build loudly if `VITE_SUPABASE_URL`/`VITE_SUPABASE_PUBLISHABLE_KEY` aren't resolvable, instead of shipping a broken artifact silently. |
| `package.json` | `build:desktop` now runs the check first. |

No changes to `tauri.conf.json`, `vite.config.ts`, `__root.tsx`,
`src/integrations/supabase/client.ts`, or any Rust source -- the SPA
shell architecture, asset paths, and router were all confirmed working;
nothing there needed fixing.

## Validation

- `node scripts/check-desktop-env.mjs` with `.env` removed -- fails,
  exit 1, prints the exact missing vars and the fix.
- Same, with `.env` restored -- passes, exit 0.
- Same, with `.env` removed but the two vars set directly in
  `process.env` (how CI provides them) -- passes, exit 0. CI's
  `desktop-build.yml` already sets both at the job `env:` level, so it
  is unaffected by this change.
- `bunx tsc --noEmit` -- clean.
- `bun run test` (vitest) -- 8/8.
- `bun run build` (web) -- clean.
- `bun run build:desktop` -- clean, with the new check passing first.
- `cargo check` / `cargo test` (`src-tauri`) -- clean / 3/3.
- Headless-Chromium runtime check against the **exact** `dist/client`
  output (§3 above) -- confirmed broken without the env vars, confirmed
  fixed with them, using the identical static files Tauri bundles.

**Not done, and I want to be explicit about why:** rebuilding the real
`.app`/`.dmg` and launching it on macOS. I have no macOS environment in
this sandbox (same limitation as the DMG investigation). Given the
headless-Chromium evidence above is against the literal files Tauri
packages, and Tauri's custom protocol was already shown (via the DMG
investigation) to serve static files correctly, I'm confident this
transfers -- but "confident" isn't "verified on your Mac," so please
run the checklist below for real.

## What I need from you

```sh
bun run tauri:build
```

This will now fail immediately with a clear message if `.env` is
missing/incomplete (see "What you need to do on your Mac" above). Once
it passes and produces the `.dmg`:

1. Install and launch it.
2. Confirm the sign-in screen renders (not the error page).
3. Only then test the Google OAuth flow.

If the sign-in screen still doesn't render after `.env` is confirmed
correct, open the WebView's dev tools (right-click -> Inspect, if
enabled) or check Console.app for the same
`Missing Supabase environment variable(s)` string -- if it's gone but
something else is thrown, share that exact message and I'll trace it
the same way.
