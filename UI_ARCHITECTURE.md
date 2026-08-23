# UI Architecture — Vision Contracting Profit System (Phase 3)

This document describes the desktop UI built in Phase 3: how it's
structured, how it stays separated from business logic and the database,
and how financial figures actually reach the screen. It complements
`ARCHITECTURE.md` (overall system design) and `FINANCIAL_MODEL.md`
(the financial definitions the UI only ever displays, never computes).

## 1. Layering, restated for the UI

```
ui/            PySide6 widgets, dialogs, pages — presentation only
      |
services/      business logic, validation, orchestration (this phase adds
               client_service, quotation_service, cost_service,
               dashboard_service, lookup_service)
      |
core/          financial_engine.py — the only place profit/margin/variance
               formulas exist
      |
models/        SQLAlchemy ORM entities
      |
database/      engine, session, migrations
```

**The rule that matters most:** no `.py` file under `app/ui/` imports
`sqlalchemy` for querying beyond opening a `session_scope()` and calling a
service function, and no `.py` file under `app/ui/` computes a profit,
margin, or variance. Every financial number displayed anywhere in the UI
originates from a `ProjectFinancialSnapshot` or `EstimateAccuracyReport`
(both in `app/core/financial_engine.py`), built by
`app/services/financial_service.py`. `app/ui/formatting.py` only turns an
already-computed `Decimal`/`None` into a display string
(`"AED 1,000,000.00"`, `"—"` for unknown) — it never derives a number.

## 2. Navigation

```
MainWindow (app/ui/main_window.py)
├── Sidebar (persistent): Dashboard, Projects, Quotations, Costs, Analytics, Settings
└── QStackedWidget
    ├── DashboardPage
    ├── ProjectsListPage ──(double-click / +New)──> ProjectDetailPage (pushed onto the stack)
    │                                                 ├── Overview tab
    │                                                 ├── Quotations tab
    │                                                 ├── Estimated Costs tab
    │                                                 ├── Actual Costs tab
    │                                                 ├── Profitability tab
    │                                                 └── Documents tab (placeholder)
    ├── QuotationsPage (global, all projects)
    ├── CostsPage (project selector + the same cost widgets used in detail)
    ├── AnalyticsPage (placeholder)
    ├── SettingsPage ──(Manage Clients)──> ClientsPage
    └── ClientsPage
```

**Why Clients isn't in the primary sidebar:** the brief's primary
navigation list is Dashboard / Projects / Quotations / Costs / Analytics /
Settings — it doesn't include Clients. Client management is reached from
Settings instead, and every client-picking field (project creation,
quotation forms) has an inline "+ New Client" button
(`app/ui/widgets/client_selector.py`) so creating a client is never more
than one click away from where it's needed, without adding a seventh
sidebar item the brief didn't ask for.

**Why "Costs" exists as its own top-level page, given costs are inherently
project-scoped:** `CostsPage` is a thin project selector wrapped around
the exact same `EstimatedCostsWidget`/`ActualCostsWidget` used inside
`ProjectDetailPage`'s tabs — see §4. It exists because the brief's primary
navigation explicitly lists "Costs", but no cost logic is duplicated to
provide it.

**Project Detail as a pushed stack page, not a dialog:** `MainWindow`
keeps at most one `ProjectDetailPage` on the `QStackedWidget` at a time
(`open_project_detail` removes and deletes the previous one before adding
a new one), so switching between projects doesn't accumulate hidden
widgets. "Back to Projects" returns to `ProjectsListPage`, which refreshes
so any edits are reflected immediately.

## 3. Screen ↔ service mapping

| Screen | Backing service function(s) |
|---|---|
| Dashboard | `dashboard_service.build_dashboard_summary` |
| Projects list | `project_service.list_projects_with_snapshots` |
| Project create/edit | `project_service.create_project` / `update_project` |
| Project Overview tab | `financial_service.build_project_financial_snapshot` (+ plain Project fields) |
| Project/global Quotations | `quotation_service.*` (`create_quotation`, `create_quotation_revision`, `mark_submitted`, `mark_lost`, `mark_awarded`) |
| Estimated Costs tab | `cost_service.*` (`get_or_create_current_revision`, `add_estimated_cost_line`, `start_new_estimate_revision`, `mark_revision_final`, `remove_estimated_cost_line`) |
| Actual Costs tab | `cost_service.add_actual_cost` / `list_actual_costs` / `cost_by_category` |
| Profitability tab | `financial_service.build_project_financial_snapshot` (same call as Overview — see §4) |
| Clients | `client_service.*` |

No page queries a model directly; every page's `refresh()` calls exactly
one or two service functions inside a `session_scope()`, then hands
plain/Pydantic results to widgets.

## 4. One snapshot, two screens

`ProjectOverviewTab`'s "Financial Summary" section and the dedicated
`ProjectProfitabilityTab` both render the **same**
`app/ui/widgets/profitability_view.py::ProfitabilityView` widget, fed by
the same `build_project_financial_snapshot()` call. This was a deliberate
choice over building two separate layouts: the brief asks for financial
figures on both screens, and having one rendering path for a
`ProjectFinancialSnapshot` makes it structurally impossible for the two
screens to ever disagree about a number. If Overview ever needs a more
condensed view than Profitability, that's a display-density change to
`ProfitabilityView`, not a second data path.

## 5. How the dashboard gets its aggregates

`dashboard_service.build_dashboard_summary()` loads every non-deleted
project, builds each one's `ProjectFinancialSnapshot` (via
`list_projects_with_snapshots`), and then only **sums or averages
already-computed values** — see the module's docstring for the exact
null-handling rules (a project with nothing recorded contributes zero to a
*total*, but is *excluded* from an *average* margin, since 0% would be
numerically wrong for "not applicable"). No profit/margin formula is
re-derived at the portfolio level.

