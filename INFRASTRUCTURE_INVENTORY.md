# VINCO — repository dependencies and domain/URL inventory

> **Superseded.** This was written when the frontend and backend were two
> separate repositories, per that earlier pass's explicit instruction not
> to consolidate yet. That consolidation has since happened: the backend
> now lives at `backend/` in this same repository (merged via `git
> subtree`, full history preserved) -- see the root `README.md`. The
> couplings this file documents are still real (a renamed backend route
> still silently breaks the frontend, etc.), just no longer *cross-repository*
> ones. Kept as a record of what to check when changing either side, not
> because the two-repo framing below is still accurate.

## Repository dependencies (historical: written when these were two separate repos)

Two repositories today: `vision-opus-connect` (this one -- frontend web + desktop)
and `vision-contracting-profit` (backend -- FastAPI + PostgreSQL/Alembic). Every
place one depends on the other's specifics:

| From | To | What couples them |
|---|---|---|
| `src/lib/api.ts` | Backend's FastAPI routes | Hardcoded relative paths (`/clients`, `/vendors`, `/dashboard/summary`, etc.) matching the backend's `app/api/routers/*.py` route definitions exactly -- a renamed backend route breaks this silently until someone hits it. |
| `src/components/resource-page.tsx` configs (`customers.tsx`, `suppliers.tsx`, `leads.tsx`, `invoices.tsx`, `payments.tsx`, `expenses.tsx`, `projects.tsx`, `quotations.tsx`, `contracts.tsx`, `purchase-orders.tsx`) | Backend's Pydantic response/request models | Each `fields`/`columns` list's `key`s must match the backend model's real field names (see each file's own comments on this, e.g. invoices.tsx's note about `direction` replacing `type`) -- there is no shared type generation between the two repos; this is maintained by hand on both sides. |
| Backend's `app/api/auth.py`/`app/api/deps.py` | Supabase's `user_roles`/`role_permissions`/`can()` (frontend repo's `supabase/migrations/*.sql`) | The backend has no permission model of its own -- every `require_permission("x.y")` call names a permission string that must exist in the frontend repo's `app_permission` enum, or the check always fails. |
| `src/hooks/use-auth.ts` (`PERMISSION_GROUPS`, `ROLE_LABELS`) | Same `supabase/migrations/*.sql` enum | A hand-maintained mirror of the enum's values, purely for UI labels/grouping -- can drift silently if the enum changes without this file being updated too. |
| Backend's `render.yaml`/`Dockerfile` | Nothing in this repo directly, but... | ...the backend's CORS allow-list (`VISION_CORS_ALLOWED_ORIGINS`, see Domains section) must include whatever origin this repo's web build is actually served from, or every backend API call fails browser-side with a CORS error the backend logs would show as "fine" (it never even reaches FastAPI's app code -- rejected by the CORS middleware first). |
| This repo's desktop build (`DESKTOP_AUTH_MVP.md`) | A Supabase user only this repo's docs describe how to create | The dedicated internal account this depends on lives in Supabase, has no representation in either repo's committed code, and must be recreated by hand if the Supabase project is ever recreated/migrated. |

**What's NOT coupled** (safe to change independently today): UI styling/i18n, Rust/
Tauri internals, the backend's internal service-layer structure below its API
surface, database migrations that don't touch `app_permission`/route shapes,
CI workflow internals on either side.

**Eventual single-repo goal** (not attempted now): merging would mostly mean moving
the backend's `app/`, `migrations/`, `render.yaml`, `Dockerfile` into this repo
alongside `src/`, `src-tauri/`, keeping both CI workflows, and -- the real
work -- replacing the hand-synced field-name/permission-string coupling above with
something generated from one shared source (e.g. an OpenAPI spec the frontend
codegens against) so the two sides can't drift silently again.

## Domains, URLs, and where they're configured

None of this was touched this pass. Listing where each one actually lives, since
none of it is visible from reading either repo's code alone -- most of it is
dashboard-only configuration.

| What | Current value / where set | Lives in |
|---|---|---|
| Web app's own origin (what Cloudflare serves it at) | Not in this repo at all -- no committed `wrangler.json`/`wrangler.toml` | Cloudflare Pages dashboard (project settings + custom domain, if any) -- this repo's `vite.config.ts` only configures the *build* (nitro's Cloudflare preset), not where it's deployed |
| Web build's `VITE_SUPABASE_URL`/`VITE_SUPABASE_PUBLISHABLE_KEY`/`VITE_API_URL` | Baked in at Cloudflare's build time | Cloudflare Pages dashboard -> Settings -> Environment variables (separate from this repo's local `.env`, which only affects local `bun run dev`/`build`) |
| Backend API's own origin | Whatever Render assigns/whatever custom domain is attached | Render dashboard for the `vinco-api` service (`render.yaml` pins the *branch* it builds from, not a domain) |
| Backend's `VISION_DATABASE_URL`/`VISION_SUPABASE_URL`/`VISION_SUPABASE_ANON_KEY`/`VISION_CORS_ALLOWED_ORIGINS` | Render secrets (`render.yaml` declares the keys with `sync: false`, meaning "set by hand in the dashboard, never committed") | Render dashboard -> `vinco-api` -> Environment |
| Backend's CORS allow-list | `VISION_CORS_ALLOWED_ORIGINS` (comma-separated), read by `app/core/config.py` and applied in `app/api/main.py`'s `CORSMiddleware` | Same Render env var above -- must list the web app's real Cloudflare origin(s) exactly, or the browser blocks every API call from that origin |
| Supabase project URL/keys (both repos) | `cvonhorkglqizsxdlulp.supabase.co` today | Supabase Dashboard -> Project Settings -> API; consumed via each repo's own env vars (frontend: `.env`/Cloudflare vars; backend: Render's `VISION_SUPABASE_URL`/`VISION_SUPABASE_ANON_KEY`) |
| Supabase Auth redirect URLs (Google OAuth callback allow-list) | Includes `vinco://auth-callback` (added for the now-parked desktop OAuth flow) plus whatever web callback URL(s) are configured | Supabase Dashboard -> Authentication -> URL Configuration -- not touched this pass, not touched by parking desktop OAuth either (left as-is per "do not touch Google OAuth") |
| Google Cloud OAuth client's own redirect URI | Supabase's own fixed `https://<project-ref>.supabase.co/auth/v1/callback` (not a VINCO-controlled URL) | Google Cloud Console, for the OAuth client Supabase's Google provider uses |
| Desktop app's identifier | `com.visioncontracting.vinco` | `src-tauri/tauri.conf.json` -- this one *is* in-repo, not a dashboard setting |
| Desktop's backend URL when built locally | Defaults to `http://localhost:8000` unless `.env`'s `VITE_API_URL` overrides it | Local `.env` only -- there's no "production desktop" backend URL configured anywhere yet, since desktop builds are unsigned/internal for now |

**The eventual cleanup this enables** (not attempted now): once actual production
domains are decided, this table is the checklist of every place a URL needs to be
updated together -- Cloudflare's custom domain, Render's CORS allow-list, Supabase's
redirect allow-list, and (if desktop ever points at a real hosted backend instead of
localhost) a real `VITE_API_URL` for desktop builds.
