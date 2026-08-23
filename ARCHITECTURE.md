# Architecture — Vision Contracting Profit System

Status: **Phase 1 — Foundation**. This document describes the architecture
established in this phase. No UI, AI, OAuth, or importer logic is implemented
yet; only the structure they will plug into.

## 1. Goals of this phase

- A modular, testable Python project skeleton.
- A normalized SQLite schema that can represent the full quote-to-cash and
  estimate-vs-actual lifecycle of a construction project.
- A deterministic, unit-tested financial calculation engine — because profit
  figures drive real business decisions and must never depend on an LLM.
- Clean seams (interfaces) for the two subsystems that will be built later
  and are the riskiest to bolt on afterwards: Google Drive integration and
  document importing (PDF/Excel/Word).

## 2. Layering

The codebase is organized so that each layer only depends on the layers
below it. Nothing in `database/` or `models/` imports from `ui/`; nothing in
`ui/` talks to SQLAlchemy directly.

```
ui/            PySide6 desktop UI (presentation only)
      |
reports/       Report generation (reads data via services, no business logic)
      |
analytics/     Aggregation & profitability analysis (pandas-based, read-only)
      |
services/      Business logic / use-cases, orchestrates models + integrations
      |
importers/     Document ingestion interfaces (PDF/Excel/Word -> structured data)
integrations/  External systems behind interfaces (Google Drive, later AI)
      |
models/        SQLAlchemy ORM entities (the schema, as Python objects)
      |
database/      Engine, session management, Base, migrations
      |
core/          Framework-agnostic domain logic: money, currency, the
               financial calculation engine, shared enums/exceptions.
```

`core/` has no dependency on SQLAlchemy, Qt, or pandas. It is pure Python +
Pydantic, which is what makes the financial engine trivially unit-testable
and safe to reuse from the UI, a script, a report, or (later) an API.

### Directory layout

```
app/
    core/            money/currency types, financial calculation engine,
                     shared enums, exceptions, settings
    database/        engine, session factory, declarative Base, init_db
    models/          SQLAlchemy models, one module per domain area
    services/        business logic (project service, quotation service, ...)
    integrations/    GoogleDriveService interface + stub implementation
    analytics/       profitability analysis built on pandas (Phase 2+)
    importers/       BaseImporter interface + format-specific stubs
    ui/              PySide6 application shell (Phase 2+ for full UI)
    reports/         report generation (Phase 3+)
    tests/           pytest suite
migrations/          Alembic migration scripts
```

This matches the structure requested in the brief. `services/`,
`analytics/`, `reports/` and most of `ui/` are intentionally near-empty in
this phase — only enough exists to prove the seams work end to end (a
window that opens, a session that connects to the database).

## 3. Technology choices and rationale

| Concern | Choice | Why |
|---|---|---|
| Language runtime | Python 3.12+ | Modern typing features (`X \| None`, `StrEnum`), long support window |
| Database | SQLite | Single-file, zero-ops, native to a per-machine macOS desktop app; trivial to back up (copy the file) |
| ORM | SQLAlchemy 2.0 (typed, `Mapped[...]` style) | Mature, explicit, keeps SQL under our control for a financial system (no hidden magic) |
| Migrations | Alembic | The brief requires "no destructive migration of existing financial records" — that's exactly what versioned, reviewable migrations give us over ad-hoc `create_all` |
| Validation / DTOs | Pydantic v2 | Fast, typed, integrates with the settings module (`pydantic-settings`) |
| Desktop UI | PySide6 | Native, LGPL, mature; matches the "run natively on macOS" requirement |
| Data analysis | pandas | Standard for the multi-year / multi-dimension profitability analysis in Phase 2+ |
| Excel/BOQ | openpyxl | Reads/writes `.xlsx`, the near-universal BOQ format |
| PDF extraction | PyMuPDF (`fitz`) | Fast, reliable text/table extraction for historical quotations |
| Google Drive | `google-api-python-client` + `google-auth*` | Official Google client libraries, isolated behind our own interface |
| Testing | pytest | Standard, minimal ceremony |

No web framework, task queue, or ORM-agnostic abstraction layer has been
added — there is exactly one consumer (the desktop app) and one database
engine (SQLite), so an abstraction over "which database" or "which
transport" would be speculative complexity the brief explicitly warns
against.

## 4. The financial model (`app/core/financial_engine.py`)

This is the most important design decision in the codebase, so it gets its
own section.

**Principle: AI is never the authority for a financial number.** Every
figure in the system that feeds a profit or margin calculation is either:

1. Entered directly by a user (quoted value, cost line, invoice amount), or
2. Computed by a pure, deterministic Python function over those inputs.

There is no code path where a language model output is summed, averaged, or
otherwise used as a financial figure. When AI analysis is added in a later
phase, it will consume the *outputs* of this engine (read-only) to generate
commentary — it will never write to cost/revenue tables or replace this
engine's arithmetic.

The engine distinguishes nine figures, exactly as specified in the brief:

