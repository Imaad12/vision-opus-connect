# Vision Contracting Profit System

A private business application for Vision Contracting Company to manage
construction projects, quotations and BOQs, and to track estimated vs.
actual costs and profitability across projects, clients, trades and cost
categories.

This repository has completed **Phase 3: the first usable native desktop
application** — a PySide6 UI (Dashboard, Projects, Quotations, Costs,
Profitability) built on the Phase 2 financial engine (see
`FINANCIAL_MODEL.md`) and the Phase 1 foundation (database schema, module
structure). There is still no Google Drive/OAuth integration, no AI, no
document importing, and no production packaging (`.app`/DMG). See
`ARCHITECTURE.md`, `DATABASE_SCHEMA.md`, `FINANCIAL_MODEL.md`, and
`UI_ARCHITECTURE.md` for the design, and "Roadmap" below for what comes
next.

## Requirements

- Python 3.12+
- macOS (target platform for the eventual desktop app) — development also
  works on Linux, since PySide6/SQLite are cross-platform.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the tests

```bash
pytest
```

The test suite covers the financial calculation engine
(`app/core/financial_engine.py`), the database-backed aggregation service
(`app/services/financial_service.py`), and the Phase 3 service layer
(`client_service`, `project_service`, `quotation_service`, `cost_service`,
`dashboard_service`) — validation rules, business rules (e.g. a lost
quotation never sets a contract value, an estimate revision's history is
never mutated), and aggregation. The UI layer itself (`app/ui/`) doesn't
have automated widget tests yet — see `UI_ARCHITECTURE.md` §11 — but was
verified by scripted end-to-end runs driving the real dialogs and pages
during development.

## Creating a local database

```bash
python -m app.database.init_db
```

This creates `vision_contracting.db` (SQLite) in the project root using the
current SQLAlchemy models. For an existing database with real data, use
Alembic migrations instead (see below) — `init_db` is for fresh/dev/test
databases only.

## Migrations

Schema changes are managed with Alembic so that existing financial data is
never dropped or rewritten in place:

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

## Launching the desktop application

```bash
python -m app.ui.main
```

This launches the full Phase 3 application: a persistent sidebar
(Dashboard, Projects, Quotations, Costs, Analytics, Settings), project
creation and detail (Overview / Quotations / Estimated Costs / Actual
Costs / Profitability / Documents tabs), and client management (via
Settings → Manage Clients). On first run it automatically seeds the
default cost-category reference data (Materials, Labour, Subcontractors,
...) — see `UI_ARCHITECTURE.md` §10 for why that's safe to do
automatically while fabricated *sample projects* are not.

Application logs are written to `logs/app.log` (git-ignored, rotating).

### Optional: development sample data

To manually exercise the UI with a few realistic projects (one under
budget, one over budget, one lost quotation), run:

```bash
python -m app.database.dev_seed_data
```

This is a development-only tool — it is never imported by `app.ui.main`
and never runs automatically. All rows it creates are clearly named
(`[DEV] ...` project names, a `(DEV DATA)`-tagged client) so they're easy
to distinguish from real business data and safe to delete.

## Project layout

See `ARCHITECTURE.md` for the full explanation. Short version:

```
app/
    core/          money/currency types, the financial calculation engine
    database/      SQLAlchemy engine, session, Base, init_db, seed data,
                   dev_seed_data.py (optional, dev-only sample projects)
    models/        SQLAlchemy ORM entities
    services/      business logic — project/client/quotation/cost_service
                   for CRUD + validation; financial_service.py and
                   dashboard_service.py build read-only financial views
    integrations/  external systems behind interfaces (Google Drive today)
    analytics/     profitability analysis (Phase 4+)
    importers/     historical document import interfaces (Phase 4+)
    ui/            PySide6 desktop application — see UI_ARCHITECTURE.md
                   for the full screen map and UI/service boundary
    reports/       report generation (Phase 4+)
    tests/         pytest suite
migrations/        Alembic migration scripts
```

## Design principles carried through every phase

1. **Financial calculations are deterministic Python/SQL, never AI.** AI
   will eventually analyze this data, but it never computes or overwrites a
   cost, revenue, or margin figure.
2. **Estimated and actual figures are always kept separate** — never
   merged into a single "cost" column — so estimate-vs-actual comparison is
   always possible.
3. **Money is `Decimal`, with an explicit currency on every amount.**
4. **UI never talks to the database directly.** It calls into `services/`,
   which uses `models/` and `database/`.
5. **No destructive migrations.** Schema changes are additive and
   reviewed; user-facing deletion is soft deletion.

## Roadmap (not yet built)

- Phase 4: Google Drive OAuth + live sync, document importers (PDF/Excel/
  Word), report generation, quotation document generation, cross-project
  analytics/dashboards beyond the current portfolio summary.
- Phase 5: AI-assisted analysis over historical estimating/profitability
  data (read-only with respect to financial figures).
- Production packaging (`.app` bundle / DMG) once the application
  stabilizes further.

## Open decisions before Phase 4

- Multi-currency FX conversion: still explicitly out of scope. All figures
  rolled into one project's snapshot — and the dashboard's portfolio
  totals — assume a single currency (see `FINANCIAL_MODEL.md` /
  `DATABASE_SCHEMA.md` §4.3, `UI_ARCHITECTURE.md` §11).
- Trade taxonomy and supplier vs. subcontractor fields: unchanged open
  question from Phase 1.
- Whether the Overview/Profitability views should ever surface a
  historical revision's estimate for comparison, beyond the read-only
  browser already on the Estimated Costs tab (see `UI_ARCHITECTURE.md`
  §11 and `FINANCIAL_MODEL.md` §7).
- Automated GUI testing (e.g. `pytest-qt`) for the widget layer, once the
  Phase 3 screens stabilize — see `UI_ARCHITECTURE.md` §11.
