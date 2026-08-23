# Database Schema — Vision Contracting Profit System

Database engine: **SQLite**, accessed exclusively through the SQLAlchemy
models in `app/models/`. This document is the human-readable companion to
those models — if they ever disagree, the code is authoritative and this
file should be updated.

Conventions used throughout:

- Every table has an integer primary key `id`.
- Every table has `created_at` / `updated_at` timestamps (`TimestampMixin`).
- Business tables that a user can delete use soft deletion: `is_deleted`,
  `deleted_at` (`SoftDeleteMixin`) instead of a real `DELETE`.
- Every monetary column is paired with a `currency` column
  (`Currency`, default `AED`) and stored as `Decimal` (`Numeric(14, 2)`).
- Foreign keys use `ON DELETE RESTRICT` by default to protect financial
  history; a few genuinely optional/dependent links use `SET NULL` (noted
  below).

## 1. Entity overview

```
Company ──< Project >── Client
                │
                ├──< ProjectStatusHistory
                ├──< ProjectVariation
                ├──< Quotation ──< QuotationVersion ──1:1── BOQ ──< BOQLineItem >── Trade
                │                                                                 └── CostCategory
                ├──< EstimatedCost >── CostCategory
                │                   └── Trade
                ├──< ActualCost >── CostCategory
                │                └── Trade
                │                └── Vendor
                ├──< Invoice >── Client / Vendor
                │             └──< Payment
                └──< GoogleDriveDocument
```

`Vendor` unifies suppliers and subcontractors (see §3.9 for the reasoning).

## 2. The financial model, at the schema level

The nine figures from the brief map onto stored data plus the deterministic
engine in `app/core/financial_engine.py` like this:

| Figure | Source |
|---|---|
| Quoted revenue | `QuotationVersion.quoted_value` (denormalized total of its `BOQLineItem`s, kept in sync by the service layer) |
| Estimated cost | `SUM(EstimatedCost.amount)` for the project's current estimate |
| Estimated profit | **Computed**, never stored: `quoted_value - estimated_cost` |
| Contract / awarded value | `Project.contract_value` (+ currency), set when a `QuotationVersion` is marked `WON` |
| Actual cost | `SUM(ActualCost.amount)` for the project |
| Actual revenue | **Computed**: `Project.contract_value + SUM(ProjectVariation.approved_value_change WHERE status=APPROVED)` |
| Actual profit | **Computed**: `actual_revenue - actual_cost` |
| Estimated margin | **Computed**: `estimated_profit / quoted_value * 100` |
| Actual margin | **Computed**: `actual_profit / actual_revenue * 100` |

Nothing computed is stored as a column. Storing derived financial figures
invites drift between the stored value and its inputs; the engine
recomputes them on demand from the rows above.

## 3. Entities

### 3.1 Company

Represents a legal entity of Vision Contracting itself (supports the
possibility of multiple group entities later; today there will typically be
exactly one row).

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| name | str, required | |
| legal_name | str, nullable | |
| trade_license_number | str, nullable | |
| default_currency | Currency, default `AED` | |
| address | str, nullable | |
| notes | text, nullable | |

### 3.2 Client

The customer awarding contracts.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| name | str, required, indexed | |
| contact_name | str, nullable | |
| contact_email | str, nullable | |
| contact_phone | str, nullable | |
| address | str, nullable | |
| notes | text, nullable | |

### 3.3 Trade

Lookup table for classifying work (Electrical, Plumbing, Civil, Joinery...).
Used by `BOQLineItem`, `EstimatedCost` and `ActualCost` so profitability can
be sliced "by trade" per the brief.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| name | str, required, unique | |
| code | str, nullable, unique | short code, e.g. `ELEC` |

### 3.4 CostCategory

Lookup table for cost classification (Labor, Material, Equipment,
Subcontract, Overhead, ...). Self-referencing `parent_id` allows grouping
(e.g. "Skilled Labor" under "Labor") without a separate hierarchy table.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| name | str, required | |
| code | str, nullable, unique | |
| parent_id | FK → CostCategory.id, nullable | |

### 3.5 Project

The central entity.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| company_id | FK → Company.id, required | who is executing the project |
| client_id | FK → Client.id, required | |
| name | str, required | |
| project_code | str, nullable, unique | internal reference number |
| primary_trade_id | FK → Trade.id, nullable | |
| status | ProjectStatus enum, required, default `LEAD` | current status (see §4) |
| tender_submission_date | date, nullable | |
| award_date | date, nullable | |
| start_date | date, nullable | |
| planned_completion_date | date, nullable | |
| actual_completion_date | date, nullable | |
| defects_liability_end_date | date, nullable | |
| contract_value | Numeric(14,2), nullable | set once awarded |
| contract_currency | Currency, default `AED` | |
| winning_quotation_version_id | FK → QuotationVersion.id, nullable, `SET NULL` | which version was awarded |
| notes | text, nullable | |

`ProjectDates` from the brief is realized as columns on `Project` rather
than a separate table — they are a fixed, well-known set of milestones per
project, not an open-ended collection, so a child table would only add
joins without adding flexibility.