| Figure | Definition |
|---|---|
| Quoted revenue | Total value of the submitted quotation (BOQ total) |
| Estimated cost | Sum of estimated cost line items for the project |
| Estimated profit | `quoted_value - estimated_cost` |
| Contract / awarded value | The value actually agreed once a quotation is won (may differ from quoted value after negotiation) |
| Actual cost | Sum of actual cost line items recorded during execution |
| Actual revenue | Contract value plus net approved variations (what the company is actually entitled to bill for) |
| Actual profit | `actual_revenue - actual_cost` |
| Estimated margin | `estimated_profit / quoted_value * 100` |
| Actual margin | `actual_profit / actual_revenue * 100` |

All monetary values use `decimal.Decimal`, never `float` — see `app/core/money.py`.
Division guards against `None` and `0` denominators and returns `None`
(not `0` and not an exception) when a margin is undefined, so "no revenue
recorded yet" is never silently displayed as "0% margin".

### `Money` and currency

`app/core/money.py` defines a small `Money` value object: a `Decimal`
amount paired with a `Currency` code. Every monetary column in the database
is stored with an explicit currency column next to it (see
`DATABASE_SCHEMA.md`) rather than assuming a single global currency. The
default currency for new records is **AED**, but nothing in the schema or
engine hard-codes it — `Currency` is an open string-backed enum of common
codes plus free-form ISO-4217 codes, so adding a new currency is a data
change, not a schema migration.

The engine deliberately does **not** perform currency conversion. Comparing
or summing amounts across different currencies is a business decision
(which FX rate? which date?) that belongs in a future, explicit
`FXConversionService`, not silently inside profit arithmetic.

## 5. Database access (`app/database/`)

- `base.py` — the single shared `DeclarativeBase` all models inherit from,
  plus shared mixins (`TimestampMixin`, `SoftDeleteMixin`).
- `session.py` — engine creation (`sqlite:///...`, `PRAGMA foreign_keys=ON`)
  and a `session_scope()` context manager. This is the only place that
  knows the database URL.
- `init_db.py` — creates a fresh database from the models (used by tests
  and first-run setup). It does **not** replace Alembic for an existing
  database with real data; see below.

### Migration strategy

Alembic is used from day one, even though the schema will only be
`create_all`'d for fresh/test databases right now:

- `migrations/env.py` points at `app.database.base.Base.metadata` for
  autogeneration.
- Every future schema change ships as a reviewed migration script, never as
  an in-place `ALTER` or a dropped/recreated table.
- Migrations are additive by default (add nullable columns/tables). A
  column that must become `NOT NULL` gets a two-step migration (add
  nullable + backfill, then constrain) so existing financial rows are never
  dropped or rewritten destructively.
- Soft deletion (`is_deleted`, `deleted_at`) is used for business records
  that a user can "remove" (projects, quotations, cost lines, invoices) so
  a mistaken deletion never destroys audit history. Hard deletes are
  reserved for genuinely disposable data (e.g. a cached Drive file listing).

## 6. Google Drive integration (`app/integrations/google_drive.py`)

Only an interface exists in this phase:

```python
class GoogleDriveService(Protocol):
    def authenticate(self) -> None: ...
    def list_files(self, folder_id: str) -> list[DriveFile]: ...
    def search_files(self, query: str) -> list[DriveFile]: ...
    def download_file(self, file_id: str, destination: Path) -> Path: ...
    def upload_file(self, source: Path, folder_id: str) -> DriveFile: ...
```

A `NullGoogleDriveService` stub implements this by raising
`NotImplementedError`, so services can depend on the interface today and
get a real implementation swapped in later without any call-site changes.
Google Drive is treated purely as **document storage**: the
`GoogleDriveDocument` table stores a reference (`drive_file_id`, name, link,
mime type, which project/quotation/invoice it belongs to) — never the
document content and never financial figures extracted from it without
going through the normal data-entry/import path.

## 7. Historical document importers (`app/importers/`)

Only an interface exists in this phase:

```python
class BaseImporter(ABC):
    def parse(self, path: Path) -> ImportResult: ...
```

`ImportResult` is a Pydantic model (project/quotation/BOQ line candidates +
warnings), so any future `PdfQuotationImporter`, `ExcelBoqImporter`, or
`WordQuotationImporter` produces the same shape of output regardless of
source format, and importing is always a reviewable staging step (produce
`ImportResult` → user reviews → services layer persists it) rather than a
direct write to the database.

## 8. Backups

Because the database is a single SQLite file, backup is architecturally
simple: `app/database/session.py` exposes the resolved database file path,
and a (not-yet-implemented) `app/services/backup_service.py` will do a
consistent file copy (`sqlite3 .backup` API, not a raw `cp`, to be safe
against concurrent writes). This phase only documents the approach; no
backup code is implemented yet, per the brief.

## 9. What is explicitly deferred

- Google OAuth flow and real Drive API calls.
- Any AI/LLM integration.
- Quotation/report generation.
- The full PySide6 dashboard (only a placeholder shell exists).
- Multi-currency FX conversion.
- Multi-user/auth (this is a single-user desktop app for now).

## 10. Decisions to confirm before Phase 2

See the summary at the end of the task for the open questions (e.g.
supplier vs. subcontractor modeling, how "actual revenue" should be derived
from invoices vs. contract value, trade taxonomy) that should be confirmed
with the business before deeper implementation.
