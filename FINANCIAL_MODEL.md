# Financial Model — Vision Contracting Profit System

This document is the authoritative narrative explanation of every
financial term the system uses, the exact formulas that relate them, and
the rounding rules that apply. The code is the ultimate source of truth —
`app/core/financial_engine.py` (pure calculations) and
`app/services/financial_service.py` (database aggregation) — but this
document should never fall out of sync with it.

**Core principle, unchanged since Phase 1: AI is never the authority for a
financial number.** Every figure below is either typed in by a user or
computed by a deterministic Python function. There is no code path where a
language model output becomes a cost, revenue, or profit figure.

## 1. The three stages of "profit"

The single most common way a profit figure goes wrong is silently
substituting one revenue basis for another (quoted value for awarded
value, or cash received for revenue). To make that impossible, the system
recognizes three distinct stages, each with its own named revenue basis:

| Stage | When | Revenue basis | Profit | Margin |
|---|---|---|---|---|
| **1. Quoted** | Before award (a bid/no-bid decision) | `quoted_value` | `quoted_profit` | `quoted_margin` |
| **2. Estimated** | After award, using contract terms | `awarded_contract_value` | `estimated_profit` | `estimated_margin` |
| **3. Actual** | During/after execution, using real figures | `revised_contract_value` (= `actual_revenue`) | `actual_profit` | `actual_margin` |

A project moves through these stages left to right as it progresses; a
project that is never awarded simply never reaches stage 2 or 3 — its
`awarded_contract_value` stays `None` forever, and so do every figure
downstream of it (`actual_revenue`, `actual_profit`, `actual_margin` are
all `None`, never `0` and never silently equal to the quoted-stage
numbers).

## 2. Revenue definitions

| Term | Definition | Notes |
|---|---|---|
| **Quoted value** | The value submitted to the client in a specific quotation revision. | Stated exclusive of VAT by convention. Source: `QuotationVersion.quoted_value`. |
| **Awarded contract value** | The value actually agreed at award. | The ORIGINAL value — fixed once set, never mutated by variations. Stated exclusive of VAT. Source: `Project.contract_value`. |
| **Approved variation value** | The net sum of only APPROVED contract variations. | PENDING/PROPOSED/REJECTED/CANCELLED variations contribute nothing. May be negative (a credit / de-scope). |
| **Revised contract value** | `awarded_contract_value + approved_variation_value`. | The live, current entitlement. Also called **actual revenue** — the two names refer to the exact same figure; see §4. |
| **Invoiced revenue** | The sum of CLIENT-direction invoices raised, **net of VAT**. | What has actually been billed, tax excluded. Normally lags `revised_contract_value` on an in-progress project; the two should converge once the project is fully invoiced. |
| **Invoiced revenue (gross)** | The same sum, **inclusive of VAT** — the face value actually printed on the invoices. | Not itself a revenue figure; it is what the client actually owes in cash, VAT included. |
| **Cash received** | The sum of payments actually collected against client invoices. | Never revenue. See §4. |
| **Retention outstanding** | Retention withheld to date minus retention released to date. | Invoiced revenue already includes retained amounts; retention only affects *collectibility*, not revenue recognition. See §5. |
| **Receivables outstanding** | Amount currently due (invoice amounts after retention withholding) minus cash received. | The real, VAT-inclusive amount still owed in cash. |

## 3. Cost definitions

| Term | Definition | Notes |
|---|---|---|
| **Estimated cost** | The planned cost for a project, by category, at the relevant quotation stage. | Sum of `EstimatedCost` rows scoped to the current/winning quotation version (plus version-independent rows). A single current estimate feeds both the quoted and estimated profit stages — see §7. |
| **Actual cost** | Cost actually incurred/accrued during execution, recognized independently of vendor payment status. | Sum of the *recognized* amount of each `ActualCost` row — see "recognized cost" below. |
| **Net amount** (of a cost or invoice) | The tax-exclusive value: `gross - tax`. | `calculate_net_of_tax()`. |
| **Gross amount** | The tax-inclusive value: `net + tax`. | `calculate_gross_amount()`, the inverse. |
| **Recognized cost** | The portion of an `ActualCost` that actually counts as project cost. | By default (`is_tax_recoverable=True`), this is the **net** amount — VAT is reclaimable and not a real cost. If `is_tax_recoverable=False` (e.g. blocked input VAT), the recognized cost is the full **gross** amount, since the business genuinely bears it. `calculate_recognized_cost()`. |