### 3.6 ProjectStatusHistory

Audit trail of status changes (the brief lists "Project status" as its own
entity; this table is what makes status auditable rather than just a
mutable column).

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| project_id | FK → Project.id, required | |
| status | ProjectStatus enum, required | |
| changed_at | datetime, required, default now | |
| changed_by | str, nullable | user identifier |
| note | text, nullable | |

### 3.7 Quotation / QuotationVersion

A `Quotation` is the umbrella for a tender opportunity on a project; a
project can have more than one `Quotation` (e.g. re-tendered after a gap).
Each `Quotation` has one or more `QuotationVersion` rows — every revision
before/after submission is preserved (never overwritten) for audit and
estimating-history analysis.

**Quotation**

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| project_id | FK → Project.id, required | |
| reference_number | str, nullable, unique | |
| title | str, nullable | |

**QuotationVersion**

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| quotation_id | FK → Quotation.id, required | |
| version_number | int, required | monotonically increasing per quotation |
| status | QuotationStatus enum, required, default `DRAFT` | |
| quoted_value | Numeric(14,2), nullable | denormalized sum of its BOQ line items |
| currency | Currency, default `AED` | |
| issued_date | date, nullable | |
| valid_until | date, nullable | |
| notes | text, nullable | |

Unique constraint on `(quotation_id, version_number)`.

### 3.8 BOQ / BOQLineItem

A Bill of Quantities belongs to exactly one `QuotationVersion` (1:1).
Historical BOQs imported without a full quotation record can still attach
via a synthetic `Quotation`/`QuotationVersion` created by the importer.

**BOQ**

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| quotation_version_id | FK → QuotationVersion.id, required, unique | enforces 1:1 |
| title | str, nullable | |

**BOQLineItem**

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| boq_id | FK → BOQ.id, required | |
| line_number | str, nullable | as printed on the original BOQ (e.g. "2.1.3") |
| description | text, required | |
| trade_id | FK → Trade.id, nullable | |
| unit | str, nullable | e.g. `m2`, `no`, `LS` |
| quantity | Numeric(14,3), nullable | |
| unit_rate | Numeric(14,2), nullable | |
| total | Numeric(14,2), nullable | `quantity * unit_rate`, kept in sync by the service layer, not a DB trigger |
| currency | Currency, default `AED` | |

### 3.9 Vendor (Suppliers & Subcontractors)

The brief lists "Suppliers" and "Subcontractors" as separate entities. They
are modeled as **one table with a type discriminator** rather than two
near-identical tables, because they share the same shape (contact details,
trade specialization, payment terms) and everywhere they're used
(`ActualCost.vendor_id`, `Invoice.vendor_id`) either one is equally valid.
Splitting them would duplicate every column and every relationship for no
behavioral difference. If supplier- or subcontractor-specific fields
emerge later (e.g. subcontractor license/insurance tracking), that's an
additive migration on this table, not a schema redesign.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| vendor_type | VendorType enum, required | `SUPPLIER` or `SUBCONTRACTOR` |
| name | str, required, indexed | |
| trade_id | FK → Trade.id, nullable | primary specialization |
| contact_name | str, nullable | |
| contact_email | str, nullable | |
| contact_phone | str, nullable | |
| payment_terms | str, nullable | e.g. "30 days" |
| notes | text, nullable | |

### 3.10 EstimatedCost

Line items making up the estimated cost for a project at tender stage.
Linked to the quotation version so historical estimates are preserved even
if a new version is created.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| project_id | FK → Project.id, required | |
| quotation_version_id | FK → QuotationVersion.id, nullable, `SET NULL` | which estimate this belongs to |
| cost_category_id | FK → CostCategory.id, required | |
| trade_id | FK → Trade.id, nullable | |
| description | str, nullable | |
| amount | Numeric(14,2), required | |
| currency | Currency, default `AED` | |

### 3.11 ActualCost

Costs actually incurred during execution.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| project_id | FK → Project.id, required | |
| cost_category_id | FK → CostCategory.id, required | |
| trade_id | FK → Trade.id, nullable | |
| vendor_id | FK → Vendor.id, nullable | who was paid |
| invoice_id | FK → Invoice.id, nullable, `SET NULL` | the vendor invoice this cost came from, if any |
| description | str, nullable | |
| amount | Numeric(14,2), required | |
| currency | Currency, default `AED` | |
| incurred_date | date, nullable | |

### 3.12 Invoice

Covers both directions: money owed *by* the client (sales/AR) and money
owed *to* a vendor (purchase/AP), distinguished by `direction`. Exactly one
of `client_id` / `vendor_id` is set, matching `direction`.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| project_id | FK → Project.id, required | |
| direction | InvoiceDirection enum, required | `CLIENT` or `VENDOR` |
| client_id | FK → Client.id, nullable | set when `direction=CLIENT` |
| vendor_id | FK → Vendor.id, nullable | set when `direction=VENDOR` |
| invoice_number | str, nullable | |
| status | InvoiceStatus enum, required, default `DRAFT` | |
| amount | Numeric(14,2), required | |
| currency | Currency, default `AED` | |
| issued_date | date, nullable | |
| due_date | date, nullable | |
| notes | text, nullable | |

