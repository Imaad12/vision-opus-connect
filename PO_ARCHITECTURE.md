# Purchase Order Ingestion — Foundation

This documents the PO ingestion foundation actually built (not the full
earlier design proposal — see git history for that discussion; this file
reflects what shipped and supersedes it wherever they differ). See
`IMPORT_ARCHITECTURE.md` for the quotation-side pipeline this reuses, and
`DATABASE_SCHEMA.md` §3.18 for the schema.

## 1. Why a PO matters

The business workflow is: `Quotation` → (client decides) → `Purchase
Order` → the PO's reference number cites the quotation it awards. A PO is
therefore the **authoritative evidence** that a quotation was awarded —
never inferred from a project existing, a quotation existing, or names
looking similar. This foundation exists to make that linkage exact and
auditable, as the base for later dashboards (quoted vs. awarded,
quotation-to-PO conversion, awarded value by client/project).

## 2. Scope of this round

Deliberately small, per the task that introduced it:

- One PO per file (no multi-PO-per-file segmentation — a real PO archive
  doesn't exist yet to design that against, unlike quotation segmentation,
  which was built against 29 real scanned pages).
- One extracted reference field, `po_reference_number` — per current
  business practice this **is** the quotation's own reference number as
  printed on the PO, not a separate PO-internal numbering scheme. This is
  also the sole matching key.
- No PO line items, no PO revision/version history — a `PurchaseOrder` is
  a single confirmed record per reference number. Revisiting this (a
  `PurchaseOrderVersion` table, mirroring `QuotationVersion`) is future
  work once real PO documents show revisions/cancellations happening in
  practice.
- Field label wording (`app/core/po_extraction.py`) is provisional,
  generic accounting-document vocabulary — not yet evidence-tuned against
  real PO scans the way quotation extraction was refined across four
  rounds against the real archive. Expect this to need adjustment once
  real POs are imported.

## 3. Pipeline

```
PO file (local, .pdf/.txt/.docx/scanned image/...)
  -> stage_purchase_order_document()   [app.services.import_service]
       - SHA-256 hash + duplicate check, same as quotation staging
       - document_kind = PURCHASE_ORDER set explicitly (never inferred —
         POs are a separate, explicitly-chosen import action, not
         auto-classified alongside quotation batches)
  -> run_po_extraction()               [same module]
       - deterministic importer, or OCR fallback (extract_via_ocr) if the
         file needs it — exactly the same importer registry/OCR engine
         quotations use, no new extraction infrastructure
       - extract_purchase_order_candidate()   [app.core.po_extraction]
       - match_quotation_for_reference()      [app.services.po_matching]
         computed immediately — matching is exact and deterministic, not
         a judgment call, so it's never deferred to confirmation time
       - ImportedPurchaseOrderCandidate persisted with match_status
  -> confirm_purchase_order_import()   [app.services.purchase_order_service]
       - only callable when match_status == MATCHED
       - creates PurchaseOrder, then calls the existing, unmodified
         quotation_service.mark_awarded() — the only way a project is
         awarded from a PO
  -> reject_purchase_order_import()    [same module]
       - REJECTED, no business record ever created
```

## 4. The award rule

Matching (`app.services.po_matching.match_quotation_for_reference`) is
**exact, whitespace-normalized string comparison only** — never fuzzy,
never by project/client name, never by value/date proximity.

| Outcome | Result |
|---|---|
| Exactly one quotation matches | `MATCHED` — confirming creates the `PurchaseOrder` and awards the quotation |
| No quotation matches | `UNMATCHED` — no `PurchaseOrder` is ever created; confirming raises |
| More than one quotation matches (a real possibility despite `Quotation.reference_number`'s DB uniqueness — see below) | `AMBIGUOUS` — confirming raises; never guesses |
| PO has no reference at all | `UNMATCHED` (same bucket as "no match found") |

Reference matching normalizes whitespace only (the same `normalize_whitespace`
already used everywhere else in this codebase, not a new fuzzy-matching
heuristic) — done in Python against every quotation's reference, not a raw
SQL `==`, which is what makes `AMBIGUOUS` representable at all: two
`Quotation` rows can legally differ only by incidental whitespace (e.g.
`"VN/QU/777/25"` vs. `" VN/QU/777/25"`) despite the column's own unique
constraint on the raw string.

## 5. Idempotency

Two independent layers, because they catch different duplicates:

1. **SHA-256 file hash** (`stage_purchase_order_document`, same mechanism
   quotations use) — catches re-importing the exact same bytes.
2. **`PurchaseOrder.po_reference_number` uniqueness** — catches a
   *rescanned* copy of the same physical PO (different bytes, same
   reference). `confirm_purchase_order_import` checks for an existing
   `PurchaseOrder` with the same reference first; if found, the new
   document is attached to it and neither a new record nor a second award
   is created.

**Known limitation:** because a PO's only extracted identifier is the
quotation reference it cites, two *genuinely different* POs against the
same quotation (e.g. a real amendment) cannot currently be distinguished
from a duplicate import of the same PO — both present the identical
reference text. This is an accepted gap for this foundation, not a bug;
resolving it needs a second, PO-internal identifier field, which has not
been added because no real PO document has been seen to justify its shape
yet (see §2).

A PO confirmed against a quotation that is **already awarded** (by any
means — a prior PO, or a manual award from the Quotations screen) is still
recorded as a `PurchaseOrder` row (evidence), but never re-triggers
`mark_awarded` and never changes `Project.contract_value`.

## 6. What this never does

Same financial-integrity discipline as quotation import:

- Never creates an `Invoice`, `Payment`, `ActualCost`, or `EstimatedCost`.
- Never creates a `ProjectVariation`, even when the PO's value differs
  from the quotation's `quoted_value` (expected after negotiation — the
  PO's own value becomes `contract_value` via `mark_awarded`, the
  quotation's historical `quoted_value` is never overwritten).
- Never creates or edits a `QuotationVersion` — award only ever flips the
  existing version's `status` to `WON` via the existing, unmodified
  `quotation_service.mark_awarded`.
- Never sets `Project.contract_value` outside that single call.

## 7. What remains before analytics

- No real PO archive has been ingested yet — the field-label vocabulary in
  `app/core/po_extraction.py` needs the same evidence-driven refinement
  quotation extraction went through once real PO scans exist.
- No PO revision/cancellation history (`PurchaseOrderVersion`) — add only
  once real documents show this happening.
- No PO line items / no multi-PO-per-file segmentation.
- No UI screen for staging/reviewing/confirming a PO import yet (this
  round is service-layer only, mirroring how quotation import's service
  layer preceded its UI).
- No dashboard/funnel reporting (quoted → awarded/PO received → invoiced →
  paid) — this foundation only makes sure the data needed for it exists;
  building the reporting itself is explicitly out of scope for this round.