## 4. Revenue vs. cash — the rule that must never be broken

> **Cash received is never treated as revenue. Revenue is never
> substituted with cash received.**

`actual_revenue` (= `revised_contract_value`) is an **accrual** figure: it
represents what the company is entitled to for the contract as it
currently stands, based on the awarded value and approved variations —
regardless of how much has been invoiced or collected yet. `cash_received`
is a completely independent, transactional figure summed from `Payment`
rows. Neither formula references the other:

```
actual_revenue = awarded_contract_value + approved_variation_value
actual_profit  = actual_revenue - actual_cost
```

Changing `cash_received` — collecting more or less cash on existing
invoices — never changes `actual_profit`. A project can show a healthy
`actual_profit` while its client is slow to pay (a cash-flow problem, not
a profitability problem), and the two must be visibly distinct figures at
all times. See `test_scenario_8_cash_received_is_not_revenue` in
`test_financial_engine.py`.

## 5. VAT / Tax

> **VAT is a pass-through liability collected on the government's behalf.
> It is never revenue and never profit.**

Worked example (from the brief):

```
Net contract value:  AED 1,000,000
VAT (5%):            AED    50,000
Gross invoice:        AED 1,050,000

Project revenue remains AED 1,000,000 — not 1,050,000.
```

- `quoted_value`, `awarded_contract_value`, and `ProjectVariation` amounts
  are **always stated exclusive of VAT** by convention. VAT never enters
  the accrual-revenue formula at all.
- VAT only appears explicitly at the transaction level: `Invoice.tax_amount`
  and `ActualCost.tax_amount`, each a component *within* that row's total
  `amount` (which is the gross, tax-inclusive face value).
- The tax rate itself is never hard-coded: `tax_amount` is a plain entered
  Decimal on each row, so a 5% VAT project and a 15% VAT project (or a
  future non-UAE project with a different rate) both work identically —
  the engine only ever sees the resulting `tax_amount`, never a rate
  constant. This is what "configurable tax/VAT rate" means in practice:
  configuration lives in the data (what rate was applied to this specific
  invoice), not in the code.
- `calculate_net_of_tax(gross, tax)` strips VAT out wherever a figure is
  being turned into revenue or cost. `invoiced_revenue` in the financial
  snapshot is always net; `invoiced_revenue_gross` is kept alongside it
  for transparency (e.g. reconciling against bank receipts), never
  confused with the revenue figure itself.
- On the cost side, VAT is excluded from project cost by default (it is
  reclaimable) — see "recognized cost" above. Only an explicit
  `is_tax_recoverable=False` flag lets tax become a real cost.

## 6. Retention

> **Retention withheld is still invoiced revenue. It is not a project
> cost, and it is not yet collectible cash.**

Worked example (from the brief):

```
Net invoice:     AED 100,000
VAT (4.75%):     AED   4,750
Gross invoice:   AED 104,750   (= net + VAT)
Retention:       AED   5,000   (withheld from the gross invoice)
Amount due now:  AED  99,750   (= gross - retention)
```

- `Invoice.retention_amount` is the portion of that invoice's gross value
  withheld by the counterparty (a client withholding from Vision
  Contracting, or Vision Contracting withholding from a subcontractor —
  the same field serves both directions).
- `calculate_amount_due_after_retention(gross, retention)` computes what's
  currently payable; this is independent of `calculate_net_of_tax` — one
  strips VAT, the other strips retention, and they answer different
  questions (revenue recognition vs. cash collectibility).
- Retention is released later (typically at the end of the defects
  liability period) as an ordinary `Payment` row flagged
  `is_retention_release=True` — no separate "retention release" table is
  needed. `retention_outstanding` = total withheld minus total released,
  so it correctly shrinks to zero once released rather than growing
  forever.
- Retention never appears anywhere in a cost calculation. It is purely a
  revenue-collection-timing concept.

## 7. Estimated and actual cost, kept strictly separate

Estimated and actual costs live in entirely separate tables
(`EstimatedCost`, `ActualCost`) and are never merged or allowed to
overwrite one another — this was established in Phase 1 and is unchanged.
What Phase 2 adds:

- **Cost categories are data, not code.** `CostCategory` is a plain lookup
  table; `app/database/seed.py` optionally seeds the initial set
  (Materials, Labour, Subcontractors, Equipment, Transport, Plant,
  Permits, Professional Fees, Other), but nothing in
  `financial_engine.py` or `financial_service.py` branches on a category
  name. Renaming, adding, or removing a category is a data change.
