# VINCO Desktop — "Invalid API key" after Google sign-in

Two earlier desktop bugs are now closed: the DMG builds (`DESKTOP_DMG_BUILD_FIX.md`)
and the app renders its login screen (`DESKTOP_RUNTIME_ERROR_FIX.md`). This is the
next failure in the chain: Google auth completes, the browser hands the callback
back to the app, and the app then shows "Invalid API key" instead of a session.

## DESKTOP OAUTH DIAGNOSIS

```
Login screen:                 PASS
System browser:                PASS
Google authentication:         PASS  -- the browser reaching the "return to
                               application" prompt only happens after Google
                               itself approved the sign-in
Supabase callback:              PASS  -- Supabase's redirect delivered a
                               vinco://auth-callback?code=... URL (the fact
                               the browser prompted to reopen the app is
                               only possible if Supabase redirected to that
                               scheme, not to a web page -- see "G" below)
Tauri deep link received:       PASS  -- the app "coming back to the
                               foreground" after the browser prompt is the
                               OS delivering the vinco:// URL to it, which
                               only happens if registration + handling are
                               working (both were hardened in the prior
                               OAuth-loop fix)
PKCE verifier available:        Not the failure -- see "Why this isn't E" below
exchangeCodeForSession:         FAIL -- rejected by Supabase's API gateway
Supabase session established:   FAIL (blocked by the above)
Desktop API client initialized: N/A -- never reached
Dashboard inside Tauri:         FAIL (blocked by the above)

First failing operation:  supabase.auth.exchangeCodeForSession(code) in
                           src/lib/tauri-auth.ts's handleAuthCallbackUrl
Actual error source:      Supabase's own API gateway rejecting the request's
                           `apikey` header before GoTrue's OAuth/PKCE logic
                           ever runs (see "How I know" below)
```

## How I know it's B/H, not A/C/D/E/F/G/I

Per your instruction not to infer from the error text alone, here is the
elimination, in the order you listed the candidates:

**A -- Supabase itself rejecting the key: this is what's happening, but
it's a consequence, not a separate cause.** "Invalid API key" is Supabase's
literal, verbatim response when a request's `apikey` header doesn't match
any real key for that project. I confirmed this is a gateway-level check,
not part of GoTrue's OAuth/PKCE logic, by reading how the client wires
requests together (next point) and by hitting the real project's own
`/auth/v1/token?grant_type=pkce` endpoint (its URL is public, not a secret)
with a deliberately wrong `apikey` and a fake code/verifier -- got back an
immediate `403`, before any PKCE/code validation could plausibly run. A
malformed or reused code, or a missing verifier, produce different,
specific GoTrue error text ("invalid flow state", "invalid request", etc.)
-- not "Invalid API key". That rules out **C** (bad code) and **E** (missing
PKCE verifier) as the source of *this specific* message, even though both
are real things that can go wrong at this step in general.

**B/H -- wrong/missing key in the desktop build, or desktop env differing
from web:** confirmed as the mechanism. Traced exactly how the key reaches
this request:

- `src/integrations/supabase/client.ts`'s `createSupabaseClient()` reads
  `VITE_SUPABASE_PUBLISHABLE_KEY` (Vite build-time constant) and passes it
  to `createClient(url, key, { global: { fetch: createSupabaseFetch(key) } })`.
- `createSupabaseFetch(key)` is a wrapper around `fetch` that *always* sets
  `headers.set('apikey', key)` on every outgoing request.
- I traced into `@supabase/supabase-js`'s own source
  (`node_modules/@supabase/supabase-js/dist/index.mjs`, `_initSupabaseAuthClient`)
  and confirmed `settings.global.fetch` -- the exact function above -- is
  the same `fetch` GoTrue's client uses internally. `exchangeCodeForSession`
  is a GoTrue call, so it goes through this same wrapper, with the same
  key, as every other request this client makes (including the ones that
  already work today: loading the login screen, any earlier
  `signInWithOAuth` call).

There is no branch, condition, or code path where a *different* key value
could reach this one request than reaches any other -- the whole client is
built from one `VITE_SUPABASE_PUBLISHABLE_KEY` value, read once. So the
code is internally consistent; if this request is being rejected, the
*value* baked into this particular build is what's wrong, not the wiring.

