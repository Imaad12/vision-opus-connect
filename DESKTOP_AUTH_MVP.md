# VINCO Desktop — MVP authentication (Google OAuth parked)

Google OAuth for the desktop app is parked, not deleted. This document
covers: what changed, the mechanism that replaced it, how to set it up,
what it deliberately does *not* touch, and what the real future auth
system looks like.

## What changed

The desktop build no longer shows a login screen or opens a browser at
all. It signs itself in automatically, at launch, as one dedicated
internal Supabase account, then goes straight to the dashboard.

| Before | Now (desktop only) |
|---|---|
| `/` renders `SignInScreen` with a "Sign in with Google" button | `/` renders a plain loading state, then redirects to `/dashboard` once auto-login succeeds |
| Click → system browser → Google → Supabase → `vinco://auth-callback` → Tauri → `exchangeCodeForSession` | `supabase.auth.signInWithPassword()`, called directly, in-process, no browser |
| `__root.tsx` registered a `vinco://` deep-link listener on every launch | No deep-link listener is registered |

**The web app is untouched.** `sign-in-card.tsx`'s non-Tauri branch still
renders the same Google button and calls the same `signInWithOAuth`, byte
for byte. Every `isTauri()` check that used to route to the Google flow
now routes to the auto-login effect instead; nothing about the web
code path changed.

## Why this isn't a new auth architecture

The backend (`app/api/deps.py`, `app/api/auth.py` in the backend repo) was
traced before any code changed here, and none of it was touched:

- Every request still needs a real Supabase-issued JWT as a Bearer token.
- `get_current_user` still verifies that token against Supabase's JWKS.
- `require_permission(...)` still asks Supabase's own `can()` Postgres
  function, using the caller's own token, exactly as before.
- There is no dev-bypass flag, no synthetic user, no widened permission
  check anywhere in the backend.

What's different is only *how* the desktop app obtains that token:
`supabase.auth.signInWithPassword({ email, password })` -- the same
email/password mechanism Supabase's own auth API already supports, called
by code instead of typed into a form. `src/lib/api.ts` (unchanged) then
forwards whatever session exists as `Authorization: Bearer <token>`,
exactly as it always has. The account's actual permissions come entirely
from the existing `user_roles`/`role_permissions` tables -- this grants
nothing the backend didn't already know how to check for any other user.

**Alternatives considered and ruled out** (per the explicit constraints
this was designed against):

- A backend dev-bypass env var (skip `get_current_user`/`can()` entirely
  when set) -- rejected: touches the same code path used in production,
  and an accidental `true` in Render's environment would deauthenticate
  the entire backend, not just the desktop MVP. Much larger blast radius
  for a temporary desktop convenience.
- The Supabase anon/publishable key as the bearer token -- rejected: it
  isn't a per-user JWT (no `sub` claim), `get_current_user` requires one,
  and even if it were accepted, `can()` would evaluate permissions for no
  identity at all, denying everything by default.
- A fabricated/hand-signed JWT -- rejected outright per your instruction;
  would also require holding the project's JWT signing secret in the
  desktop app, which is exactly the class of thing a service-role key is.

## Setting up the dedicated internal account (one-time, manual)

This is a Supabase Dashboard action, not something this session can do
(no dashboard/API access, and creating it via a service-role key is
exactly what was ruled out above).

1. Supabase Dashboard → Authentication → Users → **Add user** → create a
   normal email/password user, e.g. `desktop-dev@vinco.internal`. This is
   an ordinary user row, not a service-role credential.
2. Give it a role the same way any other user gets one: an insert into
   the existing `user_roles` table (Table Editor, or SQL), using
   whichever of the existing roles (Admin, Management, Finance, Sales,
   Procurement, Projects, HR, Viewer) matches what the desktop MVP should
   be able to see/do. This is a data change, not a schema or RLS change.
3. Put that account's email/password in `.env` (project root, gitignored):
   ```
   VITE_DESKTOP_DEV_EMAIL="desktop-dev@vinco.internal"
   VITE_DESKTOP_DEV_PASSWORD="<the password you set>"
   ```