- **A single current `estimated_cost` figure feeds both the quoted and
  estimated profit stages.** In practice, cost estimates evolve as a
  quotation is revised, but the engine doesn't need two separate "cost at
  quoting time" vs. "cost at award time" inputs — the caller (the
  financial service) always supplies whatever the current best estimate
  is, scoped to the relevant quotation version. A business that wants to
  freeze and compare the cost estimate as it stood at a specific past
  revision can do so by reading that revision's linked `EstimatedCost`
  rows directly; that is a reporting concern, not a change to the
  snapshot's shape.
- **Actual cost is accrual-based, decoupled from vendor payment status.**
  An `ActualCost` row is recognized as soon as the cost is incurred or
  certified — regardless of whether the linked vendor invoice, if any, has
  itself been paid. `ActualCost.payment_status` tracks payment
  independently (useful even when there's no formal linked `Invoice` yet —
  see `reference_number`), but it never gates whether the cost counts
  toward `actual_cost`. This is standard construction accounting practice:
  a cost that's been incurred is a cost, whether or not it's been settled
  in cash yet.

## 8. Contract variations

Only **APPROVED** variations affect `revised_contract_value` (and hence
`actual_revenue`). PENDING_APPROVAL, PROPOSED, REJECTED, and CANCELLED
variations contribute nothing, however large:

```
Original contract = AED 1,000,000
Variation A = +AED 100,000  APPROVED
Variation B = +AED  50,000  PENDING_APPROVAL   <- excluded
Variation C = -AED  25,000  APPROVED

revised_contract_value = 1,000,000 + 100,000 - 25,000 = AED 1,075,000
```

Variations may be positive (additional scope) or negative (a credit or
de-scope) — nothing in the schema or engine assumes a variation is always
an increase. This filtering happens in
`app.services.financial_service.build_project_financial_snapshot`, which
only sums `ProjectVariation` rows with `status == APPROVED`; the pure
engine function `calculate_revised_contract_value()` simply trusts that
its `approved_variation_value` input has already been filtered correctly.

## 9. Estimated vs. actual: variance

Every variance follows the same "actual minus baseline" convention — a
positive cost variance is an overrun, a positive revenue/profit/margin
variance is outperformance:

```
cost_variance    = actual_cost - estimated_cost
revenue_variance = actual_revenue - awarded_contract_value
                  (equivalently: the net effect of approved variations)
profit_variance  = actual_profit - estimated_profit
margin_variance  = actual_margin - estimated_margin   (percentage points)
```

## 10. Project status is informational, never part of the math

`ProjectFinancialSnapshot.project_status` exists so a report can always
show a project's true state (`LOST`, `CANCELLED`, `IN_PROGRESS`,
`COMPLETED`, ...) alongside its numbers — but the financial engine never
branches on it. A `LOST` quotation may still show a `quoted_profit` (a
useful "what we would have made" figure for post-mortem analysis), but its
`awarded_contract_value` stays `None`, so `actual_revenue`/`actual_profit`
correctly resolve to `None` — never showing a lost deal as realized
profit. A `CANCELLED` project's `actual_profit` is computed with the exact
same formula as an `IN_PROGRESS` one, using whatever figures were actually
recorded before cancellation; there is no special-cased "cancelled
profit" formula, because the real numbers (contract value, approved
variations, actual costs incurred before cancellation) are already
sufficient and correct without one.

## 11. Rounding rules

- **All monetary amounts are `Decimal`, never `float`.** Money columns are
  `Numeric(14, 2)` in the database, so a value is already exact to 2
  decimal places the moment it's entered.
- **Addition and subtraction never need rounding.** Two exact 2-decimal
  Decimals added or subtracted produce another exact 2-decimal Decimal —
  every profit, variance, and revenue figure in this document is pure
  addition/subtraction, so none of them are ever rounded by the engine.
- **Division is rounded.** The only division the engine performs is a
  margin percentage (`profit / revenue * 100`), which can produce more
  than 2 decimal places. `safe_margin()` rounds the result to 2 decimal
  places using `ROUND_HALF_UP` via `app.core.money.quantize`.
- **Multiplication is rounded.** `calculate_line_total(quantity, unit_rate)`
  multiplies a 3-decimal quantity by a 2-decimal rate, which can produce
  up to 5 decimal places; the result is quantized to 2 decimal places
  (`ROUND_HALF_UP`) to keep it a valid money amount.