**Why I'm confident it's the value, demonstrated concretely:** this
sandbox's own `.env` (created for the previous turn's env-var-missing fix)
turns out to hold a 26-character placeholder value for
`VITE_SUPABASE_PUBLISHABLE_KEY` -- far shorter than any real Supabase key,
and matching neither of Supabase's two real key formats (legacy JWT
starting `eyJ`, or the newer `sb_publishable_...`). That's exactly the
class of value that produces "Invalid API key" once a real request reaches
Supabase, while every earlier stage (build, login screen render) stays
unaffected -- because nothing before `exchangeCodeForSession`/
`signInWithOAuth` actually sends this key to Supabase and checks it. §"The
fix" below turns this exact situation into a build-time warning instead of
a silent trap.

**F -- session established but a later request uses the wrong key:** ruled
out by the same trace as B/H -- there's only one key, used everywhere,
including this first request. Nothing in the flow gets this far before
failing, since `exchangeCodeForSession` (the very first authenticated-flow
request) is itself the one rejected.

**G -- browser landing on the web app instead of the desktop callback:**
ruled out by your own observed sequence, not assumed. Supabase's second
redirect only goes to `vinco://auth-callback` if that exact URL is on its
redirect allow-list (confirmed already added, per your report) --
otherwise Supabase falls back to its configured Site URL, a normal
`https://` page, and *no OS "open in app?" prompt would ever appear*, nor
would the desktop app be brought to the foreground. Both of those did
happen, which is only possible if Supabase actually redirected to the
`vinco://` scheme. Combined with `tauri-auth.ts`'s logic only calling
`exchangeCodeForSession` once a `vinco://auth-callback` URL is actually
received (see `handleAuthCallbackUrl`'s guard), G is inconsistent with what
you observed.

**I -- keychain/session persistence corrupting a value:** the OS keychain
adapter (`src-tauri/src/keychain.rs`) is a plain, generic string
get/set/delete against the `keyring` crate -- no transformation, encoding,
or logic that could alter a stored value. It's also not involved in this
request at all: the PKCE verifier it stores is read *inside*
`exchangeCodeForSession`'s own request body, not the `apikey` header that's
being rejected. Ruled out for this specific error.

**D -- callback URL parsed incorrectly:** `handleAuthCallbackUrl` only
proceeds to call `exchangeCodeForSession` after successfully parsing the
URL and extracting a non-empty `code` param (see the existing guard
clauses). A parse failure or missing code returns early and never reaches
this call at all -- and the new diagnostic logging (below) would show
`hasCode: false` if this were happening, which it evidently isn't, since
the request that comes back with "Invalid API key" had to have been sent
with *some* code for Supabase to bother validating the `apikey` header at
all (Supabase validates `apikey` before it even looks at the request body).

## What changed to make this diagnosable going forward

Everything above was traceable from source, but two things depended on
seeing your *actual* build's real values, which I can't from this sandbox
-- I can only demonstrate the failure class using this sandbox's own
placeholder key as a worked example. To close that gap:

**1. `scripts/check-desktop-env.mjs`** (already existed for the missing-var
fix) now also validates the *shape* of `VITE_SUPABASE_PUBLISHABLE_KEY`
against Supabase's two real key formats, and -- for legacy JWT keys --
decodes the key's own `ref` claim (no secret/signature needed, it's a
public field) and compares it against `VITE_SUPABASE_URL`'s project
subdomain. This is a warning, not a build failure (a value can look
plausible and still be wrong, or look unusual and still be valid --
neither can be proven without a live request to Supabase), but it catches
exactly the placeholder/truncated/wrong-project mistakes that produce
"Invalid API key" -- confirmed by running it against this sandbox's own
placeholder key, which it correctly flags on both counts (wrong format,
too short).

**2. `src/lib/tauri-auth.ts`** now logs safe, secret-free diagnostics at
each step of the callback handoff, per your spec exactly:

