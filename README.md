# VINCO ERP

Internal ERP for Vision Contracting Co.: customers, contacts, leads,
quotations, approvals, projects, contracts, suppliers, purchase orders,
invoices, payments, expenses, employees, finance/management reporting,
and audit logs.

## For VINCO users

Open VINCO (desktop app or the web address your administrator gave you)
and sign in with the username and password your administrator created
for you:

```
VINCO

Username
[________________]

Password
[________________]

[ Sign In ]
```

That's it — no Google account, no separate login screen, nothing else to
set up.

## For administrators

Go to **Settings → Users & Access** to create accounts and manage roles.
For each person you add: a display name, a username, a temporary
password (they can be given a new one later from the same screen), and a
role:

| Role | Access |
|---|---|
| Employee | Limited, day-to-day operational access |
| Admin | Broad operational/management access |
| Super User | Full application access |
| Super Admin | Everything Super User has, plus user/system administration |

You can deactivate an account at any time (they immediately lose access,
without deleting their history), and reset anyone's password from the
same screen. Only people with the Admin/Super Admin permission see this
page at all.

---

The rest of this document is for developers working on VINCO itself.

## Architecture

One repository, two deployment targets, one source tree:

```
                        ┌─────────────────────────────┐
   Browser  ──────────▶ │  frontend (this repo's root) │
                        │  React / TanStack Start      │
   Tauri desktop ─────▶ │  src/, src-tauri/             │
                        └──────────────┬───────────────┘
                                       │ HTTPS (Bearer: Supabase JWT)
                                       ▼
                        ┌─────────────────────────────┐
                        │  backend/  (FastAPI)          │
                        │  deployed to Render           │
                        └──────────────┬───────────────┘
                                       │
                                       ▼
                        ┌─────────────────────────────┐
                        │  Supabase Postgres            │
                        │  `vinco` schema (app data)     │
                        │  `public` schema (Supabase      │
                        │   Auth/RBAC + legacy tables)   │
                        └─────────────────────────────┘
```

- **Web**: browser → this repo's frontend (deployed to Cloudflare Pages)
  → the FastAPI backend (Render) → Supabase Postgres. Employees see a
  VINCO-branded username/password login (`src/components/sign-in-card.tsx`,
  `src/lib/vinco-auth.ts`) — Supabase Auth still verifies the password
  underneath (see "Native login" below), but nothing Supabase-specific is
  ever shown to them.
- **Desktop**: the same frontend source, built as a Tauri shell → the
  same production FastAPI backend → the same Supabase Postgres. Auth is
  **currently still** automatic sign-in as a dedicated internal Supabase
  account (no browser, no OAuth) — see `DESKTOP_AUTH_MVP.md`. Migrating
  desktop to the same native VINCO login the web build now uses is a
  deliberate later step (not done automatically alongside adding native
  login), once that path is proven — see `DESKTOP_AUTH_MVP.md`'s
  migration note. Session storage is a local JSON file
  (`src-tauri/src/session_store.rs`), not the OS keychain — see that
  file's module doc for why.
- Both targets talk to the **same backend** and go through the **same**
  Supabase JWT verification and RBAC checks (`backend/app/api/deps.py`).
  Neither client has any special access the other doesn't.

### Native login and user management

Employees sign in with a VINCO username and password — no Supabase UI,
no OAuth, no browser redirect. Underneath, Supabase Auth still does the
real work (password verification, JWT issuance): a native account's
Supabase email is always `<username>@vinco.local`, a synthetic address
never shown to anyone and never reachable — see
`src/lib/vinco-auth.ts`/`backend/app/services/user_service.py`'s module
docs for the exact convention both sides share.