- These are the *only* two rounding points in the entire financial engine.
  Every other function is exact.

## 12. Worked example — a full project lifecycle (AED)

A project is quoted, awarded, varied, invoiced, and executed:

1. **Quoted.** `quoted_value = 1,000,000`; estimated cost at tender stage
   = `780,000`.
   `quoted_profit = 220,000`, `quoted_margin = 22.00%`.
2. **Awarded.** The client awards at the quoted value:
   `awarded_contract_value = 1,000,000` (unchanged from the quote here,
   though it need not be).
   `estimated_profit = 1,000,000 - 780,000 = 220,000`,
   `estimated_margin = 22.00%` — same numbers as stage 1 in this example,
   but computed from a different, now-fixed revenue basis.
3. **Variations.** A +100,000 variation is approved; a -25,000 variation
   is also approved; a +50,000 variation remains pending.
   `approved_variation_value = 75,000`.
   `revised_contract_value = actual_revenue = 1,075,000`.
4. **Invoicing.** A single invoice for `1,050,000` gross is raised, with
   `tax_amount = 50,000` and `retention_amount = 52,500`.
   `invoiced_revenue_gross = 1,050,000`, `invoiced_revenue = 1,000,000`.
5. **Payment.** `700,000` is received.
   `cash_received = 700,000`. Amount due after retention =
   `1,050,000 - 52,500 = 997,500`; `receivables_outstanding = 297,500`.
6. **Actual costs.** `525,000` gross incurred with `25,000` recoverable
   VAT (recognized cost `500,000`), plus `300,000` with no VAT.
   `actual_cost = 800,000`.
7. **Actual profitability.**
   `actual_profit = 1,075,000 - 800,000 = 275,000`,
   `actual_margin = 275,000 / 1,075,000 * 100 = 25.58%`.
8. **Variance.**
   `cost_variance = 800,000 - 780,000 = 20,000` (a cost overrun),
   `revenue_variance = 1,075,000 - 1,000,000 = 75,000`,
   `profit_variance = 275,000 - 220,000 = 55,000`.

This exact scenario is encoded as
`test_full_lifecycle_end_to_end_snapshot` in `test_financial_service.py`.

## 13. Where each figure comes from

| Figure | Kind | Source |
|---|---|---|
| `quoted_value` | Input | `QuotationVersion.quoted_value` of the relevant version |
| `awarded_contract_value` | Input | `Project.contract_value` |
| `approved_variation_value` | Aggregated input | `SUM(ProjectVariation.approved_value_change WHERE status=APPROVED)` |
| `estimated_cost` | Aggregated input | `SUM(EstimatedCost.amount)` scoped to the relevant quotation version |
| `actual_cost` | Aggregated input | `SUM` of each `ActualCost`'s *recognized* amount |
| `invoiced_revenue` / `invoiced_revenue_gross` | Aggregated input | `SUM` over CLIENT `Invoice` rows, net/gross of tax |
| `cash_received` | Aggregated input | `SUM(Payment.amount)` for those invoices |
| `retention_outstanding` | Aggregated input | withheld total minus released total |
| `receivables_outstanding` | Aggregated input | amount due after retention minus cash received |
| everything else (`quoted_profit`, `estimated_margin`, `revised_contract_value`, `actual_profit`, every variance, ...) | **Computed property** | Derived on demand from the inputs above — never separately stored |
| `EstimateAccuracyReport.original_estimate` | Aggregated input | `SUM(EstimatedCost.amount)` for the project's original `EstimateRevision` (see §14) |
| `EstimateAccuracyReport.final_estimate` | Aggregated input | `SUM(EstimatedCost.amount)` for the project's final `EstimateRevision` (see §14) |
| `estimate_change`, `original_estimate_variance`, `final_estimate_variance`, and their percentages | **Computed property** | Derived from the two rows above and `actual_cost` — never separately stored |

No computed figure is ever also persisted as a database column (see
DATABASE_SCHEMA.md §6 "Data integrity summary" for the no-duplicate-totals
rule); a `ProjectFinancialSnapshot` is always built fresh from source
records via `app.services.financial_service.build_project_financial_snapshot`.

## 14. Estimating accuracy history — original, revised, and final