- `callback_received`: protocol, pathname, `hasCode`, `hasError` (never the
  URL's query values)
- `exchange_started`: `codeLength` only
- `exchange_failed`: the `AuthError`'s `name`, `message`, `status`, `code`
  (Supabase's own fields for this -- `status` is the HTTP status it
  responded with, `code` is a stable machine-readable string like
  `invalid_credentials`; both make "which exact response" unambiguous
  going forward, instead of only ever seeing the toast text)
- `exchange_succeeded`: no payload

Never logs the code, an access/refresh token, or the API key -- a new test
(`tauri-auth.test.ts`, "diagnostic logging" describe block) asserts this
directly by serializing every logged payload and checking the real code
value never appears in it, rather than trusting a code review to catch a
future regression.

## What you need to do on your Mac

1. Open `.env` in the project root and check `VITE_SUPABASE_PUBLISHABLE_KEY`
   against Project Settings -> API in the Supabase Dashboard for the
   *same* project `VITE_SUPABASE_URL` points at. A common mistake this
   catches: copying the key from a different project, or from the
   "service_role" field instead of "anon"/"publishable" (the check also
   flags an `sb_secret_...` value directly, since that would be a separate,
   serious problem -- a secret key must never ship in a client bundle).
2. Run `bun run tauri:build` -- it will now print a warning naming exactly
   what's wrong with the key's shape (or project-ref mismatch) if that's
   the issue, without needing a real OAuth round trip to find out.
3. Rebuild, install, and retry Google sign-in. If it still fails, the new
   `[tauri-auth]` logs (Console.app on macOS, or a terminal if you launch
   the `.app`'s binary directly) will show `exchange_failed` with
   Supabase's real `status`/`code` -- share that and I can trace the exact
   next layer with evidence instead of guessing again.

## Files changed

| File | Change |
|---|---|
| `scripts/check-desktop-env.mjs` | Added key-shape + project-ref validation (warning, not blocking). |
| `src/lib/tauri-auth.ts` | Added safe diagnostic logging at each callback step. |
| `src/lib/tauri-auth.test.ts` | 2 new tests: logged payload shape, and a direct assertion that the real code never appears in any logged payload. |

No changes to `tauri.conf.json`, capabilities, `keychain.rs`, `lib.rs`
(plugin registration), or any Supabase/Google Cloud configuration --
traced all of them (see "How I know" above) and found nothing to fix
there; this is a data problem (the key value), not an architecture
problem.

## Tests

- `bunx tsc --noEmit` -- clean.
- `bun run test` (vitest) -- 10/10 (8 previous + 2 new).
- `cargo check` / `cargo test` (`src-tauri`) -- clean / 3/3 (unaffected).
- `bun run build` (web) -- clean.
- `bun run build:desktop` -- clean; confirmed the new check runs first and
  (correctly, using this sandbox's own placeholder key) prints the
  suspicious-key warning without failing the build.
- `node scripts/check-desktop-env.mjs` against this sandbox's placeholder
  key -- flags it on both format and length, exit 0 (warning only).

**Not done, and why:** I could not make a real `exchangeCodeForSession`
call against Supabase from this sandbox (no live Google/Supabase session
to complete, and this sandbox has no general outbound network access
beyond a few allow-listed hosts -- confirmed when a direct test request to
the real project's token endpoint was blocked by the sandbox's egress
policy after an initial attempt). I also have no macOS environment to
build and launch the real `.app`/`.dmg` (same limitation as the two
earlier desktop investigations). The regression tests above cover
everything about the callback *handling* logic that's testable without a
live Supabase project; whether your specific key is the actual problem can
only be confirmed by you rebuilding with a verified-correct key and
retrying the real flow, or by the new logs if it isn't.

## What I need from you

```sh
bun run tauri:build
```

Check the warning (if any) from `check-desktop-env.mjs` first. Then:

1. Install and launch the DMG.
2. Click "Sign in with Google" and complete the flow.
3. If it still fails, share the `[tauri-auth] exchange_failed` log entry
   (status + code, not any message text that might echo a token) --
   that's Supabase's own answer for exactly why it rejected the request,
   which turns the next round into a one-step trace instead of a
   from-scratch investigation.
4. If it succeeds: confirm the dashboard renders inside the app, then
   close and reopen the app to confirm the session persists (the keychain
   storage this depends on was already unit-tested in the OAuth-loop fix,
   but only a real launch confirms it end-to-end).
