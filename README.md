# Vision Contracting Profit System

A private business application for Vision Contracting Company to manage
construction projects, quotations and BOQs, and to track estimated vs.
actual costs and profitability across projects, clients, trades and cost
categories.

This repository has completed **Phase 2: the financial/project accounting
engine** — a deterministic service that aggregates a project's quotations,
variations, costs, invoices, and payments into a complete profitability
snapshot (see `FINANCIAL_MODEL.md`), built on the Phase 1 foundation
(database schema, module structure). There is still no full UI, no AI
integration, no Google OAuth, no document importing, and no quotation
generation. See `ARCHITECTURE.md`, `DATABASE_SCHEMA.md`, and
`FINANCIAL_MODEL.md` for the design, and "Roadmap" below for what comes
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

The test suite focuses on the financial calculation engine
(`app/core/financial_engine.py`) and the database-backed aggregation
service (`app/services/financial_service.py`), which are the parts of the
system that must be provably correct.

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

## Launching the (placeholder) desktop shell

```bash
python -m app.ui.main
```

This opens a minimal PySide6 window that connects to the database and
displays a project count, purely to prove the UI → services → database
seam works. It is not the product UI.

## Project layout

See `ARCHITECTURE.md` for the full explanation. Short version:

```
app/
    core/          money/currency types, the financial calculation engine
    database/      SQLAlchemy engine, session, Base, init_db, seed data
    models/        SQLAlchemy ORM entities
    services/      business logic — financial_service.py builds a
                   ProjectFinancialSnapshot from the database
    integrations/  external systems behind interfaces (Google Drive today)
    analytics/     profitability analysis (Phase 3+)
    importers/     historical document import interfaces (Phase 3+)
    ui/            PySide6 desktop app (placeholder shell today)
    reports/       report generation (Phase 3+)
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

- Phase 3: profitability analytics/dashboards, document importers
  (PDF/Excel/Word), full PySide6 UI, report generation.
- Phase 4: Google Drive OAuth + live sync.
- Phase 5: AI-assisted analysis over historical estimating/profitability
  data (read-only with respect to financial figures).

## Open decisions before Phase 3

- Multi-currency FX conversion: still explicitly out of scope. All figures
  rolled into one project's snapshot must share a currency (see
  `FINANCIAL_MODEL.md` / `DATABASE_SCHEMA.md` §4.3).
- Trade taxonomy and supplier vs. subcontractor fields: unchanged open
  question from Phase 1.
- Whether the UI needs a "freeze the quote-time cost estimate" view, given
  `ProjectFinancialSnapshot.estimated_cost` always reflects the *current*
  best estimate rather than a historical snapshot per revision (see
  `FINANCIAL_MODEL.md` §7).