Creating an account, resetting a password, or (de)activating one are
admin-level operations no ordinary user token can perform — the backend
holds a Supabase **service-role key** for exactly this
(`backend/app/api/auth.py`'s `SupabaseAdmin`), used only by
`backend/app/api/routers/users.py`'s routes (`VISION_SUPABASE_SERVICE_ROLE_KEY`,
a Render secret, empty by default). RBAC enforcement itself is
completely unchanged — every request still goes through
`require_permission`/Supabase's own `can()`, gated behind the existing
`admin.users` (create/edit/deactivate) and `admin.roles` (change what a
user is allowed to do) permissions, not new ones.

VINCO's four role labels (Employee/Admin/Super User/Super Admin) map onto
Supabase's existing role set — Employee→`employee`, Admin→
`general_manager`, Super Admin→`super_admin`, all already-existing roles.
Super User needs one **optional, one-time, manual** SQL step
(`backend/scripts/native_auth_rbac.sql`, run once in the Supabase SQL
Editor) to become a real, independently-enforced role; until that's run,
assigning "Super User" fails with a clear error explaining exactly that.

## Repository layout

```
.
├── src/                 # Frontend: React, TanStack Start/Router, React Query
├── src-tauri/            # Tauri desktop shell (Rust)
├── backend/               # FastAPI backend + Alembic migrations
│   ├── app/                # Routers, services, models, RBAC deps
│   ├── migrations/          # Alembic migration chain
│   ├── app/tests/            # pytest suite (SQLite by default, real
│   │                           Postgres tests behind VISION_TEST_POSTGRES_URL)
│   └── render.yaml            # Render Blueprint config for this service
├── .github/workflows/
│   ├── desktop-build.yml    # Frontend TS/tests, web build, desktop build,
│   │                          Rust checks, Windows/macOS installer artifacts
│   └── backend-ci.yml       # Backend pytest (SQLite + real-Postgres jobs)
└── scripts/                # Build-time env-var checks (check-web-env.mjs,
                              check-desktop-env.mjs) and desktop build helpers
```

`backend/` was merged from the former standalone `vision-contracting-profit`
repository via `git subtree` — its full commit history is preserved and
browsable in this repo's log, not squashed or discarded.

## Running things

### Frontend (web)

```sh
bun install
cp .env.example .env   # fill in real values, see below
bun run dev             # http://localhost:8080
bun run build            # production web build (Cloudflare/Nitro target)
bun run test              # vitest
bunx tsc --noEmit          # typecheck
```