This application exists to let Vision Contracting analyze its estimating
accuracy over multiple years, which requires something the figures above
don't provide on their own: **estimated cost must never be silently
overwritten**. `ProjectFinancialSnapshot.estimated_cost` (§13) always
reflects whatever the *current* best estimate is — perfectly fine for
live profitability, but useless for asking "what did we originally think
this would cost, and how far off were we?" once that original number has
been replaced.

### 14.1 EstimateRevision

An `EstimateRevision` is a named, point-in-time snapshot of a project's
cost estimate (see DATABASE_SCHEMA.md §3.10 for the full schema). Every
re-estimate — at tender stage, at award, or at any point during
execution — creates a **new** revision via
`app.services.financial_service.create_estimate_revision`, which assigns
the next sequential `revision_number`. `EstimatedCost` rows are added
under that revision; existing revisions and their cost lines are never
edited or deleted. This is what makes the history reliable: there is no
code path that mutates a past estimate, only ones that add a new one.

It is deliberately independent of `QuotationVersion` — a quotation is only
revised before award, but the cost estimate keeps being refined well after
award, during execution, with no quotation to attach a new revision to.

### 14.2 Identifying original, latest, and final

| Question | Answer |
|---|---|
| What did we originally estimate? | The `EstimatedCost` rows under the revision with the lowest `revision_number` (`get_original_estimate_revision`). |
| What was our latest estimate (regardless of completion)? | The revision with the highest `revision_number` (`get_latest_estimate_revision`). |
| What was our final estimate before/at completion? | See §14.3 (`get_final_estimate_revision`) — not always the same as "latest". |
| What did the project actually cost? | Unchanged: `SUM` of each `ActualCost`'s recognized amount — completely separate from any estimate, exactly as before. |

### 14.3 Determining the "final" estimate

"Final" is not simply "the newest revision" — a business may keep
re-forecasting after a project nominally completes (e.g. during a
closeout review), and that shouldn't retroactively redefine what the
estimate was *at* completion. `get_final_estimate_revision` resolves it in
this order:

1. **Explicit flag.** If a revision is marked `is_final=True`, that one
   wins, unconditionally. A database constraint guarantees at most one
   revision per project can carry this flag.
2. **Latest before completion.** If no revision is flagged final and the
   project has an `actual_completion_date`, the latest revision whose
   `effective_date` (falling back to its `created_at` date) is at or
   before that completion date is used. If no revision qualifies, the
   result is `None` rather than guessing.
3. **Latest overall.** If the project hasn't completed yet and nothing is
   flagged final, "final" and "latest" are the same thing — there's
   nothing to distinguish them from until the project actually finishes.

### 14.4 Estimating accuracy

`EstimateAccuracyReport` (built by
`app.services.financial_service.build_estimate_accuracy_report`) compares
the original and final revisions against actual cost:

```
estimate_change            = final_estimate - original_estimate
original_estimate_variance = actual_cost - original_estimate
final_estimate_variance    = actual_cost - final_estimate
```

Both variances reuse `calculate_cost_variance` — accuracy is just "actual
minus a specific estimate," the same formula already used for the live
cost variance, just anchored to a named historical revision instead of
whatever the current estimate happens to be. A percentage view of each is
also available (`original_estimate_variance_percentage`,
`final_estimate_variance_percentage`), following the same
`safe_margin`-based null/zero handling as every other percentage in this
document.

**Worked example.** A project's estimate evolves as follows:

```
Revision 1 (original, at tender):  estimated cost = AED 780,000
Revision 2 (mid-project):          estimated cost = AED 800,000
Revision 3 (is_final=True):        estimated cost = AED 820,000
Actual cost at completion:                          AED 800,000

estimate_change            = 820,000 - 780,000 =  40,000  (estimate grew)
original_estimate_variance = 800,000 - 780,000 =  20,000  (original underestimated)
final_estimate_variance    = 800,000 - 820,000 = -20,000  (final overestimated)
```

The original estimate and the final estimate were each wrong by the same
magnitude but in opposite directions — a distinction that would be
completely invisible if only "the current estimated cost" were ever kept.

### 14.5 What this does not do

This is intentionally narrow. It does not version-control every project
field, and it does not touch how `ActualCost` works — actual costs remain
exactly as separate from estimates as they were before this feature: no
`ActualCost` row references an `EstimateRevision`, and nothing here
changes `build_project_financial_snapshot`'s existing "current estimate"
scoping (§13), which continues to drive live profitability unchanged.
`EstimateRevision` exists solely to answer estimating-accuracy questions
across a project's lifetime.