This is O(N) snapshot builds for N projects, each snapshot itself being a
handful of targeted, indexed queries scoped by `project_id` — not a single
giant join, and not N² anything. At the scale a single contracting
company's project list actually reaches, this is simple, obviously
correct, and fast enough; it is the one place in this phase where
"correct and simple" was chosen over "fewest possible queries." If a future
phase needs this to scale further, the fix is a batched/materialized
aggregate query layer — not a change to how any individual figure is
computed.

## 6. Estimate revision history in the UI

`EstimatedCostsWidget` (`app/ui/costs/estimated_costs_widget.py`) is the
piece of UI most directly shaped by the estimating-accuracy requirement
from the last review round:

- A revision picker lets the user browse **Original**, any **previous**
  revision, and the **Current** one — all read from real
  `EstimateRevision` rows, never inferred.
- **Add Line** / **Remove Line** are only enabled while viewing the
  *current* (latest) revision. Selecting a historical revision switches
  the table to read-only automatically — this is what actually prevents
  "accidentally overwriting historical estimate records," not just a
  database constraint the UI could route around.
- **Start New Revision** calls `cost_service.start_new_estimate_revision`,
  which copies the current revision's lines forward as new rows (so
  re-estimating doesn't mean re-typing everything) and makes the old
  revision permanently read-only history.
- **Mark as Final Estimate** sets the `is_final` flag used by
  `get_final_estimate_revision` for estimating-accuracy reporting
  (`FINANCIAL_MODEL.md` §14).

## 7. Money input, not `QDoubleSpinBox`

`app/ui/widgets/money_field.py::MoneyLineEdit` is a validated `QLineEdit`
(regex-constrained to at most 2 decimal places) that parses straight to
`Decimal`, never `float`. Qt's `QDoubleSpinBox` is backed by a C `double`
— using it anywhere in this application would reintroduce the exact
binary-floating-point risk `app/core/money.py` exists to rule out. Every
money-entry field in every dialog uses `MoneyLineEdit`.

## 8. Error handling

`app/ui/errors.py::run_guarded` (a function wrapper) and `guard` (a
context-manager form) are the only two ways a page/dialog should call into
the service layer for a database-writing action. They translate:

- `app.services.errors.ValidationError` → an inline `QMessageBox.warning`
  with the exact message the service raised (these are expected,
  user-correctable conditions — not logged as errors).
- `sqlalchemy.exc.SQLAlchemyError` → a generic friendly dialog, full
  exception logged via `app/ui/logging_setup.py`.
- anything else → the same generic friendly dialog, also logged with a
  full traceback (`logger.exception`).

No raw exception or traceback is ever shown in a dialog. See
`app/ui/logging_setup.py` for the rotating file handler
(`logs/app.log`, git-ignored) — logs never include full financial payloads
or credentials, only enough context (which action failed) to diagnose.

## 9. Semantic labels instead of color-only status

`app/ui/variance_labels.py` maps a variance's sign to the *correct*
semantic label given what that particular figure means — a positive cost
variance is "Over Estimate" (unfavorable), while a positive profit
variance is "Above Target" (favorable). `app/ui/widgets/status_badge.py`
renders these as a labeled chip with color as a secondary cue, never the
only cue — satisfying "don't rely on color alone" directly rather than by
convention.

## 10. Reference data vs. sample data

Two different seeding mechanisms exist, and only one runs automatically:

- `app/database/seed.py::seed_default_cost_categories` — plain reference
  data (Materials, Labour, Subcontractors, ...) the cost-entry forms need
  a category list to function at all. `app/ui/main.py` calls this on
  every startup; it is fully idempotent (checks by name) and never touches
  projects, clients, or financial figures, so it is safe to run against a
  real database.
- `app/database/dev_seed_data.py` — fabricated projects (`[DEV] ...`
  prefixed names, a `(DEV DATA)`-tagged client) for manually exercising
  the UI: one under-budget project, one over-budget project, and one
  never-awarded quotation. This is **never imported by `app.ui.main`** and
  must be run explicitly (`python -m app.database.dev_seed_data`) — it is
  a development tool, not part of the application.

## 11. Known limitations (Phase 3)

- **Multi-currency portfolio rollups**: the dashboard formats every total
  as if the whole portfolio shares one currency (AED). Per-project figures
  correctly use that project's own currency; the existing one-currency-
  per-project convention (`FINANCIAL_MODEL.md` §4.3) isn't yet extended
  with an explicit multi-currency dashboard view.
- **`estimated_cost` in the live snapshot always reflects the current
  revision** — there is no "show me the estimate as it stood at Revision
  2" view on the Overview/Profitability tabs (that history is fully
  preserved and viewable, just on the Estimated Costs tab's revision
  picker, not surfaced into the profitability comparison itself).
- **No inline table editing**: adding/removing a cost line uses a dialog
  rather than editing table cells directly — simpler and safer for Phase
  3, at some cost to data-entry speed for bulk entry.
- **Documents tab is a placeholder**, as scoped — Google Drive integration
  is a later phase.
- **No automated GUI tests** (e.g. `pytest-qt`) — Phase 3 testing covers
  the full service layer (validation, business rules, aggregation) with
  real unit/integration tests, plus scripted end-to-end verification
  driving the actual dialog/widget code during development (see the PR
  description for what was exercised). Widget-level automated tests are a
  reasonable Phase 4 addition once the screens stabilize.