`bun run build` runs `scripts/check-web-env.mjs` first and **fails the
build** if `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, or
`VITE_API_URL` is missing — or, inside a real Cloudflare Pages build
specifically, if `VITE_API_URL` still points at `localhost`. This repo
has no `wrangler.toml`; the actual Cloudflare Pages project's build
command and env vars live entirely in the Cloudflare dashboard for that
project (Settings → Environment variables) — this check is what stops a
misconfigured dashboard from silently shipping `localhost:8000` as the
production API URL to every visitor's browser.

### Desktop (Tauri)

```sh
bun run tauri:dev          # dev shell against http://localhost:8080
bun run tauri:build         # release .app/.dmg/.exe (needs a Rust toolchain)
```

`bun run build:desktop` (called by `tauri:build`) runs
`scripts/check-desktop-env.mjs` first, which additionally requires
`VITE_DESKTOP_DEV_EMAIL` / `VITE_DESKTOP_DEV_PASSWORD` (the dedicated
internal Supabase account desktop auto-login uses — see
`DESKTOP_AUTH_MVP.md`).

### Rust (`src-tauri/`)

```sh
cd src-tauri
cargo check
cargo test
cargo build --release
```

### Backend

```sh
cd backend
pip install -e ".[dev]"       # add ",ocr" too for the full test suite to collect
alembic upgrade head        # SQLite by default (VISION_DATABASE_URL unset)
uvicorn app.api.main:create_app --factory --reload   # http://localhost:8000
python -m pytest -q          # full suite, SQLite
```

Real-Postgres-only tests (migration chain, dialect compatibility, a full
`/clients` CRUD round trip against a database built only by the
documented migration procedure) run behind an env var, against a
**disposable** database only:

```sh
export VISION_TEST_POSTGRES_URL="postgresql+psycopg://user:pass@localhost:5432/some_throwaway_db"
python -m pytest -q app/tests/test_postgres_compat.py app/tests/test_migrations.py app/tests/test_clients_api_against_real_postgres.py
```

## Database

- Production database is PostgreSQL (via Supabase). Local dev/tests
  default to SQLite unless `VISION_DATABASE_URL` is set.
- VINCO's own tables live in a dedicated `vinco` Postgres schema, isolated
  from Supabase's own `public` schema (which owns Auth/RBAC tables and
  pre-existing Lovable-era tables that collide by name with several of
  VINCO's own) — see `backend/app/core/config.py` and
  `backend/app/database/schema_isolation.py`.
- A **fresh** Postgres database must be initialized with
  `alembic stamp cb86207a716e && alembic upgrade head`, not a bare
  `alembic upgrade head` — see
  `backend/migrations/versions/926e160784a0_postgresql_baseline_schema.py`'s
  own docstring for why, and `backend/app/tests/test_migrations.py` for
  the regression test proving both the documented procedure and the
  naive one's failure mode.

## Environment variables

| Variable | Used by | Notes |
|---|---|---|
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_PUBLISHABLE_KEY` | frontend (web + desktop) | Same Supabase project both build targets use |
| `VITE_API_URL` | frontend (web + desktop) | The FastAPI backend's base URL. Web: set in Cloudflare Pages dashboard. Desktop: baked in at `tauri:build` time from `.env`. Never silently defaults to `localhost` in a real production build (see `scripts/check-web-env.mjs`) |
| `VITE_DESKTOP_DEV_EMAIL` / `VITE_DESKTOP_DEV_PASSWORD` | desktop only | The dedicated internal Supabase account desktop auto-login signs in as |
| `VISION_DATABASE_URL` | backend | Unset = local SQLite. Set = PostgreSQL (Render secret in production) |
| `VISION_SUPABASE_URL` / `VISION_SUPABASE_ANON_KEY` | backend | Verifies JWTs and checks permissions against this Supabase project |
| `VISION_SUPABASE_SERVICE_ROLE_KEY` | backend | Only used by the native user-management routes (`/users/*`) to create/edit Supabase Auth identities. A real secret — never commit a value, never expose to the frontend |
| `VISION_CORS_ALLOWED_ORIGINS` | backend | Comma-separated web origins. The desktop app's own fixed origins (`tauri://localhost`, `https://tauri.localhost`) are always allowed in code regardless of this value — see `backend/app/core/config.py` |
| `VISION_STAGING_SCHEMA` | backend | Defaults to `vinco` — the isolated Postgres schema name |

Never commit real values for any of these — `.env`/`.env.local` are
gitignored; `.env.example` documents the shape only.

## Deployment

- **Backend**: Render, Docker runtime, deploys from `backend/`
  (`backend/Dockerfile`, `backend/render.yaml`). See `backend/render.yaml`
  for the exact build/start command and required env vars.
- **Web frontend**: Cloudflare Pages, built from this repo's root
  (`bun run build`). Project config lives entirely in the Cloudflare
  dashboard, not in this repo.
- **Desktop**: built via `bun run tauri:build` (locally or in
  `.github/workflows/desktop-build.yml`'s CI matrix), producing unsigned
  `.dmg`/`.exe` installer artifacts — not auto-published anywhere.

## History note

This project was originally scaffolded with [Lovable](https://lovable.dev).
Some files still carry a `// This file is automatically generated. Do not
edit it directly.` header from that scaffold (e.g.
`src/integrations/supabase/client.ts`) — those specific files have since
had deliberate, documented hand edits layered on top (see the comment at
the top of each) for things Lovable's own generator doesn't know about,
like desktop session storage. The application itself is no longer
developed through the Lovable editor.