4. For CI (`.github/workflows/desktop-build.yml`): add the same two
   values as repo secrets, `VITE_DESKTOP_DEV_EMAIL` /
   `VITE_DESKTOP_DEV_PASSWORD` (Settings → Secrets and variables →
   Actions), matching how `VITE_SUPABASE_PUBLISHABLE_KEY` is already
   configured there. Until that's done, `build-desktop`'s
   `frontend-checks`/`build-desktop` jobs will fail at
   `check-desktop-env.mjs` -- deliberately, the same way a missing local
   `.env` fails `bun run tauri:build` (see that script's own error
   message for exactly what's missing).

**Revoking desktop access** is exactly as easy as granting it: disable
the account or rotate its password in the Supabase Dashboard. It's not a
special case the app needs to know about -- the next `signInWithPassword`
call just fails, same as any other invalid Supabase login, and
`sign-in-card.tsx`'s retry screen surfaces that.

## What's parked, not removed

`src/lib/tauri-auth.ts` (the Google OAuth flow itself, PKCE, callback
parsing) and its test suite are left completely intact -- see that file's
own updated doc comment. Nothing calls it right now:

- `__root.tsx` no longer calls `initTauriDeepLinkAuth()`.
- `sign-in-card.tsx` no longer calls `signInWithGoogleDesktop()`.

The Tauri-side infrastructure it depends on is also left in place,
unused but harmless: `tauri-plugin-deep-link` / `tauri-plugin-opener`
registrations in `src-tauri/src/lib.rs`, the `vinco://` scheme in
`tauri.conf.json`, the `deep-link`/`opener` capabilities. None of it does
anything unless JS calls into it, and nothing does anymore.

**To reintroduce Google OAuth later:** re-add the
`initTauriDeepLinkAuth()` call in `__root.tsx`, and give `sign-in-card.tsx`
a way to choose between the two (e.g. Google for a real end-user, the dev
account only in an explicit development mode) instead of unconditionally
auto-signing-in on desktop. Everything else -- the PKCE flow, the deep
link handling, the keychain storage -- needs no changes to work again.

## The real future system

The username/password login described above is now built --
`src/lib/vinco-auth.ts` (web) plus `backend/app/api/routers/users.py` /
`backend/app/services/user_service.py` (native account creation/role
management, "Settings → Users & Access" in the app). See the root
`README.md`'s "Native login and user management" section for the full
picture. Enforced through the exact same `require_permission`/`can()`
path this document confirmed is untouched by the original MVP -- a real
per-user login just replaces *how* a session is obtained, exactly as
predicted above.

**What's still exactly as this document originally described, and
deliberately not changed by adding native login:** the desktop build's
*default* sign-in is still this file's automatic dedicated-account flow,
not the new native login. That migration -- desktop asking for a VINCO
username/password instead of auto-signing-in -- was explicitly sequenced
as a separate, later step once the new login path is proven in real use
(first on web), not something to flip silently as a side effect of
building the login system itself. When that migration happens: replace
`signInDesktopDevAccount()`'s call site in `sign-in-card.tsx`'s
`isTauri()` branch with the same login form the web branch already
renders (`signInWithUsernamePassword` from `src/lib/vinco-auth.ts`
handles both identically -- nothing platform-specific about it), then
retire `tauri-dev-auth.ts` and its `VITE_DESKTOP_DEV_EMAIL`/
`VITE_DESKTOP_DEV_PASSWORD` build-time requirement once no build depends
on it. The dedicated internal account itself can remain as a fallback/
migration-safety account for a period rather than being deleted
immediately.

## Files changed

| File | Change |
|---|---|
| `src/lib/tauri-dev-auth.ts` (new) | The auto-login function: `signInDesktopDevAccount()`. |
| `src/lib/tauri-dev-auth.test.ts` (new) | 4 tests: existing session is a no-op, missing env vars throw clearly, successful sign-in, failed sign-in propagates. |
| `src/components/sign-in-card.tsx` | Desktop branch (`isTauri()`) now renders a plain loading/retry state and calls `signInDesktopDevAccount()` instead of showing the Google button / calling `signInWithGoogleDesktop()`. Web branch unchanged. |
| `src/routes/__root.tsx` | Removed the `initTauriDeepLinkAuth()` call and its import (no deep-link listener registered). |
| `src/lib/tauri-auth.ts` | Doc comment only: marked PARKED, points here. No logic changed; tests untouched and still passing. |
| `scripts/check-desktop-env.mjs` | `VITE_DESKTOP_DEV_EMAIL` / `VITE_DESKTOP_DEV_PASSWORD` added to the required-vars check (fails the build loudly if unset, same convention as the Supabase vars). |
| `.env.example` | Documents the two new vars and how to obtain them. |
| `.github/workflows/desktop-build.yml` | Passes the same two vars through from new repo secrets. |

No changes to `tauri.conf.json`, capabilities, `keychain.rs`,
`lib.rs`'s plugin registration, the backend, RBAC, the database, or any
production/web configuration.
