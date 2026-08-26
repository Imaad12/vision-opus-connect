# Analytics — Data Definitions (query layer only, no dashboard yet)

This documents `app/services/analytics_service.py`: a read-only query
layer over the existing `Quotation → QuotationVersion → Project/Client`
and `PurchaseOrder → Quotation` relationships (see `DATABASE_SCHEMA.md`,
`PO_ARCHITECTURE.md`). It introduces **no new arithmetic** beyond
summing/counting/averaging fields that are already correct —
`app.core.financial_engine` is not touched, and no award/matching logic
is duplicated. This module does not build a dashboard; it is the
deterministic, tested layer a future dashboard UI will call.

## 1. Which "quoted value" is used

A `Quotation` can have several `QuotationVersion` revisions. Every metric
below uses the **current version** — same definition and ordering rule as
`app.services.quotation_service.get_current_version`: the version with
the most recent `issued_date` (nulls last), tie-broken by highest `id`.
This is "dated most recently," never "entered into the system most
recently" — the same rule the confirm/revision-conflict logic already
depends on elsewhere.

A quotation whose current version has **no `quoted_value`** is excluded
from value totals and averages, and counted separately
(`quotations_missing_value_count`). A missing value is a data-completeness
gap, not a real zero — treating it as zero would understate nothing
(quoted value isn't a transactional sum like an invoice total) and
silently hide how much of the historical archive is still incomplete.

## 2. "Awarded" vs. "has a PO" — two different, both real, concepts

- **Awarded**: `QuotationVersion.status == WON` (set only by
  `quotation_service.mark_awarded`, one-shot, unchanged). This can happen
  with **or without** a `PurchaseOrder` ever being recorded — a project
  can still be manually awarded from the Quotations screen with no PO on
  file yet, exactly as before PO ingestion existed.
- **Has a PO**: at least one `PurchaseOrder` row references the
  quotation. Every confirmed `PurchaseOrder` implies its quotation was
  awarded (per `confirm_purchase_order_import`), but not every awarded
  quotation has a PO.

`quotation_to_po_conversion_rate` measures the second concept
(`quotations_with_po_count / quotation_count`), not the first — see
`awarded_quotation_count`/`awarded_value_total` for the first. Reporting
both side by side is what lets a manually-awarded-but-PO-less quotation
be told apart from a genuinely PO-evidenced one.

`awarded_value_total` sums `Project.contract_value` (the actually-agreed
figure, which may differ from `quoted_value` after negotiation — see
`FINANCIAL_MODEL.md`), never `quoted_value` again.

## 3. Trends (monthly/yearly)

Grouped by the current version's `issued_date` — the real business date
printed on the document — **never** `ImportedDocument.created_at` (that's
only when the file was digitized/imported, an archival artifact that can
be years after the fact for historical batches, and would badly distort
a real trend). A quotation with no known `issued_date` is excluded from
every trend entirely, never guessed at.

## 4. Average time from quotation to PO

`compute_average_time_to_po` averages `PurchaseOrder.po_date -
awarded_quotation_version.issued_date` in days, using **only** POs that
recorded `awarded_quotation_version_id` — set exclusively when *that*
specific PO is what triggered the award (see
`purchase_order_service.confirm_purchase_order_import`;
`reconcile_unmatched_purchase_orders` sets it identically for the
PO-before-quotation ordering). A later, evidence-only PO against an
already-awarded quotation never sets this field and is correctly excluded
— there would be no honest way to know which of possibly several POs
against that quotation timing should be measured against.

Always report `sample_size` alongside `average_days`: it is frequently a
small fraction of all POs, especially early in a historical-batch
ingestion where most POs won't yet have both dates cleanly extracted.

## 5. Quotations without a PO / unmatched POs

- `list_quotations_without_po`: quotations (any status) with zero
  `PurchaseOrder` rows. Includes both genuinely-never-awarded quotations
  and manually-awarded ones with no PO on file.
- `list_unmatched_purchase_order_candidates` /
  `compute_pending_purchase_order_summary`: PO **staging candidates**
  (`ImportedPurchaseOrderCandidate`) still `UNMATCHED`/`AMBIGUOUS` and not
  yet confirmed or rejected. A confirmed `PurchaseOrder` is, by
  construction (see `PO_ARCHITECTURE.md`), always matched — "unmatched
  POs" can only ever be a staging-layer concept, never a
  `PurchaseOrder`-table one.

## 6. PO financial analysis ("where data is actually available")

`compute_po_financial_analysis` sums `net_value`/`tax_value`/`gross_value`
only over `PurchaseOrder` rows where that specific field is non-null, and
reports each field's own sample size next to its total. Not every real PO
document yields a readable financial figure (see `PO_ARCHITECTURE.md`'s
documented table-reading-order limitations) — a smaller sample size than
`purchase_order_count` is expected and must never be backfilled or
estimated.

## 7. Currency breakdown

Two separate breakdowns — quotations (by current version's `currency`,
summing `quoted_value`) and POs (by `PurchaseOrder.currency`, summing
`net_value`) — since a PO's currency is not guaranteed to match its
quotation's (not yet observed in the real archive, but the schema already
allows it, per `DATABASE_SCHEMA.md` §4.3).

## 8. Scope

Deliberately not built yet, per the task this module was introduced
under: any dashboard UI, any chart/visualization, any caching/pagination
layer. `analytics_service.py` is called directly, synchronously, against
the live database — acceptable at this project's stated data scale (see
`app/services/dashboard_service.py`'s own precedent), revisited if a
future real historical batch proves otherwise.