A `CHECK` constraint enforces exactly one of `client_id`/`vendor_id` being
non-null, matching `direction`.

### 3.13 Payment

Payments recorded against an invoice (either received from a client or
paid to a vendor — direction is inherited from the parent invoice).

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| invoice_id | FK → Invoice.id, required | |
| amount | Numeric(14,2), required | |
| currency | Currency, default `AED` | |
| paid_date | date, required | |
| method | PaymentMethod enum, nullable | |
| reference | str, nullable | cheque number / transfer reference |
| notes | text, nullable | |

### 3.14 ProjectVariation

Change/variation orders that adjust the contract value (and often cost)
after award.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| project_id | FK → Project.id, required | |
| variation_number | str, nullable | |
| description | text, nullable | |
| proposed_value_change | Numeric(14,2), nullable | revenue impact if approved |
| approved_value_change | Numeric(14,2), nullable | set once approved; used in actual revenue |
| estimated_cost_change | Numeric(14,2), nullable | |
| currency | Currency, default `AED` | |
| status | VariationStatus enum, required, default `PROPOSED` | |
| submitted_date | date, nullable | |
| decided_date | date, nullable | |

### 3.15 GoogleDriveDocument

A reference to a file stored in Google Drive — never the file content, and
never a source of financial figures on its own.

| Column | Type | Notes |
|---|---|---|
| id | PK | |
| project_id | FK → Project.id, required | |
| quotation_version_id | FK → QuotationVersion.id, nullable, `SET NULL` | optional finer association |
| invoice_id | FK → Invoice.id, nullable, `SET NULL` | optional finer association |
| document_type | DocumentType enum, required | `QUOTATION`, `BOQ`, `CONTRACT`, `INVOICE`, `DRAWING`, `PHOTO`, `CORRESPONDENCE`, `OTHER` |
| drive_file_id | str, required, unique | Google Drive file ID |
| name | str, required | |
| web_link | str, nullable | |
| mime_type | str, nullable | |
| synced_at | datetime, nullable | last time metadata was refreshed from Drive |

## 4. Enumerations (`app/core/enums.py`)

Defined in `core` (not `models`) so they carry no SQLAlchemy dependency and
can be reused by the financial engine, services, and UI alike; `models/`
imports them for column definitions.

| Enum | Values |
|---|---|
| `Currency` | `AED`, `USD`, `EUR`, `GBP`, `SAR` (extensible; stored as plain string) |
| `ProjectStatus` | `LEAD`, `TENDERING`, `SUBMITTED`, `AWARDED`, `LOST`, `IN_PROGRESS`, `ON_HOLD`, `COMPLETED`, `CLOSED`, `CANCELLED` |
| `QuotationStatus` | `DRAFT`, `SUBMITTED`, `REVISED`, `WON`, `LOST`, `WITHDRAWN`, `EXPIRED` |
| `VendorType` | `SUPPLIER`, `SUBCONTRACTOR` |
| `InvoiceDirection` | `CLIENT`, `VENDOR` |
| `InvoiceStatus` | `DRAFT`, `ISSUED`, `PARTIALLY_PAID`, `PAID`, `OVERDUE`, `CANCELLED`, `DISPUTED` |
| `PaymentMethod` | `BANK_TRANSFER`, `CHEQUE`, `CASH`, `CARD`, `OTHER` |
| `VariationStatus` | `PROPOSED`, `PENDING_APPROVAL`, `APPROVED`, `REJECTED`, `CANCELLED` |
| `DocumentType` | `QUOTATION`, `BOQ`, `CONTRACT`, `INVOICE`, `DRAWING`, `PHOTO`, `CORRESPONDENCE`, `OTHER` |

## 5. Data integrity summary

- **Constraints**: required foreign keys are `NOT NULL`; `Invoice` has a
  `CHECK` tying `direction` to which party FK is populated; unique
  constraints on `(quotation_id, version_number)`, `BOQ.quotation_version_id`,
  `Project.project_code`, `GoogleDriveDocument.drive_file_id`.
- **Validation**: Pydantic schemas at the service boundary validate input
  before it reaches the ORM (e.g. amounts ≥ 0, dates in sensible order).
- **Audit**: `created_at`/`updated_at` on every table; `ProjectStatusHistory`
  for status changes; quotation *versions* rather than in-place edits.
- **Soft deletion**: applied to `Project`, `Client`, `Vendor`, `Quotation`,
  `QuotationVersion`, `BOQ`, `BOQLineItem`, `EstimatedCost`, `ActualCost`,
  `Invoice`, `Payment`, `ProjectVariation`. Lookup tables (`Trade`,
  `CostCategory`, `Company`) and `GoogleDriveDocument` are hard-deletable
  since they carry no independent financial history.
- **No destructive migrations**: see `ARCHITECTURE.md` §5.
