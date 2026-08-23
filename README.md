# Vision Contracting Profit System

A private business application for Vision Contracting Company to manage
construction projects, quotations and BOQs, and to track estimated vs.
actual costs and profitability across projects, clients, trades and cost
categories.

This repository has completed **Phase 4: local document import and
review** — pick quotation/BOQ files (PDF, Excel, Word, CSV/text, images)
from your computer, review deterministically extracted candidate data, and
confirm before anything is written to the business database. This builds
on **Phase 3's** desktop UI (Dashboard, Projects, Quotations, Costs,
Profitability), the Phase 2 financial engine (see `FINANCIAL_MODEL.md`),
and the Phase 1 foundation (database schema, module structure). There is
still no Google Drive/OAuth integration, no AI, and no production
packaging (`.app`/DMG). See `ARCHITECTURE.md`, `DATABASE_SCHEMA.md`,
`FINANCIAL_MODEL.md`, `UI_ARCHITECTURE.md`, and `IMPORT_ARCHITECTURE.md`
for the design, and "Roadmap" below for what comes next.

## Requirements

- Python 3.12+
- macOS or Windows (both are first-class target platforms as of Phase 4 —
  see `IMPORT_ARCHITECTURE.md` §14) — development also works on Linux,
  since PySide6/SQLite/the document-import libraries are all
  cross-platform.

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
(`app/services/financial_service.py`), the Phase 3 service layer
(`client_service`, `project_service`, `quotation_service`, `cost_service`,
`dashboard_service`) — validation rules, business rules (e.g. a lost
quotation never sets a contract value, an estimate revision's history is
never mutated), and aggregation — and the Phase 4 document-import pipeline
(every importer in `app/importers/`, `app/core/import_normalization.py`,
`app/core/import_extraction.py`, `app/services/import_service.py`,
`app/services/import_matching.py`): file-type detection, hashing/duplicate
detection, extraction for every supported format, normalization
(including the explicit "don't guess an ambiguous number" rule), staging,
review/edit, project/client matching, and confirm/reject. Test fixtures
are small synthetic files generated at test time (see
`IMPORT_ARCHITECTURE.md` for why `.xlsb` is tested via a mocked reader
rather than a real binary fixture) — no real company documents are ever
committed. The UI layer itself (`app/ui/`) doesn't have automated widget
tests yet — see `UI_ARCHITECTURE.md` §11 — but was verified by scripted
end-to-end runs driving the real dialogs and pages during development.

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

This launches the full application: a persistent sidebar (Dashboard,
Projects, Quotations, Costs, Imports, Analytics, Settings), project
creation and detail (Overview / Quotations / Estimated Costs / Actual
Costs / Profitability / Documents tabs), client management (via
Settings → Manage Clients), and the Phase 4 Import Center. On first run it
automatically seeds the default cost-category reference data (Materials,
Labour, Subcontractors, ...) — see `UI_ARCHITECTURE.md` §10 for why that's
safe to do automatically while fabricated *sample projects* are not.

Application logs are written to `logs/app.log` (git-ignored, rotating).

### Importing local documents

From the **Imports** tab, click **Import Documents** to pick one or more
local files (PDF, `.xlsx`/`.xlsm`/`.xlsb`/`.xls`, `.docx`, `.csv`/`.txt`,
or an image). Each file is:

1. Staged as-is — the original file is never moved, copied, or modified.
2. Hashed (SHA-256); if the exact same file was already imported, you're
   asked whether to import it again rather than silently duplicating or
   silently blocking it.
3. Run through a deterministic parser for its format (never AI, never a
   network call) to produce candidate quotation/BOQ data.

Click **Review** on any staged document to see what was extracted, edit
any field, see suggested existing clients/projects, and either **Confirm
Import** (after a final summary step) or **Reject** it. Nothing reaches
`Client`/`Project`/`Quotation`/`BOQ` until you explicitly confirm — and
confirming a quotation import never marks a project as awarded or records
actual cost; those remain separate, explicit steps on the Quotations/Costs
screens, exactly as if the data had been typed in by hand. See
`IMPORT_ARCHITECTURE.md` for the full pipeline and every extraction/
normalization rule.

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
    core/          money/currency types, the financial calculation engine,
                   import_normalization.py + import_extraction.py (pure,
                   deterministic candidate-data extraction, see
                   IMPORT_ARCHITECTURE.md)
    database/      SQLAlchemy engine, session, Base, init_db, seed data,
                   dev_seed_data.py (optional, dev-only sample projects)
    models/        SQLAlchemy ORM entities, incl. import_staging.py
                   (ImportedDocument + candidate/audit-log staging tables)
    services/      business logic — project/client/quotation/cost_service
                   for CRUD + validation; financial_service.py and
                   dashboard_service.py build read-only financial views;
                   import_service.py + import_matching.py drive the local
                   document import pipeline
    integrations/  external systems behind interfaces (Google Drive today)
    analytics/     profitability analysis (future phase)
    importers/     PDF/Excel/XLSB/Word/CSV/text/image document importers
                   — see IMPORT_ARCHITECTURE.md for the full list
    ui/            PySide6 desktop application — see UI_ARCHITECTURE.md
                   for the full screen map and UI/service boundary
    reports/       report generation (future phase)
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

- Phase 5: Google Drive OAuth + live sync (using `ImportedDocument`'s
  already-present `source_type`/`GOOGLE_DRIVE` distinction), AI-assisted
  extraction as a reviewed aid on top of the Phase 4 deterministic
  pipeline, report generation, quotation document generation,
  cross-project analytics/dashboards beyond the current portfolio
  summary.
- AI-assisted analysis over historical estimating/profitability data
  (read-only with respect to financial figures) — a later phase, after
  Drive integration.
- Production packaging (`.app` bundle / DMG / `.exe` installer) once the
  application stabilizes further.

## Open decisions before the next phase

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
  screens stabilize — see `UI_ARCHITECTURE.md` §11.
- Moving `run_extraction` onto a background worker if/when document
  volumes make synchronous extraction noticeably block the UI — see
  `IMPORT_ARCHITECTURE.md` §16.
- Whether BOQ category/trade text should get smarter (fuzzy) matching to
  existing `Trade` records, beyond today's exact-name match — see
  `IMPORT_ARCHITECTURE.md` §16.
