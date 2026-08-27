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

### 3a. Ordering independence (PO-before-quotation reconciliation)

A historical batch is not guaranteed to arrive quotation-first. When a PO
is staged and its reference doesn't yet match any quotation, it is left
`UNMATCHED` — but this is never a dead end. `app.services.
purchase_order_service.reconcile_unmatched_purchase_orders` is called
automatically by `app.services.import_service.confirm_import` whenever a
**brand-new** `Quotation` (never a revision — a revision never changes
`Quotation.reference_number`) is created, and re-runs
`match_quotation_for_reference` for every currently `UNMATCHED`,
not-yet-resolved PO candidate. A candidate that newly resolves to
`MATCHED` is auto-confirmed via the same, unmodified
`confirm_purchase_order_import` a human would otherwise click — same
exact-match rule, same one-shot `mark_awarded` guard, same
already-awarded-gets-evidence-only behavior. One that resolves to
`AMBIGUOUS` is updated and left for manual review, never auto-confirmed.
A `CONFIRMED`/`REJECTED` document is never touched again. This makes "PO
arrives before its quotation" and "quotation arrives before its PO" both
safe orderings for the same historical-ingestion pipeline.

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

## 6a. Real-PO validation round 1

Validated against four real uploaded documents (see git history for the
session this ran in): three genuine client-issued POs and one Vision→vendor
procurement PO (out of scope, excluded — see §2/§6 on cost-side POs not
being built yet). Full field-by-field results, fixes, and before/after
numbers are in that session's report; summarized here for future rounds:

- **Confirmed real label variants** now in `app/core/po_extraction.py`:
  `"quotation ref"` (abbreviated form) and `"your/vendor ref"` (used by two
  independent real client PO templates), alongside the original
  `"quotation reference"`.
- **Confirmed real date format**: `DD-Mon-YY` (e.g. `15-May-26`), added to
  the shared `_DATE_FORMATS` in `app/core/import_normalization.py`.
- **Confirmed real no-separator VAT/Grand-Total wording**, ported from the
  quotation side's already-proven pattern into a PO-specific fallback
  (`app/core/po_extraction.py`, never touching `import_extraction.py`).
- **New, narrow fallback mechanism**: `_find_po_reference_anywhere_on_line`
  — a `search()`-based (not line-start-anchored) recovery for
  `po_reference_number` specifically, scoped only to a fixed set of
  specific multi-word label phrases (never a bare "reference"/"ref"), for
  the real, recurring case of a two-column PO header table flattening two
  columns onto one OCR line.
- **Confirmed, accepted limitation**: a real client PO template (Saudi
  Power Transformers Co.) uses the same `"your/vendor ref"` label, but its
  value ends up many lines away from the label after OCR — a genuine
  table/reading-order scramble, structurally different from the same-line
  bleed case above, and not fixable by any narrow per-label pattern. This
  mirrors the exact same category of limitation already accepted
  throughout the quotation OCR work (see `IMPORT_ARCHITECTURE.md`) — it
  is not new to POs, just now confirmed on real PO documents too.
- Match/award/idempotency/rollback/immutability behavior all validated
  against real documents with no code changes needed — only extraction
  needed fixes; the matching and award logic behaved correctly from the
  first real document onward.

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

## 8. Supplier/Vendor intelligence foundation

The next ERP vertical after quotations/POs is Supplier/Vendor
intelligence: `Supplier → PO → Quotation/Project` today, and — not built
in this round — `Supplier → Invoice → Payment` later. This round
establishes the relationships that later work depends on, without
building the downstream financial modules themselves.

### 8.1 What already existed

`Vendor` (one table, `vendor_type` discriminator for Supplier/
Subcontractor — see `DATABASE_SCHEMA.md` §3.9) already existed, already
used by `ActualCost.vendor_id` and `Invoice.vendor_id`. It was extended,
not duplicated: `tax_number`, `default_currency`, `is_active` were added
as plain, additive columns. "Total historical spend" and "outstanding
payable amount" were deliberately *not* added as columns — every
relationship needed to compute them already existed before this round
(`ActualCost.vendor_id`, `Invoice.vendor_id` + `Payment`), so they remain
computed-on-demand, never stored, the same rule this schema has followed
everywhere since Phase 1.

### 8.2 Extraction and matching are document-kind-agnostic by design

`app/core/vendor_extraction.py` and `app/services/vendor_matching.py` are
deliberately not quotation/PO-specific code — they extract/match a
vendor's identity (name, VAT/tax registration number) from *any*
already-OCR'd text, the same way `po_extraction.py`/`po_matching.py`
extract/match PO-shaped fields, but with no assumption baked in about
what kind of document produced that text. The only thing wired to a
specific document type this round is the one call site
(`import_service._build_purchase_order_candidate`, since client POs are
the only document type currently staged that might plausibly name a
vendor — e.g. a client-nominated subcontractor). When vendor invoices or
other procurement documents are ingested in a future round, they reuse
these same two modules unchanged; only a new call site is added.

Matching is exact only, strongest-signal-first (tax number, then name),
whitespace/case-normalized but never fuzzy or similarity-based — the
same discipline `po_matching.py` already established for PO-to-quotation
matching. An exact match against more than one `Vendor` is `AMBIGUOUS`
and is never resolved by falling through to a weaker signal. Reuses
`PurchaseOrderMatchStatus`'s existing three values rather than
introducing a near-duplicate enum — its values carry no PO-specific
meaning, only its class name does.

### 8.3 The vendor match is always optional, unlike the quotation match

This is the one deliberate asymmetry from the existing PO↔quotation
matching rule: an `UNMATCHED`/`AMBIGUOUS` `match_status` blocks
`confirm_purchase_order_import` outright (no PO can exist without an
exact quotation match), but an `UNMATCHED`/`AMBIGUOUS`
`vendor_match_status` never blocks it. Most real client POs will never
name a vendor at all, and that must never be treated as a defect in the
PO itself. `PurchaseOrder.vendor_id` is therefore always nullable and
independent of `quotation_id` — populated only when a vendor was both
named on the document and deterministically matched, exactly mirroring
"PO before quotation"/"quotation before PO" reconciliation's own
principle: extract first, stage, identify a candidate if possible, leave
unmatched if not, and never let an unresolved secondary identity block a
primary, already-safe transaction.

### 8.4 What this round does not build

- No vendor invoice ingestion, no vendor PO (a PO *we* issue to a
  supplier, as opposed to a PO a *client* issues to us) — this round only
  extends the existing client-PO pipeline with an optional vendor link.
- No supplier spend/payable analytics functions — the relationships
  needed for them exist; the functions themselves are future work.
- No UI for managing vendors or reviewing a vendor match.
- No real supplier/vendor document archive has been ingested yet — the
  label vocabulary in `vendor_extraction.py` is provisional accounting-
  document wording, the same starting posture `po_extraction.py` had
  before real PO scans existed to validate against. When real supplier
  documents arrive, extend it the same evidence-driven way: diagnose
  against the real OCR text first, then make a narrow, grounded addition
  with a regression test — never expand the heuristic set speculatively.
