# Import Architecture — Local Document Import & Review (Phase 4)

Phase 4 adds a local document import pipeline: pick files from disk,
extract candidate quotation/BOQ data deterministically, let a human review
and correct it, and only on explicit confirmation write it into the real
business tables (`Client`, `Project`, `Quotation`, `QuotationVersion`,
`BOQ`, `BOQLineItem`) via the existing Phase 1–3 services. There is no
Google Drive integration, no AI/ML, and no OCR in this phase — see §12/§13.

## 1. The pipeline

```
Local file (unmodified)
    |  app.importers.*           -- format-specific readers
    v
RawExtraction                     -- exactly what the parser found (text/tables)
    |  app.core.import_extraction -- deterministic pattern matching + arithmetic
    v
Candidate data (in memory)        -- QuotationCandidateFields / BoqRowCandidate
    |  app.services.import_service.stage_document / run_extraction
    v
ImportedDocument + ImportedQuotationCandidate + ImportedBoqLineCandidate[]  (staging tables)
    |  human review (Import Center UI) — edit fields, edit BOQ rows
    v
app.services.import_service.confirm_import
    |  reuses client_service / project_service / quotation_service (Phase 1-3)
    v
Client / Project / Quotation / QuotationVersion / BOQ / BOQLineItem  (business tables)
```

Rejecting a staged document (`reject_import`) at any point before
confirmation touches nothing in the business tables — it only flips
`ImportedDocument.review_status` to `REJECTED` and appends an audit entry.
A confirmed import can never be re-confirmed or rejected afterward
(`confirm_import`/`reject_import` both check `review_status` first).

## 2. Layering (same rule as the rest of the app)

```
app/ui/imports/            PySide6 widgets — presentation only
      |
app/services/import_service.py   staging, extraction orchestration, review edits,
app/services/import_matching.py  confirm/reject, project/client match suggestions
      |
app/core/import_extraction.py    deterministic candidate extraction (pure)
app/core/import_normalization.py deterministic value normalization (pure)
      |
app/importers/*                  one class per file format, reads bytes -> RawExtraction
      |
app/models/import_staging.py     ImportedDocument / *Candidate / audit log ORM models
```

No importer, and no function in `app.core.import_extraction` or
`app.core.import_normalization`, ever opens a database session or writes
anything. No file under `app/ui/imports/` computes a normalized value or
runs a regex over document text — it only calls into `import_service`.

## 3. Supported file types

| Format | Extensions | Library | Notes |
|---|---|---|---|
| PDF | `.pdf` | PyMuPDF | Text vs. scanned detection; per-page table detection |
| Excel (modern) | `.xlsx`, `.xlsm` | openpyxl (`read_only=True`) | Streams rows; doesn't load the whole sheet |
| Excel (legacy) | `.xls` | xlrd | xlrd 2.x only reads `.xls`, which is exactly what's needed here |
| Excel (binary) | `.xlsb` | pyxlsb | Reads already-calculated cell values |
| Word | `.docx` | python-docx | Paragraphs, headings, tables |
| Word (legacy) | `.doc` | — | Explicitly unsupported (see §4) |
| Text | `.txt` | stdlib | Encoding fallback chain |
| CSV | `.csv` | stdlib `csv` + `Sniffer` | Delimiter auto-detected |
| Images | `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff` | — | Always staged as `OCR_REQUIRED` (see §5) |

Every importer is a small class implementing `BaseImporter.extract(path) ->
RawExtraction` (`app/importers/base.py`), registered by extension in
`ImporterRegistry` (`app/importers/base.py::build_default_registry`).
Adding a new format later is one new class plus one registration line —
nothing else in the pipeline changes. A file with no registered importer
is staged with `ExtractionStatus.UNSUPPORTED` and the message "Unsupported
file type" — never a crash.

## 4. Legacy `.doc` is not faked

`.doc` is a completely different (binary OLE) format from `.docx`, and
`python-docx` cannot open it. Rather than silently returning an empty
result or crashing, `WordImporter` immediately reports
`unsupported=True` with a message asking the user to save the file as
`.docx` and re-import. No converter is bundled in Phase 4.

## 5. Scanned PDFs and images: local OCR (OCR Phase 1)

`PDFImporter` extracts text page-by-page; if the average extractable text
per page falls below a small threshold, the document is flagged
`requires_ocr` instead of returning near-empty candidate data.
`ImageImporter` (`.png`/`.jpg`/`.tif`/...) *always* reports `requires_ocr`
— there is no text layer to read at all. Phase 4 stopped there
(`ExtractionStatus.OCR_REQUIRED`, manual entry only); **OCR Phase 1** adds
one thing on top: `app.services.import_service.run_extraction` now
attempts local, offline OCR (`app.core.ocr_extraction.extract_via_ocr`)
before giving up, still ending in `OCR_REQUIRED` if the OCR engine itself
is unavailable/fails, or `UNSUPPORTED` if the file can't even be opened.
No external/cloud OCR service is ever called — see §13.

The design is deliberately "OCR produces the exact same `RawExtraction`
every other importer already produces, then everything downstream is
unchanged":

- **`app.core.ocr_engine`** wraps Tesseract (`pytesseract`, optional
  dependency — see `pyproject.toml`'s `ocr` extra) behind an `OcrEngine`
  interface. `is_available()` is checked before anything is attempted; an
  engine that isn't installed degrades to `OCR_REQUIRED`, never a crash.
- **`app.core.ocr_extraction.extract_via_ocr`** rasterizes each page (via
  `pymupdf`, the same library `PDFImporter` already uses) and calls the
  engine once per page. A single bad page (render failure, engine
  exception, empty result) is caught and recorded per-page — it never
  aborts the rest of the document.
- **`app.core.ocr_table_reconstruction`** turns one page's OCR word
  positions into a grid (`ExtractedTable`, the same dataclass
  `pymupdf.find_tables()` already produces) using a conservative
  gap-based column heuristic. If the layout isn't confidently table-shaped
  it returns nothing rather than guessing — the page is instead flagged
  with a warning so BOQ lines can be added/corrected manually.
- **`app.core.import_extraction.extract_candidates`** (unchanged) then
  runs over OCR'd text/tables exactly as it runs over a clean text layer
  — the same label matching, the same `reconcile_net_tax_gross` VAT
  handling, the same BOQ header/column detection. OCR never gets its own
  parsing logic.
- **`app.core.ocr_confidence.compute_ocr_confidence_status`** is a small,
  three-state gate (`OcrConfidenceStatus`: `HIGH_CONFIDENCE` /
  `REVIEW_REQUIRED` / `BLOCKED`) computed on demand from the candidate's
  *current* values. `BLOCKED` — the quotation date and/or net value is
  still missing — is the one state that actually disables Confirm, both
  in `ImportReviewDialog` and defensively inside `confirm_import` itself
  (`ImportedDocument.extraction_engine == "ocr"` gates this; a
  deterministically-parsed document is unaffected). The other two states
  are informational badges only — human review remains the unconditional
  gate for every document regardless of confidence, exactly as in Phase 4.

This is still the same principle as password-protected PDFs and corrupt
files: **never fabricate structured data from a source that can't
actually be read** — OCR just moves the boundary of what "can be read"
covers, without changing what happens on either side of it.

## 6. Raw extraction vs. normalized candidate data

`RawExtraction` (`app/importers/base.py`) is exactly what a parser found —
flattened text and/or a list of tables, nothing interpreted. It is stored
verbatim as JSON on `ImportedDocument.raw_extracted_data` and never
discarded, even after review/confirmation.

`app.core.import_extraction.extract_candidates` turns that into
*candidate* business data:

- `QuotationCandidateFields` — quotation-shaped fields, found by scanning
  text lines and two-column table rows for a fixed set of labels
  ("Quotation Number", "Net Amount", "Total Including VAT", ...).
- `BoqRowCandidate` — one row per detected BOQ line, found by locating a
  header row (a row containing both a "description"-like column and a
  "quantity"/"rate"/"amount"-like column) and mapping columns positionally
  from there.

Both are stored on separate staging tables
(`ImportedQuotationCandidate`, `ImportedBoqLineCandidate`) rather than as
a single blob, precisely so they stay individually editable during review
and so `confirm_import` can read typed fields, not re-parse JSON.

`ImportedQuotationCandidate.raw_values` / `.field_confidence` are small
JSON dictionaries keyed by field name (e.g.
`{"net_value": "AED 1,250,000.00"}` / `{"net_value": "HIGH"}`) rather than
one column per field per concept — this keeps the raw-value audit trail
and the confidence signal available without doubling the table's column
count for a value most fields will never need edited-history detail on
beyond the general audit log (see §9).

### BOQ: extracted amount vs. calculated amount

Every BOQ row candidate keeps **both** `extracted_amount` (what the source
document said) and `calculated_amount` (`quantity * unit_rate`, via the
exact same `calculate_line_total` function the rest of the app uses —
never a second copy of that arithmetic). Neither ever silently overwrites
the other. When they differ by more than 1% (or 1 currency unit, whichever
is larger — a rounding allowance), the row is flagged
(`amount_flagged=True`) and shown in the review UI as "Check amount"
rather than "Amount matches" — a semantic label, not just a color, per the
same convention as `app.ui.variance_labels` (§9 there).

## 7. Confidence is categorical, never a fabricated percentage

`app.core.enums.ConfidenceLevel` is `HIGH` / `NEEDS_REVIEW` / `LOW` — never
a number like "98%". The deterministic label-matching parsers in this
phase have no statistically meaningful accuracy model to back a percentage
with, so presenting one would be worse than presenting nothing: it would
imply a level of certainty the system cannot actually justify. A field
found via a clean, unambiguous label match is `HIGH`; a value derived by
`reconcile_net_tax_gross` (see below) rather than directly extracted is
`NEEDS_REVIEW`; an unparsed or ambiguous value is `LOW`. A field the parser
never found at all has *no* confidence entry — it's simply blank for the
reviewer to fill in.

## 8. Normalization rules (`app/core/import_normalization.py`)

- **Whitespace**: collapsed and trimmed.
- **Currency**: a fixed alias table maps symbols/words ("Dh", "د.إ",
  "Dirham", "$", ...) to ISO codes. An unrecognized token is left `None`
  rather than guessed.
- **Units**: a small alias table ("SQM" → `m2`, "NOS" → `nos`, ...);
  anything unrecognized passes through unchanged rather than being
  dropped.
- **Dates**: tried against a fixed list of common formats, day-first where
  ambiguous (this business operates in the UAE). Unparseable text becomes
  `None`, never a wrong guess.
- **Amounts — the ambiguity rule the brief calls out explicitly**:
  `parse_amount` distinguishes a thousands separator from a decimal
  separator using digit-grouping heuristics (a trailing group of exactly 3
  digits after a single comma/dot is genuinely ambiguous — `"1,250"` could
  be `1250` or `1.250`). When genuinely ambiguous, `value` is `None` and
  `ambiguous=True` is set — **the value is never silently guessed**. Two or
  more thousands-style groups (`"1,312,500"`), or a clear 1–2 digit decimal
  remainder (`"1250,50"`), are unambiguous and parsed normally.
- **Net / tax / gross reconciliation**: `reconcile_net_tax_gross` fills in
  exactly one of the three values *only* when the other two are already
  present in the source (using `calculate_net_of_tax`/`calculate_gross_amount`
  from `app.core.financial_engine` — never a second copy of that formula).
  If only one of the three is present, **nothing is derived** — assuming a
  standard VAT rate to back-fill the other two would be a fabricated
  calculation, which this application never does with financial figures.

## 9. Duplicate detection

`app.services.import_service.compute_file_hash` computes a streamed
SHA-256 (reads in 1 MiB chunks, never loading a whole large file into
memory). `stage_document` looks up any prior `ImportedDocument` with the
same hash *before* creating a new one; if found, it raises `ValidationError`
naming the existing staging record, and the Import Center UI turns that
into a "this file was already imported — import again anyway?" prompt
(`app/ui/imports/imports_page.py::_import_documents`). Passing
`allow_duplicate=True` (only reachable after that explicit prompt) stages
a second, independent copy. Filename is never used for duplicate
detection — a renamed copy of the same bytes is still flagged; a
different file that happens to share a name is not.

## 10. Project / client matching (`app/services/import_matching.py`)

Heuristic, deterministic, substring/equality matching only — project
number equality, project/client name substring containment. No fuzzy
matching library, no AI. `suggest_project_matches`/`suggest_client_matches`
return candidates for the review screen to display; nothing is ever
merged automatically. The reviewer always explicitly picks an existing
record (via the same `ClientSelector`/`ProjectSelector` widgets used
elsewhere in the app) or creates a new one — there is no code path that
writes a `Client`/`Project` row without that explicit choice.

`suggest_quotation_matches` follows the same pattern for quotations —
*exact* reference-number equality only (a reference is an identifier, not
free text to fuzzy-match), returning the existing quotation plus its
current version's date/total so the reviewer can compare before deciding
whether to add a revision or create a new quotation. It is purely
advisory; see §10.1 for where the actual, enforced safety check lives.

### 10.1 Quotation-reference conflicts: a real archive finding, and how it's handled

A survey of Vision Contracting's real historical archive found the same
quotation reference appearing more than once with different dates and
totals, and no consistent revision-marking convention (`REV`, a letter
suffix, or nothing at all — see the regression tests' `VN/QU/412/18`
fixture, drawn directly from that archive). Reference number alone can
never identify which document is the current revision.

`Quotation.reference_number` already carries a database-wide unique
constraint, so a second, *independent* `Quotation` can never silently be
created under a reference that's already in use — `create_quotation`
converts that constraint violation into a clear `ValidationError`. The
gap was the *other* path: adding an incoming document as a **revision**
of an existing quotation (`quotation_service.create_quotation_revision`)
had no check at all comparing the incoming document's date against the
existing quotation's current one.

`confirm_import` now compares the incoming candidate against the target
quotation's *chronologically* current version
(`quotation_service.get_current_version` — ordered by `issued_date`, not
insertion order) before creating the revision:

- **Incoming date earlier** than the existing current version → blocked
  by default, raising `RevisionConflictError` (a `ValidationError`
  subclass carrying the reference, both dates, and both totals).
- **Same date, materially different total** → also blocked by default
  (same exception) — chronology can't resolve which is authoritative
  when the dates tie.
- **Incoming date later** → proceeds normally, no acknowledgement
  needed. This is the ordinary, expected workflow and must never be
  obstructed just because the reference already exists.

`confirm_import` accepts `acknowledge_revision_conflict: bool = False` to
let a reviewer explicitly proceed anyway — the same block-by-default,
explicit-override shape as `stage_document`'s `allow_duplicate` parameter.
In the UI, this is never a silently-set flag: `ImportConfirmationDialog`
catches `RevisionConflictError` specifically and shows the conflict in a
dialog the reviewer must explicitly answer "yes" to before retrying with
acknowledgement set; declining leaves the document unconfirmed and
creates nothing. An acknowledged conflict still only ever *adds* a new
`QuotationVersion` row — nothing is ever overwritten, and both documents'
data remain fully intact and independently queryable afterward.

Because a revision can now legitimately be confirmed out of chronological
order (once acknowledged), `financial_service._get_relevant_quotation_version`
also orders by `issued_date` rather than insertion order — the project's
"current quoted basis" always means the most recently *dated* version,
never whichever row happened to be written to the database last.

### 10.2 Related-but-differently-referenced quotations: a documented future requirement

The same real-archive review that found §10.1's case also found
`VN/QU/396/18` (7 Nov 2018, SAR 242,500) and `VN/QU/396B/18` (11 Nov 2018,
SAR 192,750) — same client, same subject ("Corrugated sheet work in Binex
Office"), almost certainly the same negotiation re-quoted lower four days
later. Unlike §10.1's case, the reference *strings* differ (`396` vs
`396B`), so `suggest_quotation_matches`' exact-equality matching correctly
does **not** connect them — and it must not be made to. Fuzzy/prefix
matching that treated "396" and "396B" as related would just as readily
connect two genuinely unrelated quotations that happen to share a numeric
prefix (`VN/QU/39/18` and `VN/QU/396/18`, for instance) — an
automatically-recognized-and-merged wrong pairing is a worse outcome than
today's "reviewer must notice it themselves."

This is deliberately **not implemented**: a same-client-plus-similar-
subject relationship signal is a real, useful thing for a future phase to
surface as an *additional advisory hint* (alongside, never instead of,
exact-reference matching) — but it needs its own design pass (what counts
as "similar enough," how it's presented, whether it's ever allowed to
pre-select anything) rather than a quick fuzzy-match bolt-on. Tracked here
as a known gap, confirmed twice now against real archive data, for a
future phase to pick up deliberately.

## 11. Audit trail (`ImportAuditLogEntry`)

Every staged document accumulates an append-only log:
`IMPORTED` (on staging) → `EXTRACTED` (after the deterministic pipeline
runs) → any number of `EDITED` entries (one per changed field, recording
old and new value as text) → exactly one of `CONFIRMED` or `REJECTED`.
This is what makes "what did the source document originally say, and what
did the reviewer change it to before confirming" answerable later, which
matters because this application's purpose includes analyzing historical
estimating accuracy over multiple years.

## 12. Financial safety (restated, since this is the part that must never regress)

- `confirm_import` calls `quotation_service.create_quotation` /
  `create_quotation_revision` — the *same* functions a manually-entered
  quotation uses. An imported quotation is exactly as "un-awarded" as a
  manually entered one until a user explicitly clicks "Mark Awarded" on
  the Quotations screen (Phase 3, unchanged).
- `candidate.net_value` becomes `QuotationVersion.quoted_value`. It is
  **never** written to `Project.contract_value`, `ActualCost`, or any
  other "real money moved" field.
- A BOQ's `extracted_amount`/`calculated_amount` becomes
  `BOQLineItem.total` — a *quoted* BOQ figure. It is never treated as
  `EstimatedCost` or `ActualCost`. (Turning an awarded project's BOQ into
  actual estimated-cost lines, if ever wanted, would be a distinct,
  explicit future feature — not something import does implicitly.)
- Nothing in `app/importers/`, `app/core/import_extraction.py`, or
  `app/core/import_normalization.py` imports or calls
  `app.core.financial_engine` for anything beyond its two pure net/tax/
  gross helper functions, reused rather than duplicated.

## 13. No AI, no network calls

Every extraction step in this phase is regex/label matching and
arithmetic — deterministic and inspectable. No call to Claude, any other
LLM API, or any external service is made anywhere in `app/importers/`,
`app/core/import_extraction.py`, or `app/services/import_service.py`.
AI-assisted extraction (as an aid *reviewed by a human*, never a silent
replacement for this pipeline) is explicitly future scope, after this
deterministic pipeline has been proven in real use.

## 14. Cross-platform considerations

- All paths are handled via `pathlib.Path`; nothing hard-codes a
  `/Users/...`, `/Applications/...`, `C:\...`, or a Windows registry path.
- File selection uses `PySide6.QtWidgets.QFileDialog`, which renders the
  native picker on both macOS and Windows without any platform-specific
  code in this application.
- Hashing reads files in binary chunks via `pathlib`/stdlib `hashlib` —
  no OS-specific file APIs.
- Tests use `tmp_path` (pytest's built-in per-test temp directory) and
  never assume a specific home directory, drive letter, or shell tool.
- `ImportedDocument.source_type` is `LOCAL` today and `GOOGLE_DRIVE` is
  already a defined (unused) value — so a future Drive integration is a
  new `source_type` and a new value for `original_path`
  (a Drive file ID/URL instead of a filesystem path), not a schema
  change to this table.

## 15. Error handling

`run_extraction` never lets an exception escape: a corrupted/malformed/
password-protected file, a moved-or-deleted source file, or an
unexpected importer bug all result in `ExtractionStatus.FAILED` (or
`UNSUPPORTED`/`OCR_REQUIRED` where that's the more precise status) with a
human-readable `extraction_error`, logged via `app/ui/logging_setup.py`
where relevant — never a crash of the whole import batch or the
application. The Import Center UI uses the same `run_guarded`/`guard`
helpers as the rest of the app (`app/ui/errors.py`) for every
service call that can raise `ValidationError` (e.g. staging a missing
file, confirming without selecting a client/project).

## 16. Known limitations (Phase 4)

- **Synchronous extraction**: `stage_document` runs `run_extraction`
  immediately, inline. This is fine at Phase 4's scale (a handful of
  documents at a time), and `run_extraction` is already a standalone
  function specifically so a future phase can move it onto a background
  worker/thread without changing its signature or the staging model.
- **BOQ review is inline table editing**, not a per-row dialog (unlike
  Phase 3's cost-entry dialogs) — reviewing dozens of extracted rows one
  dialog at a time would be impractical; each cell edit is still
  persisted (and audited) individually through `update_boq_line_candidate`.
- **Matching is substring/equality only** — no fuzzy matching, no
  phonetic matching, no AI. A project/client named very differently from
  what a document says simply won't be suggested (the user can still pick
  it manually).
- **One BOQ per quotation version** (enforced by the existing Phase 1
  schema's unique constraint) — a document containing multiple distinct
  BOQ tables currently stages all rows under one document and, on
  confirm, one `BOQ` per new `QuotationVersion`; representing genuinely
  separate BOQs on the *same* quotation version is not modeled.
- **Trade matching on BOQ rows is name-equality only**: `category_label`
  extracted from a document is matched to an existing `Trade` by exact
  (case-insensitive) name; anything else leaves `BOQLineItem.trade_id`
  unset rather than guessing.
- **No date-format ambiguity flag** (unlike amounts): day-first parsing is
  applied as a fixed business assumption rather than flagged per-value.
- **OCR (Phase 1) has been run against the real archive with real
  Tesseract** (a follow-up to the original design/build): 3 real scanned
  files (29 pages total, 16 distinct quotation references) were staged
  through the actual pipeline. Structured field capture was very low
  before the fixes below — a two-column "Label: Value" print layout
  frequently loses the label word or the colon to OCR noise, and even a
  perfect read often used label wording (bare `Reference:`) this
  project's original vocabulary didn't recognize at all. Three real,
  demonstrated defects were fixed as a direct result — see the items
  below; each one traces to a specific real-archive artifact, not a
  hypothetical.
  - **Fixed**: `parse_amount` could concatenate a percentage rate onto an
    adjacent monetary figure (`"5% charges SR 900.00"` → a fabricated
    `5,900.00` at `HIGH` confidence) — the real archive's page-11 ghosting
    artifact reproduced this exactly. `parse_amount` now tokenizes the
    input and never treats a `%`-suffixed token as part of the amount; two
    or more non-percentage candidates on one line/cell are now flagged
    ambiguous rather than guessed.
  - **Fixed**: `_FIELD_LABELS["quotation_number"]` didn't include bare
    `"reference"` or `"quotation reference"` — the real archive's actual
    label wording — so even flawless OCR never populated
    `quotation_number`. Both are now recognized (lowest priority, after
    every more specific label, to limit false positives from an unrelated
    `"Reference: <correspondence note>"` line elsewhere on the same
    document — a known, accepted trade-off, the same shape as `"attn"`
    already being accepted for `client_name`). `_pattern_for`'s separator
    class also now accepts `»`, the specific glyph Tesseract was observed
    substituting for a printed colon on this archive — not a general
    "any separator" relaxation.
  - **Fixed**: a single staged file that bundles multiple independent
    quotations (the tested 24-page archive file contains 16) could have
    its fields silently spliced across documents — `quotation_date` from
    page 1's quotation ending up on a candidate whose `net_value` (had it
    been captured) came from page 8's unrelated quotation. `run_extraction`
    now calls `find_distinct_quotation_references` before building a
    candidate; more than one distinct reference anywhere in the file stops
    candidate/BOQ creation entirely (`ExtractionStatus.
    MULTIPLE_QUOTATIONS_DETECTED`, raw OCR text still preserved, nothing
    confirmable) rather than guessing which document's fields belong
    together. No document-segmentation engine was built — this is a
    refusal, not a split.
  - **Fixed (adversarial-review round 1)**: reference-counting alone
    missed the case where one document's reference/date survive but a
    *different* document's date/total survive elsewhere in the same file
    — reproduced directly via code execution, not assumed. `run_extraction`
    now also counts distinct `quotation_date` values (a single quotation
    only ever has one issue date) as a second, independent multi-document
    signal alongside references.
  - **Fixed (adversarial-review round 2)**: `parse_amount` recognized only
    the ASCII hyphen as a negative sign — a real minus sign (U+2212) or en
    dash (U+2013), either producible by a PDF renderer/OCR engine, silently
    lost its sign and returned a *positive* value (e.g. `"−151,955.00"` →
    `151955.00`) instead of being rejected or correctly negated. Now
    recognized and normalized to the same negative `Decimal` a plain
    `"-151,955.00"` already produced.
  - **Residual, explicitly unresolved risk**: if a document loses *both*
    its reference and its date entirely while an unrelated total survives
    elsewhere in the same file, neither signal catches it — confirmed
    still reachable by direct construction in the second adversarial
    review. Real-archive evidence somewhat bounds the practical risk: across
    all 18 real quotation documents tested (29 pages, both plain-text and
    table-shaped totals), **zero** ever had a financial value (`net_value`/
    `tax_value`/`gross_value`) successfully captured on any page at all —
    the specific "clean total, lost reference and date" combination this
    gap requires has no observed instance in this archive, because
    financial-line capture itself is currently near-zero regardless of
    reference/date survival. This is not a reason to consider the gap
    closed — a cleaner scan, a different archive, or an OCR quality
    improvement could easily produce a clean total on an otherwise-unlabeled
    page. Closing it fully needs per-field source-page/line provenance
    tracking, a larger change than either adversarial pass's fixes;
    tracked here as the priority follow-up, not silently accepted.
  - **Superseded by sequential segmentation (below)**: the whole-document
    `MULTIPLE_QUOTATIONS_DETECTED` refusal above is now only the fallback
    for OCR text with no page structure at all. A page-tagged scan (the
    real archive shape) is segmented and reviewed per quotation instead
    of being refused outright — see §17.

## 17. Sequential quotation boundary detection (OCR Phase 2)

The real production workflow is batches of consecutive scanned
quotations in one PDF, in document order — not one file per quotation.
`app.core.import_segmentation` turns one OCR'd document's page-tagged
text into an ordered list of proposed page-range segments; each is
independently reviewed, locked, extracted, and confirmed exactly like a
Phase 4/OCR-1 document always was, just scoped to its own pages.

**Pipeline**: `stage_document` → OCR (`extract_via_ocr`, unchanged) →
`propose_segments` (new) → reviewer accepts/moves/splits/merges/excludes
each segment (`app.services.import_service`) → `lock_segments` slices the
document's raw OCR text per accepted segment
(`slice_raw_extraction_to_pages`) and runs the *unmodified*
`extract_candidates` on each slice → the existing
`ImportedQuotationCandidate`/review/confirm flow, unchanged, once per
segment (`confirm_import`/`reject_import` now take an optional `segment`
argument; omitted, they behave exactly as before).

**The core safety invariant is structural, not a downstream check**: a
segment's candidate is built only from a `RawExtraction` that
`slice_raw_extraction_to_pages` has already reduced to that segment's own
pages — a page outside its range is never present in the text/tables
handed to `extract_candidates`, so it cannot be extracted from. No
proposed boundary — including a HIGH-confidence one — is ever accepted
automatically anywhere in this application; every segment must pass
through an explicit reviewer action (`accept_segment`/`exclude_segment`)
before `lock_segments` will build its candidate.

**Boundary detection** (`detect_segments`) is intentionally not a fixed
page-distance rule (a legitimate quotation may span many pages): a page
starts a new segment only when its own reference and/or date genuinely
differ from the currently open segment's — reference differing is HIGH
confidence, a date-only difference with no corroborating reference on
that page is LOW (surfaced for review, never silently absorbed either
way — see `_classify_boundary`'s docstring for the exact reasoning,
including why a first-seen date with a *confirmed* matching reference is
safely absorbed as continuation, while a first-seen date with *no*
reference at all is not). Anything else (no signal, a blank/attachment
page, a repeated reference) continues the open segment by default — a
missed header can only ever under-split, never mis-attribute a page.

**Real-archive validation** (the same 24-page, 18-quotation archive used
throughout OCR Phase 1's adversarial reviews, using the already-captured
real Tesseract 5.3.4 output): segmentation proposed **11 segments**
against the archive's known 18 quotation documents (16 distinct
references, including the real `444/18` → `444 REV/18` and
`VN/QU/412/18` revision pairs) — correctly splitting the well-labeled
majority (9 of 11 proposed segments each map to exactly one real
document), but two segments under-split: pages 5–11 (7 pages) merge
`VN/QU/417/18`, two drawing pages, `VN/QU/412/18`'s first occurrence,
`VN/QU/406/18`, and an ambiguous bleed-through page into one segment,
because none of the intervening documents' own reference lines were
recognized by OCR at all on this archive; pages 12–13 similarly merge
`VN/QU/401/18` with an unrelated delivery note. Zero LOW-confidence seams
were produced in this run (every boundary segmentation *did* find was
reference-based and unambiguous) — the under-splitting is a case of no
signal being found at all, not a low-confidence one being wrongly
trusted, and is exactly the failure mode the design predicted: a missed
header under-splits rather than mis-attributes.

**Verified**: every field on every one of the 11 segments' extracted
candidates traces to a page within that segment's own range (checked
directly against the sliced text, not merely asserted) — the core
invariant held with no exceptions on this real run. **Also honestly
found**: within the one 7-page under-split segment (pages 5–11), the
resulting candidate combined `VN/QU/417/18` (page 5's reference) with a
date that actually belongs to `VN/QU/406/18` (page 10, per the archive's
visual ground truth) — the existing within-segment multi-reference safety
net (unchanged from Phase 4/OCR-1) did not catch it, because only *one*
reference was ever OCR-recognized across those 7 pages, so
`find_distinct_quotation_references` saw no conflict to flag. This is not
a regression — it is exactly the pre-segmentation flat-document risk,
just now bounded to one merged segment instead of the whole file — and it
is not confirmable in this specific run only because, consistent with
every prior finding against this archive, **zero** of the 11 segments'
candidates captured a financial value at all. A cleaner scan that
recovers financial values on an under-split segment's pages would not
automatically trip this particular safety net either. Closing this fully
needs the same per-field page-provenance tracking already named as OCR
Phase 1's priority follow-up (§16) — segmentation meaningfully shrinks the
blast radius (11 candidates instead of 1) but does not, by itself,
guarantee zero cross-quotation field mixing when its own boundary
detection misses a transition. The correct mitigation today is reviewer
diligence: a long or multi-quotation-looking segment should be split
further with `split_segment` before locking, exactly as the boundary
review screen is designed to prompt.

**Fixed (final adversarial review)**: the residual risk named above was
reproduced as a genuine, confirmable defect — constructed directly (not
assumed) and confirmed end-to-end including an actual `QuotationVersion`
write, then reverted: quotation A's own reference/date (page 1) combined
with an entirely unidentified document's total (a later page, with
neither its own reference nor date recognized at all) reached
`HIGH_CONFIDENCE` and confirmed successfully, because
`find_distinct_quotation_references`/`_dates` only compare values they
actually recognized — by construction, none of the "other document"'s
fields were. `app.core.import_segmentation.find_field_pages` now locates
which page each field actually came from (reusing the same per-page
`extract_quotation_candidate` calls `detect_segments` already makes — no
change to that function itself, or to `detect_segments`/boundary proposal
itself). When a financial field's page shares no page with the segment's
own reference or date, its confidence is downgraded from HIGH to LOW, and
`app.core.ocr_confidence.compute_ocr_confidence_status` now treats a LOW
`net_value` as BLOCKED — the same structural gate (disables Confirm,
enforced defensively inside `confirm_import`) a genuinely *missing* value
already used, not a cosmetic confidence label.

**Accepted trade-off, stated plainly**: this cannot distinguish "a
different, unidentified document's total" from "this same quotation's own
total, legitimately printed on a later page with nothing repeated in
between" — no textual signal distinguishes them, and inventing one (a
page-distance threshold, a layout heuristic) was explicitly out of scope.
A genuinely long, single quotation is still correctly proposed as *one*
segment (segmentation itself is unaffected), but its total is now flagged
for explicit reviewer sign-off rather than silently auto-confirmed.
Verified this is friction, not a dead end: a real edit to the flagged
field clears it and confirmation proceeds; a plain, unchanged
resubmission (what a `QLineEdit`'s `editingFinished` fires on ordinary
focus-out, edited or not) deliberately does *not* clear it, so the gate
cannot be defeated by incidental UI interaction.

Re-validated against the real archive with this fix applied: all 11
proposed segments remain `BLOCKED` (0 confirmable either way, unchanged
from before this fix — this archive's near-total absence of captured
financial values means the fix's specific contribution wasn't the only
thing blocking any of them in this run), and the new check independently
flagged 2 of the 11 segments' financial fields on page-mismatch grounds,
confirming it fires correctly against real OCR output, not just
constructed text.

No quotation was confirmed from the real archive during this validation
— segments were proposed, accepted, and locked only, to exercise the
full persistence path; `confirm_import` was never called against it.

**Not implemented by this change** (explicitly out of scope): Purchase
Order import, award-status derivation, or any dashboard/analytics
surfacing of the Quotation → PO → Award chain. `confirm_import` and
`quotation_service.mark_awarded` are untouched — a confirmed segment
still only ever produces a *quoted* `QuotationVersion`, never an awarded
`Project.contract_value`.
- **BOQ table reconstruction from OCR is a best-effort heuristic**
  (gap-based column splitting on word positions), not true table
  structure detection — it declines (rather than guesses) when a page's
  layout is inconsistent, but a scan with unusual column spacing may
  still be flagged "uncertain" more often than a human would consider
  necessary. Confirmed conservative against the real archive: 0/6+ real
  BOQ tables were reconstructed, but in every case that meant zero rows,
  never misaligned/fabricated ones. Manual BOQ entry remains available in
  every case.
- **No conflict detection for multiple distinct totals on one page**: if
  a document prints more than one "total"-shaped label with different
  values, the existing first-match-wins label matching (unchanged from
  Phase 4) picks one; there is no explicit multi-value warning yet. Human
  review remains the safety net regardless of which value was picked up.
  Deliberately not addressed in the OCR-safety-fix pass (out of its
  narrow scope) — a candidate future improvement.
- **No automatic relationship detection between differently-referenced
  quotations** (e.g. `VN/QU/396/18` vs `VN/QU/396B/18`, same client, same
  subject, four days apart — a real archive pair) — see §10.2. Deliberately
  not implemented; exact-reference matching must not be loosened to guess
  at this.
- **No Arabic-language verification**: Tesseract supports Arabic language
  packs, but this was not exercised against real archive documents in
  this environment (see the OCR design review's open questions).

## 18. Production OCR performance and real-archive extraction (OCR Phase 4)

A follow-up measurement-then-fix pass, scoped to three things only:
OCR performance, real-archive extraction gaps, and a VAT normalization
business rule. No AI/network calls added, `financial_engine.py`
untouched, no PO/award/invoice/dashboard work — see §16-17 for everything
already in scope before this phase.

### 18.1 Bottleneck: rendering DPI, not OCR itself

Measured directly: rasterizing a page at `pymupdf`'s `get_pixmap(dpi=300)`
and then running Tesseract on it, for a real archive page, took 30-40s —
almost all of it inside Tesseract, not rendering. The real archive's
pages declare a `MediaBox` (page size) that does not match their embedded
scanned image's actual native pixel resolution — e.g. a page sized
"26.5 x 41.5 inches" wrapping a 1910x2986px image (a ~72 DPI scan). The
fixed `_RENDER_DPI = 300` constant rendered every page at 300 DPI against
that inflated page size regardless, producing ~10x more pixels than the
source actually contains for Tesseract to process, for no accuracy gain.

**Fix**: `_effective_render_dpi` (`app/core/ocr_extraction.py`) computes
each page's own DPI from its dominant embedded image's native resolution
(`native_pixels / (mediabox_points / 72)`), clamped to `[150, 300]`. A
normally-scaled PDF (native resolution >= 300 DPI) reproduces the old
fixed 300 DPI exactly, by construction — zero rendering change on a
normal scan. Falls back to 300 DPI unchanged whenever there's no
embedded image to measure, or any error reading one.

**Measured on 3 real archive pages, this container** (a direct
render+OCR timing, old fixed 300 DPI vs. the new computed DPI, same
Tesseract call):

| page | old (300 DPI) | new (computed) | speedup | chars (old→new) | confidence (old→new) |
|---|---|---|---|---|---|
| 1  | 29.9s @ 7959x12442px | 8.4s @ 3980x6221px (150 DPI) | 3.6x | 1365→1506 | 71.2→70.0 |
| 10 | 37.1s @ 8259x14509px | 9.9s @ 4130x7255px (150 DPI) | 3.8x | 2159→1984 | 67.5→73.8 |
| 13 | 40.4s @ 8521x15117px | 11.7s @ 4261x7559px (150 DPI) | 3.5x | 2955→2835 | 80.2→83.6 |

No accuracy loss on average (2/3 pages higher confidence; the third has
fewer characters but higher confidence too — reported as measured, not
rounded up). One genuine, narrow accuracy trade-off was found on a
different real page during the full re-run (§18.4) — reported there, not
hidden. (An independent, larger 8.9x-10x figure was measured for the
same fix in an earlier session on different underlying hardware; this
section's 3.5x-3.8x is a fresh, direct re-measurement on this container,
reported instead of the old number so the ratio here is never inflated
beyond what was actually re-verified.)

**Whole-pipeline re-run, all 3 real files (29 pages) through
`stage_document` end to end** (OCR + segmentation + candidate-building +
DB writes, this container, DPI fix applied): 317s total, 10.93s/page
average — down from an extrapolated ~37s/page at the old fixed DPI (same
3-sample ratio applied to the full pipeline's small fixed per-page
overhead). No `confirm_import` call anywhere in this measurement; no
business records created.

### 18.2 OCR result reuse: already correct, nothing to change

Confirmed (again, directly against the code, not assumed): `extract_via_ocr`
is called exactly once per staged document (`import_service.py`,
`run_extraction`), and `OcrEngine.ocr_image` is called exactly once per
page. The full OCR result is stored once in
`ImportedDocument.raw_extracted_data`; segmentation (`propose_segments`,
`lock_segments`), field-page lookup (`find_field_pages`), and candidate
rebuilding all deserialize and slice that one stored result — none of
them re-invoke the OCR engine. This means "reuse/caching" contributes
**no additional speedup** at any scale: the entire benefit of not
re-OCR'ing was already built into the architecture before this phase.
The scale estimates in §18.5 are pure per-page-OCR-cost estimates for
exactly this reason.

### 18.3 Extraction fixes (real-archive evidenced, `import_extraction.py`)

Three narrow label/pattern additions, each traced to a specific real
archive OCR line (not invented):

- **Table-totals pipe separator + parenthetical currency annotation**:
  real BOQ totals rows OCR as `"Total (SAR) | 51,644.77"` /
  `"Sub Total (SAR) | 49,185.50"` — a table-cell `|` instead of a colon,
  with the currency printed inside the label's own header cell. Neither
  shape matched the previous `[:\-»]` separator class or the bare-label
  assumption. `_pattern_for` now accepts `|` and `—` (em dash — also a
  real, observed OCR misread, alongside the existing `»` one) as
  separators, one-or-more of them together (a real doubled-separator
  shape, `"— :"`, was also found), and an optional `(...)` annotation and
  trailing `.` between the label and the separator.
- **"Kind Attn." client label**: every real archive document that labels
  its client contact prints `"Kind Attn."` (with the period) — bare
  `"Attn"` never once appears at the start of a line unprefixed anywhere
  in the archive. `client_name` was therefore never populated from *any*
  real document despite `"attn"` already being a recognized alias.
  `"kind attn"` is now a higher-priority label alongside it.
  Re-verified against the real 24-page archive: `client_name` now
  populates on 8 of 10 real segments (the remaining 2 have a genuinely
  garbled OCR line for this field — `client_name` correctly stays `None`
  there rather than guessing).
- **Drawing/attachment pages verified safe, no change needed**: directly
  checked the real archive's two drawing pages (floor plans with
  dimension callouts) against every recognized field label —
  zero matches, before or after this phase's pattern changes. Label
  matching is line-start-anchored and requires the literal label text, so
  a dimension/measurement number never gets extracted as a financial
  value; this was already true and remains true. No fix was needed here,
  and this was verified, not assumed.
- **Known, deliberately unresolved gap**: a table-totals label preceded
  by OCR-garbled leading noise (`"eae Total (SAR) |__22,050.00"`,
  `"Ee | Total (SAR) 168,495.00"`) still doesn't match — the line-start
  anchor was not loosened to reach it, because that would risk matching
  label text embedded mid-sentence (the same risk the bare-whitespace-
  separator restriction already guards against). These cases correctly
  fall through to the missing-`net_value` safety gate (`BLOCKED`) instead
  of being guessed.

### 18.4 VAT business rule: "genuinely not determinable" → SAR 0.00

Real archive VAT wording, captured from the actual saved OCR output:
explicit amounts (`"VAT 5% SAR 1,125.00"`, `"5% Vat SAR 325.00"`, etc.,
already extracted normally, untouched by this change); and VAT-excluded/
no-amount wording (`"VAT 5% not included in our offer"`, `"5% VAT will
be charged extra"`) on roughly half of the real documents tested — these
state VAT is excluded but print no absolute SAR figure anywhere. No
genuine "VAT-inclusive" wording (prices already including VAT, no
separate line expected) was found anywhere in the real archive, but the
business rule still had to support it for future documents.

`_apply_vat_determination_when_undetermined` runs only when `tax_value`
is still unset after the existing label scan and `reconcile_net_tax_gross`
(unmodified). It classifies the *reason* into two distinguishable
internal states, tagged in `raw_values["tax_value_basis"]` (the existing
persisted JSON field — no schema/migration needed):

- `"vat_inclusive"` — explicit inclusive wording found. `tax_value` stays
  `None` (never split out of the total by assuming a rate); no `SAR 0.00`
  is applied here, since this is not the "undeterminable" case.
- `"undetermined_zero_applied"` — no VAT amount is determinable by any
  means (VAT-excluded wording with no figure, or nothing at all). Per the
  business rule, `tax_value` is set to a fixed `Decimal("0.00")` — never
  a rate-derived figure — and flagged `ConfidenceLevel.LOW`, so the
  candidate requires review rather than reading as certain. The matched
  excluded-wording phrase, if any, is recorded in
  `raw_values["tax_value_note"]` for audit/traceability.

Neither state ever multiplies a stated rate by `net_value` to invent an
amount, and `financial_engine.reconcile_net_tax_gross` itself is
unmodified — a real, derivable tax figure (from known net+gross) still
always takes priority over the business-rule default.

Re-verified against the real 24-page archive's 10 real segments: 6 got
`"undetermined_zero_applied"` with the real matched wording captured
verbatim in `tax_value_note` (e.g. `"VAT 5% not includ"`, `"VAT will be
charged extra"`); one derived a real tax figure algebraically as before
(unaffected); none fabricated a rate-derived amount.

**One genuine, narrow accuracy trade-off found during this re-run**: on
one real page, the lower-DPI rendering caused Tesseract to misread a
leading "5" as "$" in `"Total (SAR) | 51,644.77"` → `"$1,644.77"`,
producing a materially wrong `gross_value`. This is a real, if narrow,
cost of the DPI reduction — reported honestly, not hidden. It has no
safety impact: this segment (already carrying an unrelated cross-page
bleed-through issue — see §10.1/ground truth page 11) was already
`BLOCKED` by the existing missing-mandatory-field/LOW-confidence gate, so
the wrong figure was never at risk of silently reaching confirmation.

### 18.5 Scale estimate (measured throughput, not guessed)

Using the measured 10.93s/page whole-pipeline average (§18.1) and this
archive's real page/quotation ratio (24 pages / 18 quotation documents +
drawings + a delivery note ≈ 1.5 pages/quotation — stated explicitly as
this archive's own ratio, not a general constant):

| quotations | pages (≈1.5/doc) | new DPI (10.93s/page) | old fixed DPI (≈37.2s/page, extrapolated) |
|---|---|---|---|
| 100    | 150    | ~27 min   | ~93 min (1.6 hr) |
| 1,000  | 1,500  | ~4.6 hr   | ~15.5 hr |
| 5,000  | 7,500  | ~22.8 hr  | ~77.5 hr (3.2 days) |
| 10,000 | 15,000 | ~45.5 hr  | ~155 hr (6.5 days) |

Both columns assume today's **synchronous, one-document-at-a-time**
staging (`stage_document` calls `run_extraction` inline — the existing,
already-documented §16 limitation, unchanged by this phase). OCR result
reuse contributes no additional reduction beyond what's already in these
numbers (§18.2). At 5,000-10,000 document scale the synchronous model is
the real remaining constraint, not per-page OCR cost — background/worker
processing (already flagged in §16 as a future-phase change, not
attempted here) is what closes that gap, not further DPI tuning.

### 18.6 Explicitly not done in this phase

No change to `import_segmentation.py`'s boundary-detection signals (the
`client_name`/"attn" boundary-signal idea from the prior review's
recommendations was left out — it serves segmentation usability, not
this phase's three explicit tasks, and this phase's own re-run shows the
DPI fix already shifted some real boundaries incidentally, which is
enough segmentation-side change to observe in one pass). No PO import, no
award-state changes, no invoice import, no dashboards. No change to
`app/core/financial_engine.py`. No new AI/ML/network-based extraction.

## 19. Targeted real-archive extraction improvements (OCR Phase 4, round 2)

A business acceptance test run against the real archive (§18's fixes
applied) found the pipeline safe but with too much manual work: only 4 of
10 produced segments had correct boundaries, 6 bundled 2-3 real
quotation documents together, and two confirmed real splices were
observed (both correctly `BLOCKED`, never reaching a business record).
This round fixes three specific, narrowly-scoped real-archive problems
traced to exact OCR lines — no broad re-review, no new heuristics beyond
what the evidence below required.

### 19.1 Segmentation under-splitting — root-caused, not just described

Directly inspecting the real OCR text at all 6 under-split boundaries
found the actual cause was almost always upstream, in
`import_extraction.py`'s label matching, not in `detect_segments`'s own
decision logic:

- **4 of 6 cases**: a real, additional OCR colon-substitution the
  separator class didn't accept yet. Beyond the previously confirmed
  `»`, `—`, `|`, the archive also prints `>` ("Reference > VN/QU/389/18",
  "...VN/QU/396B/18", "...VN/QU/420/18") and `=:` ("Reference =:
  VN/QU/395/18", "...VN/QU/412/18"). Adding both to `_pattern_for`'s
  separator class (same narrow, single-character-class precedent as
  every prior addition) let the existing, unmodified boundary logic
  detect these references on its own — no segmentation-layer change was
  needed for these four.
- **1 of 6 cases** (pages 5–9: VN/QU/417/18, 2 drawing pages,
  VN/QU/412/18): a harder failure — VN/QU/412/18's reference *and* date
  labels are both **entirely** lost to OCR noise ("» VN/QU/412/18", "-
  Nov 27, 2018." — not just the separator, the whole label word). No
  label text survives to match against at all. `import_segmentation.py`
  adds a narrow, segmentation-only fallback: `_bare_reference_hint`
  recognizes a bare separator glyph directly followed by nothing but a
  Vinco-reference-shaped value ("VN/QU/412/18", "444 REV/18") and
  nothing else on the line. Per the explicit conservative requirement,
  this can **only ever** produce a LOW-confidence proposal — never a
  silent merge, never a silently-confirmable HIGH-confidence split — and
  it never populates the resulting segment's own `quotation_number`
  (only a real label match does that); a reviewer still confirms the
  reference by hand. The 2 drawing pages in between stay attached to the
  open segment (no identity signal of their own) — the already-approved,
  conservative drawing-page policy, not a new gap.
- **1 of 6 cases** (pages 10–11: VN/QU/406/18 + an unrelated
  bleed-through page with no reference or date of its own at all): **not
  fixed**. No narrow, safe signal was found that could catch this
  without risking false splits elsewhere — a page with genuinely no
  identity information cannot be safely told apart from a legitimate
  continuation page using only reference/date signals, and inventing a
  new signal class (e.g. "a second financial-summary block") on the
  strength of one observed instance would be exactly the kind of
  speculative heuristic this project avoids. Per the explicit
  requirement that a false negative boundary is preferable to a silently
  wrong split, this remains one segment — a known, deliberately
  unresolved limitation, tracked here rather than silently accepted.

All 6 real cases are directly reproduced as regression tests in
`test_import_segmentation.py` (constructed from the actual real OCR
text), including the one left deliberately unfixed.

### 19.2 Date parsing tolerates harmless trailing OCR punctuation

`parse_date_maybe` (`import_normalization.py`) used exact `strptime`
matching with zero tolerance for anything after the expected pattern.
The real archive's dates almost universally OCR with the source
sentence's own trailing punctuation still attached ("Nov 19, 2018.",
"November 20, 2018.", "November 29,2018."), so a date whose label was
already correctly found and matched was silently discarded anyway.

Fix: if the exact match fails, retry once with only a trailing `.`/`:`/
`;` run stripped from the end (`_TRAILING_HARMLESS_PUNCTUATION_RE`) —
never touching the internal "Month DD**,** YYYY" comma, since that comma
is never at the end of the string. Never broadens which date *formats*
are accepted, never rescues genuinely unparseable text (confirmed by a
test: "Nov 19, 2018abc." still returns `None`).

### 19.3 VAT extraction: two more real archive wording shapes

The business acceptance test found roughly half of all explicit VAT
figures were missed — not a business-rule problem, an upstream label-
matching gap. Direct inspection of the real archive's VAT lines found
two recurring shapes `_pattern_for`'s generic label mechanism cannot
reach at all, because there is no separator character between the label
and the rate:

- `"VAT 5% SAR __ 1,125.00"`, `"VAT 5% SAR 3,600.00"` — rate directly
  after the label, no separator.
- `"5% Vat SAR 325.00"` — rate printed *before* the label.

`_find_vat_amount_without_separator` (two new, narrow regexes,
`import_extraction.py`) matches these shapes specifically, and only ever
runs as a fallback when the normal label scan found nothing — it never
overrides an already-found value, and both patterns require a real
trailing decimal amount, so neither can ever fire on excluded/inclusive
wording with no amount ("VAT 5% not included in our offer", "5% VAT will
be charged extra" — confirmed by tests). This is pure pattern matching
over what is already printed on the page; no rate is ever multiplied
against `net_value` to invent a figure, and `financial_engine.py` is
untouched.

### 19.4 Safety tightening required by the date fix's own side effect

Fixing dates (§19.2) had one real, concerning interaction: a `net_value`
that `reconcile_net_tax_gross` derives algebraically (from `tax_value` +
`gross_value`, because it was never independently read off any single
page) is flagged `NEEDS_REVIEW`, not `LOW` — and because it was never
found via a direct per-page label match at all,
`_flag_financial_fields_without_identity_corroboration`'s page-comparison
check has nothing to compare (it only inspects fields `find_field_pages`
found directly). Before this phase, the real archive's one remaining
un-split, genuinely-spliced segment (§19.1's pages 10–11 case: a
`net_value` derived from one document's `tax_value` and a different,
unrelated document's `gross_value`) happened to still be `BLOCKED` —
but only because its date was *also* unparseable, a coincidence, not a
real safety mechanism. Fixing that date correctly (§19.2) would have
"unblocked" this specific wrong, spliced figure into `REVIEW_REQUIRED`,
which — unlike `BLOCKED` — does not disable the Confirm button.

Caught by re-running the real archive after implementing, not assumed.
Fixed at the source of the actual gap: `app/core/ocr_confidence.py`'s
`compute_ocr_confidence_status` now treats a `NEEDS_REVIEW` `net_value`
exactly like a `LOW` one for the `BLOCKED` gate — a derived-not-read
figure must always require explicit human confirmation, independent of
why it wasn't independently found. Verified against the real archive:
this segment is `BLOCKED` again after the fix. This is the smallest
possible fix for the actual gap (one condition, one existing field), not
a reversal of the date fix itself, which remains correct and necessary.

### 19.5 Real-archive re-validation

Re-running the full real archive (fresh Tesseract OCR, this session)
after all of §19.1–19.4:

| Metric | Before (§18 baseline) | After |
|---|---|---|
| Segments produced | 10 | 15 |
| Correctly bounded | 4 | 13 |
| Under-split segments | 6 / 10 | 2 / 15 |
| Confirmed real splices | 2 | 1 (the pages 10–11 case, §19.1 — still correctly `BLOCKED`, not `REVIEW_REQUIRED`) |

Cases fixed and verified against the real archive: VN/QU/412/18 (1st
occurrence, pages 8–9) now has its own segment; VN/QU/389/18 (pages
14–15) correctly separated from the delivery note (page 13);
VN/QU/396B/18 (page 17) separated from VN/QU/403/18; VN/QU/395/18 (page
20) separated from VN/QU/390/18; VN/QU/419/18 (page 21) separated from
VN/QU/420/18. VAT figures newly extracted correctly on real pages:
1,125.00 (VN/QU/403/18), 325.00 (VN/QU/395/18), 3,600.00
(VN/QU/420/18) — all previously defaulted to the undetermined-zero
business rule despite being explicitly printed.

**Correction to this section's own first draft, caught by re-checking
the real output rather than trusting the synthetic test alone**: pages
22–24 (case 6) is only *partially* fixed. VN/QU/419/18 (page 21) is now
correctly its own segment, but VN/QU/420/18 (page 22) and VN/QU/412/18's
2nd occurrence (pages 23–24) are **still merged** — the constructed
regression test for this case used clean text and passed, but the real
line is `"ee Reference =: VN/QU/412/18"`: the same **leading OCR noise
before the label** pattern already identified and deliberately left
unfixed in §18.3 (`"eae Total (SAR) |__22,050.00"`), not a flaw in the
`=` separator fix itself (confirmed working correctly on page 20's clean
`"Reference =: VN/QU/395/18"`). Widening the line-start anchor to reach
it carries the same over-broad-matching risk already declined once; not
attempted again here for the same reason. This is now the second
real-archive instance of that specific limitation (pages 10–11 was the
first) — both remain correctly `BLOCKED`, both are genuine, tracked
residual gaps, not silently accepted.

## 20. Targeted net/gross extraction improvement (OCR Phase 4 round 3)

Round 2's business acceptance found the main remaining usefulness
problem was net/gross financial totals frequently missing even on
correctly-bounded segments. This round root-caused every miss on the 13
correctly-bounded real segments against the actual saved OCR text before
changing anything, grouped the misses into two fixable root causes and
several genuinely unfixable ones, and implemented only the fixable ones.

### 20.1 Diagnostic: real archive, per correctly-bounded segment

| Pages | Doc | Net (before → after) | Gross (before → after) | Root cause if missing |
|---|---|---|---|---|
| 1–2, 3–4 | 444REV/18, 444/18 | N/A (rate-based, none printed) | N/A | — |
| 5–7 | VN/QU/417/18 | missing → missing | missing → missing | **Unfixable**: the "cost of the work..." sentence is split mid-word across two non-adjacent OCR lines ("...wit" / "h labor and..."), and the VAT amount is orphaned on its own line — a reading-order/layout defect, not a pattern gap |
| 8–9 | VN/QU/412/18 (1st) | missing → missing | N/A | **Unfixable**: the totals line is lost to OCR noise entirely (no recoverable digits) |
| 12 | VN/QU/401/18 | N/A (rate-based) | N/A | — |
| 13 | delivery note | N/A (not a quotation) | N/A | — |
| 14–15 | VN/QU/389/18 | missing → **16,850.00** ✓ | missing → **17,692.50** ✓ | Fixed: "cost of the work" sentence + separator-less "Total Amount" |
| 16 | VN/QU/403/18 | missing → **22,500.00** ✓ | missing → **23,625.00** ✓ (via existing reconciliation, net+tax) | Fixed |
| 17 | VN/QU/396B/18 | missing → **192,750.00** ✓ | N/A (no separate total printed) | Fixed |
| 18 | VN/QU/396/18 | missing → **242,500.00** ✓ | N/A | Fixed |
| 19 | VN/QU/390/18 | already correct (38,400.00) | missing → missing | **Unfixable**: real VAT/Total lines are reading-order scrambled — the Total line's separator is a bare `;` with the amount missing entirely, and the VAT amount sits on its own unlabeled line |
| 20 | VN/QU/395/18 | missing → **6,500.00** ✓ | missing → **6,825.00** ✓ | Fixed |
| 21 | VN/QU/419/18 | missing → missing | missing → missing | **Unfixable**: the entire 2-row BOQ table area is garbled — no "Sub total"/"VAT"/"Total" label survives at all |

5 of 8 real, printed-but-missed net values fixed (389, 403, 396B, 396,
395); 3 genuinely require table/layout reading-order reconstruction, not
a narrow pattern — exactly the "stop and report" case named in this
task, applied per-page rather than to the whole effort, since it would
be wrong to let 3 hard pages block fixing the 5 pages that had a real,
narrow, safe fix available.

### 20.2 Root causes (grouped) and fixes made

**Root cause 1 — net value printed only as a fixed boilerplate sentence,
never a "Label: Value" line.** The archive's own recurring wording ("The
cost of the work with labor and materials SAR 22,500.00", and the
variant "The cost of the work labor charges only SAR 6,500.00") can
never be reached by `_FIELD_LABELS`/`_pattern_for`, which require a
literal label word before a separator. Fix: `_find_net_value_from_cost_sentence`
(`import_extraction.py`) searches for the fixed phrase "cost of the
work" (via `search()`, not an anchored `match()` — safe because that
phrase is specific business wording, not a coincidence risk) through to
a real trailing decimal amount. Only ever a fallback when the normal
scan found nothing for `net_value`; never overrides an existing value;
confirmed by test not to fire when the amount is missing or the sentence
is split across lines (the page 5 case).

**Root cause 2 — "Total"/"Total Amount" directly followed by a currency
token and amount, no separator character at all** ("Total Amount SR
17,692.50", "Total SAR 6,825.00"). Fix: `_find_gross_value_without_separator`,
same fallback-only design. Deliberately kept line-start-anchored (unlike
root cause 1's pattern) since "total" alone is common enough prose that
the anchor is worth keeping — this means it does not reach the same
leading-noise-before-label limitation already documented (`"3 Total SAR
23,625.00"`), which stays a known, accepted gap, not newly introduced.

**Bonus, not a new fix**: 403's gross value (23,625.00) was recovered
purely through the *existing, unmodified* `reconcile_net_tax_gross` —
once its net (22,500.00) was found by fix 1 and its tax (1,125.00) was
already found (round 2), the pre-existing reconciliation logic derived
gross algebraically, exactly the explicitly-approved case this task
permits. No new arithmetic was written.

### 20.3 A new fix, caught by the same old safety net

Real-archive re-validation surfaced a genuine new failure mode: on the
still-unfixed pages 10–11 splice (VN/QU/406/18 + an unrelated
bleed-through page), the new "cost of the work" pattern now finds a
real, literal figure — but it's the bleed-through page's own value
(18,000.00), not 406's real total (49,185.50, itself unrecoverable
behind leading-noise). Reproduced directly as a regression test
(`test_cost_of_the_work_sentence_on_an_unidentified_page_cannot_splice_either`):
the pre-existing, unmodified `_flag_financial_fields_without_identity_corroboration`
check catches this exactly as designed — the value is found on a page
sharing no identity with the segment's own reference/date, so it's
downgraded to `LOW` and the segment stays `BLOCKED`. Nothing new was
needed here; this is the intended behavior of an existing safety
mechanism extending automatically to a new extraction path, precisely
because that mechanism was never bypassed or special-cased.

### 20.4 A newly-discovered, out-of-scope date-parsing gap

Diagnosing why several now-correctly-valued segments (389, 403, 396B,
419, and the still-merged 420/412 segment) remain `BLOCKED` despite good
net/tax/gross values found two *additional* real date-format variants
`parse_date_maybe` does not yet tolerate, beyond the trailing-punctuation
fix from round 2: a space *before* the comma ("November 18 , 2018.",
page 14) and no space *after* it ("November 29,2018.", page 22). A third
case (page 16's date) is not a format issue at all but the
already-documented leading-noise-before-label limitation, this time on a
`Date` line ("`| Date : November 18, 2018.`"). None of these are fixed
in this round — date parsing is out of this task's explicit scope
(targeted net/gross extraction) — but they are now the dominant reason
most segments remain `BLOCKED`, and are the clear highest-impact target
for the next round.

### 20.5 Real-archive re-validation

Re-running the full real archive (fresh Tesseract OCR, this session; all
3 source PDFs confirmed byte-identical by SHA-256 before and after):

| Metric | Before this round | After |
|---|---|---|
| Segments produced / correctly bounded / under-split | 15 / 13 / 2 (unchanged — no segmentation code touched) | 15 / 13 / 2 |
| Net values correctly extracted (of 15 segments) | 2 (390, and N/A cases) | 7 (389, 403, 396B, 396, 390, 395, 420) |
| Gross values correctly extracted (of 15) | 0 | 4 (389, 403, 395, 420) |
| VAT values correctly extracted or correctly ruled (of 15) | 11 | 11 (unchanged — no VAT pattern changes this round) |
| Wrong values (both pre-existing, on the already-known pages 10–11 splice) | net + gross wrong | net now differently wrong (18,000.00 vs. the old derived 744.77) — still `LOW`/`BLOCKED`, never confirmable either way |
| Blocked segments | 14 | 13 |
| Confirmable segments (`REVIEW_REQUIRED` or `HIGH_CONFIDENCE`) | 1 | 2 (VN/QU/396/18 now `REVIEW_REQUIRED`; VN/QU/395/18 now the archive's first `HIGH_CONFIDENCE` segment — net, tax, *and* gross all independently found, all `HIGH`) |

Net/gross coverage on the correctly-bounded segments improved
substantially (5 real net values and 3 real gross values recovered), but
most segments remain `BLOCKED` — now predominantly by the date-parsing
gaps in §20.4, not by net/gross. This is answered directly: the net/gross
problem this task targeted is now meaningfully smaller; date parsing has
taken over as the dominant blocker and is the next round's target.

## 21. Targeted date extraction improvement (OCR Phase 4 round 4)

Round 3 found date parsing was now the dominant reason most correctly-
bounded segments stayed `BLOCKED`, with two more real date-format
variants and a leading-noise-on-`Date` instance flagged but not yet
confirmed one-by-one. This round verified each against the real OCR text
before changing anything.

### 21.1 Every real Date line in the archive, checked individually

Grepped every `Date` line in the real saved OCR output (24 pages) and
classified each — three genuinely distinct root causes confirmed, not
assumed to be the same:

| Real line | Root cause |
|---|---|
| `Date: 23.12.2018`, `Date - November 27, 2018.`, `Date : Nov 19, 2018.`, `Date - November 07, 2018.`, `Date : Nov 07, 2018.` (6 lines) | Already handled (round 2's trailing-punctuation fix, or no defect at all) |
| `Date - November 18 , 2018.` (page 14) | **New**: a space *before* the comma |
| `Date - November 03,2018.`, `Date - November 29,2018.` ×2 (pages 19, 21, 22) | **New**: no space *after* the comma — confirmed on 3 separate real documents, the more common of the two |
| `\| Date : November 18, 2018.` (page 16), `\| Date — November 11, 2018.` (page 17) | The already-known leading-OCR-noise-before-label limitation (previously seen on Reference/Total lines) — a third, distinct instance, this time on `Date` |
| `- Nov 27, 2018.` (page 8, VN/QU/412/18 1st occurrence) | The label word itself is entirely gone (round 2 finding) — unrelated to comma spacing, unaffected either way |

### 21.2 Fix made

One narrow addition to `parse_date_maybe` (`import_normalization.py`):
normalize any whitespace immediately around the comma in "Month DD,
YYYY" to exactly `", "` before matching against the existing, unchanged
`_DATE_FORMATS` list. This handles both new variants with a single rule
(a space added before the comma is removed, a missing space after it is
inserted) — no new format strings, reusing the existing infrastructure
exactly as instructed. It only ever touches whitespace directly adjacent
to a comma; it can never change what date is represented, cannot rescue
genuinely unparseable text (verified by test), and does not touch the
leading-noise cases at all — deliberately left alone, for the third time
now, for the same, consistently-applied reason: no single safe, narrow
shape exists to anchor a fix to across noise prefixes as different as
`"|"`, `"ie"`, `"eae"`, and `"3"`. This is the "stop and report" case
named in the task, applied to this one sub-pattern rather than to the
whole effort.

No segmentation code was touched — the investigation did not find a case
where a date fix required a segmentation change.

### 21.3 Real-archive re-validation

Fresh Tesseract OCR, this session; all 3 source PDFs confirmed byte-
identical by SHA-256 before and after; no `confirm_import` call anywhere
in the validation scripts, and no `Quotation`/`QuotationVersion`/
`Client`/`Project` rows exist in any of the run's databases by
construction.

| Metric | Before this round | After |
|---|---|---|
| Segments / correctly bounded / under-split | 15 / 13 / 2 (unchanged) | 15 / 13 / 2 |
| Dates visibly present on a real quotation's own page | 14 of 15 (the 15th is the delivery note, not a quotation) | 14 |
| Dates correctly extracted | 8 | **12** |
| Dates still missing | 7 (3 leading-noise/lost-label + 4 comma-spacing) | 3 (1 lost-label — VN/QU/412/18 1st; 2 leading-noise — VN/QU/403/18, VN/QU/396B/18) |
| Incorrect dates | 0 | 0 (no wrong date was ever produced — a value either parses to the one real date it represents, or stays `None`) |
| Net / gross / VAT correctly extracted (of 15, from §20.5) | 7 / 4 / 11 | unchanged: 7 / 4 / 11 — this round touched no other extraction path |
| `HIGH_CONFIDENCE` | 1 (VN/QU/395/18) | **2** (+ VN/QU/420/18) |
| `REVIEW_REQUIRED` | 1 (VN/QU/396/18) | **2** (+ VN/QU/390/18) |
| `BLOCKED` | 13 | 11 |
| Confirmable segments (`HIGH_CONFIDENCE` + `REVIEW_REQUIRED`) | 2 / 15 | **4 / 15** |

Each of the 4 newly-recovered dates was checked against the real
scanned quotation directly: VN/QU/389/18 → 2018-11-18, VN/QU/390/18 →
2018-11-03, VN/QU/419/18 → 2018-11-29, VN/QU/420/18 → 2018-11-29 — all
four match the visual ground truth exactly.

One nuance worth stating plainly: VN/QU/389/18's date is now correctly
extracted, but its segment is still `BLOCKED` — its `net_value` is
independently flagged `LOW` by the pre-existing identity-corroboration
check (§18/§20.3), because its own net figure legitimately sits on a
different page from its reference/date (a normal, correct 2-page layout
for this business's own template, not a defect). Fixing the date does
not and should not change that separate, already-conservative gate.

### 21.4 Is quotation ingestion now practically usable?

Confirmable segments doubled (2 → 4 of 15) from a single, narrow date
fix, on top of round 3's net/gross recovery. That is real, verified
progress, not just a bigger test count. But the honest answer is not yet
fully: 11 of 15 segments are still `BLOCKED`, for a mix of reasons this
project has now catalogued precisely rather than guessed at —
2 confirmed cross-document splices/mis-bounded segments, 3 pages with
genuinely illegible or reading-order-scrambled financial or date data,
3 segments hitting the leading-noise-before-label limitation, and the
delivery note correctly excluded. None of these remaining gaps are a
single narrow pattern away from fixed — most now require either
accepting them as permanent manual-review cases (the honest majority),
or a materially different, higher-risk approach (fuzzy/confidence-scored
label matching, or real table/layout reconstruction) that this project
has consistently and deliberately declined to build. Quotation ingestion
is meaningfully more usable than at the start of this fix sequence, and
every remaining blocker is now named and explained rather than mysterious
— but "practically usable at scale with only light review" is not yet
true for a majority of real documents in this archive.

## 22. Historical batch ingestion, review triage, and analytics

Three layers were added on top of this pipeline, unchanged by any of
them: `app.services.import_service.ingest_quotation_batch`/
`ingest_purchase_order_batch` (resumable batch drivers — see that
module's own "Batch / historical ingestion" section for the exact
resumability rule), `app.services.review_service` (splits
`NEEDS_REVIEW` documents into "needs a human's judgment" vs. "just needs
the routine confirm click," reusing this document's own
`compute_ocr_confidence_status` unchanged), and
`app.services.analytics_service` (read-only reporting over confirmed
`Quotation`/`QuotationVersion` data — see `ANALYTICS_ARCHITECTURE.md`).
None of the three write to a `Quotation`/`QuotationVersion`/`BOQ` row;
`confirm_import` remains the only place that happens.

## 23. Currency fallback fix + random-order historical-ingestion pilot #2

### 23.1 Currency fallback now uses the project's own company, not a hardcoded constant

`confirm_import`'s currency resolution previously fell back to the
module-level `DEFAULT_CURRENCY` constant (`Currency.AED`) whenever no
currency was extracted from the candidate — which is the common case,
since most real Vinco quotations state their currency as a symbol
attached to each amount ("SR 5,700.00"), not as a separately labeled
field. This app is single-company (`Company` has exactly one row,
`project_service.get_or_create_default_company`), and `Company` already
had an unused `default_currency` field for exactly this purpose. The
fallback now reads `session.get(Company, project.company_id)
.default_currency`, falling back to the module constant only in the
practically-unreachable case the company row is somehow missing (it is
`NOT NULL` on `Project`). The module constant itself, and every other
one of its ~16 call sites, is deliberately untouched — this is a narrow
routing fix, not a change to what the default value *is*.

Validated against real data from pilot #2 below: with
`Company.default_currency` set to `SAR` (this archive's real business
currency), both real quotations confirmed from the batch (`VN/QU/395/18`,
`VN/QU/420/18`) received `currency=SAR`, not the hardcoded `AED`.

### 23.2 Pilot #2: a second, larger real archive, deliberately random order

A new 24-page real archive (`Quotations_20185.pdf`) was ingested via
`ingest_quotation_batch` together with the three files from pilot #1 —
by design, in whatever order the files were supplied, since the business
process this pipeline serves receives scans in no guaranteed order.
Nothing about `detect_segments`'s ordering independence changes: each
file is still segmented and extracted entirely independently of any
other file in the batch (§3a).

Ground truth for all 24 pages was established by direct visual reading
before running any extraction, confirming (among 19 real quotation
segments plus one real invoice, `VN/QU/IN/004M/18`, correctly not
recognized as a quotation) two more real, useful edge cases: a genuine
duplicate page within one PDF (`VN/QU/270A/18`'s first copy, page 13,
independently re-scanned with different OCR noise than its second copy
on page 14), and a genuine revision pair (`VN/QU/280/18` →
`VN/QU/280A/18`, same client/subject, different date and value).

Three new, narrow, real-evidence-grounded fixes were made after this
diagnosis (regression tests reference the exact real segment each is
grounded in):

- `_NET_COST_OF_WORK_PATTERN` (net-value fallback sentence) now accepts
  "cost of work" as well as "cost of the work" (real: `VN/QU/251A/18`
  genuinely drops "the"), and tolerates a run of underscores between the
  currency token and the amount, not just whitespace (real:
  `VN/QU/281/18`'s printed fill-in-the-blank line OCRs its underline as
  literal underscores: `"SR _ 7,500.00"`).
- `_TRAILING_HARMLESS_PUNCTUATION_RE` (date parsing) now also strips a
  trailing `|` and lets whitespace mix into the same trailing run, so a
  period-then-space-then-pipe artifact (`"Aug 28,2018. |"`,
  `VN/QU/253A/18`) is stripped in one pass rather than leaving the period
  behind after the pipe alone is removed.
- A new, narrow, field-scoped strip removes a trailing bare separator
  character from an extracted `quotation_number` specifically (real:
  `VN/QU/253A/18`'s own reference line ends in a stray table artifact,
  `"VN/QU/253A/18 :"`) — never applied to other fields, where trailing
  punctuation can be meaningful.

Before → after, across all 36 segments from all 4 files in this pilot
(recomputed directly against the real stored OCR text, independent of
any one document's segmentation):

| Metric | Before | After |
|---|---|---|
| `HIGH_CONFIDENCE` | 2 | 2 (unchanged — both are single-page segments unaffected by this round's fixes) |
| `REVIEW_REQUIRED` | 7 | 9 |
| `BLOCKED` | 27 | 25 |
| Missing `quotation_number` | 5 | 5 (unchanged — the fix cleans a dirty value, it doesn't recover a truly absent one) |
| Missing `quotation_date` | 5 | 4 |
| Missing `net_value` | 21 | 19 |
| Missing `gross_value` | 25 | 24 |

The two segments that moved out of `BLOCKED` are `VN/QU/251A/18` (a
genuinely huge real quotation, SAR 20,986,042.00, now correctly
extracted) and `VN/QU/281/18` (net now found directly, so `gross` is now
correctly re-derived from net+tax). Neither reached `HIGH_CONFIDENCE`
after the fix — `VN/QU/251A/18`'s VAT is explicitly not charged on this
quotation ("VAT Pricing is not included in the offer"), which is
correctly recorded as `tax_value=0.00` at `LOW` confidence (a business
fact, not a gap) and that alone keeps it at `REVIEW_REQUIRED`.

### 23.3 The dominant real cause of `BLOCKED`, confirmed, not a bug

25 of 36 segments are `BLOCKED` after this round's fixes. The large
majority of these are not a code defect: §20.3's pre-existing
identity-corroboration check (`_flag_financial_fields_without_
identity_corroboration`) downgrades `net_value` to `LOW` confidence —
which `compute_ocr_confidence_status` treats as equivalent to
`net_value` being missing outright — whenever the net figure and the
reference/date live on different pages of the same segment. This is
Vinco's own normal template for any 2-page-or-longer quotation (header
on page 1, the "cost of the work ... SAR X" totals sentence on page 2),
so it structurally, deliberately, and correctly blocks a large share of
otherwise-perfectly-extracted real multi-page quotations from ever
reaching `HIGH_CONFIDENCE` or even `REVIEW_REQUIRED` without a human
explicitly confirming the total. Confirmed directly on `VN/QU/318/18`
(pages 1-2): reference/date/client all `HIGH` confidence, net/tax/gross
all correctly extracted and internally consistent (275,750.00 +
13,787.50 = 289,537.50, matching the real printed total exactly) — and
still `BLOCKED`, for exactly this reason. This is a known, accepted,
safety-first trade-off already documented at §20.3, not a new finding to
fix; it is named here because it is the single largest contributor to
this pilot's `BLOCKED` count, and any future work on this pipeline
should not mistake it for an extraction gap.

### 23.4 Real, demonstrated OCR-quality limitations left unfixed

Three further real defects were found, diagnosed to their exact root
cause, and deliberately left unfixed — each is either already an
accepted limitation category (documented elsewhere in this file) or
would require a broad, false-positive-risking change to fix narrowly:

- **Leading OCR noise before a label, on three independent real
  pages, each with a different noise string** (`"i Reference..."` on
  `VN/QU/319/18`, `": Currency: SAR"` on the invoice page, `"be
  Reference..."`/`"= Date..."` both on `VN/QU/270A/18`'s first, noisier
  copy). Already an accepted limitation (§19.1, §20.1's "leading-noise"
  category) — the noise strings are not a small fixed set, so widening
  the anchor would risk matching ordinary prose that happens to start
  with a short word before a label-shaped phrase.
- **A real, consequential mis-boundary caused by that same limitation
  compounding**: `VN/QU/270A/18`'s first copy (page 13) lost *both* its
  reference and date labels to leading noise simultaneously, so it
  carried no identity signal at all and was silently absorbed as a
  continuation of the still-open `VN/QU/283/18` segment (pages 11-13) —
  exactly the "under-split, never mis-attribute silently" behavior this
  module's own design accepts as the safe failure mode (never confirmed
  without a human seeing the seam), but worth naming plainly: a `HIGH`
  `boundary_confidence` describes only the page that *opened* the
  segment, not a guarantee that every later page in its range truly
  belongs.
- **Complete OCR corruption of the numeric digits themselves**, not
  just the label (`VN/QU/265A/18`'s and `VN/QU/283/18`'s totals tables;
  `VN/QU/253A/18`'s `GRAND TOTAL` row) — the digits come out as
  unrelated OCR garbage with no salvageable pattern, not a wrong-but-
  parseable number. No safe fix exists short of re-scanning the source.

### 23.5 Resumability and immutability re-confirmed at this larger scale

`ingest_quotation_batch` was run a second time against the same 4 files
and the same database: all 4 were reported `skipped_duplicate` (matched
by `file_hash`, per `_RESUMABLE_EXTRACTION_STATUSES`), the second run
completed in under a second (no OCR re-run), and document/segment counts
were unchanged (36 segments both before and after). All 4 source files
remained byte-identical and hash-identical after both runs.

### 23.6 Verdict

The evidence supports **(B): another targeted extraction-improvement
round**, not yet (A) review UI/dashboard work or (C) an architectural
change. Real, narrow, safely-fixable defects are still being found at a
steady rate each time a new real file is examined (three more this
round, on top of round 3's and round 4's), and none of them have
required weakening a gate, guessing past genuine ambiguity, or touching
`financial_engine.py`/award/matching/reconciliation logic. §23.3's
finding is the one that most changes the picture for (A): the dominant
`BLOCKED` cause across this larger sample is not a bug at all, so no
amount of further narrow extraction fixing will move most of these
segments past `REVIEW_REQUIRED` — a future decision point (out of scope
for this round) is whether the identity-corroboration gate's page-level
strictness is worth revisiting specifically for the "total on a later
page of the same already-correctly-bounded segment" case, which is a
materially different, much lower-risk claim than "trust a value found
anywhere in the document."

## 24. A failed corroboration-relaxation experiment (deliberate safety finding)

§23.6 raised, as a future decision point, whether the
identity-corroboration gate (§20.3/§23.3,
`_flag_financial_fields_without_identity_corroboration`) could be
narrowed for the common "total on a later page" case without losing its
protection. This was investigated directly and rejected — recorded here
because the negative result is itself load-bearing: the same relaxation
should not be re-attempted later without the stronger evidence this
section describes being available.

### 24.1 The proposed rule

Only relax the existing downgrade (financial field found on a page other
than the identity page → confidence `LOW`) when the **identity page
itself independently matched no financial field at all** (net, tax, or
gross). The reasoning: if the identity page has nothing for a later
page's value to disagree with, there is no competing signal to protect
against. If the identity page *does* carry its own financial content,
the existing downgrade would still apply unchanged.

### 24.2 The three real cases it appeared to justify

- `VN/QU/318/18` (pp1-2, §23.2's own worked example): page 1 is pure
  header/scope-of-work, no financial content; page 2 carries the totals.
- `VN/QU/389/18` (pp14-15): same shape — page 14 header/scope only, page
  15 the "cost of the work ... SAR 16,850.00" sentence.
- `VN/QU/254/18` (pp21-22): same shape — page 21 the numbered
  scope-of-work, page 22 continuing the same numbered list into the
  total.

In all three, the identity page's own independent extraction (checked
directly, single-page slice) produced no `net_value`/`gross_value`, and
no genuine `tax_value` match either (specifically excluding
`_apply_vat_determination_when_undetermined`'s "genuinely
undeterminable, assume SAR 0.00" fallback from counting as financial
content — that fallback fires on *any* page with no VAT information at
all, which would otherwise make the check true on every identity-only
header page and defeat its own purpose; this was caught during
implementation, before any test was written, by checking
`"tax_value" in raw_values` rather than trusting `tax_value`'s own
parsed value or confidence).

### 24.3 The existing regression tests that disproved it

Implementing the rule (in `_flag_financial_fields_without_identity_
corroboration`, `app/services/import_service.py`) and running it against
the project's own pre-existing adversarial-exploit suite in
`app/tests/test_import_service_ocr.py` broke two tests immediately:

- `test_financial_value_on_an_unidentified_page_cannot_splice_into_a_confirmable_candidate`
- `test_cost_of_the_work_sentence_on_an_unidentified_page_cannot_splice_either`

Both construct the exact "reference A + unrelated total B" exploit this
gate exists to catch: a reference/date on page 1 with **zero** financial
content anywhere on that page, and a genuinely unrelated, unidentified
document's total surviving later in the same file with nothing
connecting it back to page 1's identity. Under the proposed rule, both
values (999,999.00 and 18,000.00, neither belonging to the quotation
they would attach to) were silently promoted to `HIGH` confidence and
became confirmable — reintroducing the precise defect
`_flag_financial_fields_without_identity_corroboration` was written to
close.

### 24.4 Why the real and unsafe cases are structurally indistinguishable

The proposed signal — "identity page has no financial content" — is
true of all three real safe cases *and* of both constructed exploit
cases. The only reason the fourth real case checked in §23
(`VN/QU/406/18`, correctly identified as a genuine splice risk) was
correctly kept blocked is that *that specific document* happened to
also print its own (OCR-garbled) totals table on its own identity page
— a property of that one document, not a general distinguishing fact
between "genuine continuation" and "unrelated spliced-in page." A page
carrying a genuinely unrelated value can just as easily follow an
identity page with no financial content of its own, exactly as the
existing exploit tests already assumed when they were written. The real
distinguishing property — whether the pages *between* the identity page
and the value's page form one continuous, unbroken narrative (the same
scope-of-work/item list actually continuing) rather than an unconnected
insertion — is not something a narrow, page-local, pattern-based signal
can check; it would require the kind of semantic/heuristic inference
this project has consistently and deliberately declined to add anywhere
in the pipeline (no fuzzy matching, no confidence scoring beyond the
existing categorical levels, no guessing past genuine ambiguity).

### 24.5 Outcome

The change was reverted in full (`git checkout --
app/services/import_service.py`) as soon as the regression was found,
before writing the new tests the task had otherwise called for. No test
file, migration, schema, or other production code was touched. The full
suite was confirmed back to its unmodified passing state immediately
after reverting. No real-OCR re-validation was run, since there was no
surviving change to validate. **No production behavior changed as a
result of this investigation.**

### 24.6 Conclusion

`_flag_financial_fields_without_identity_corroboration` remains exactly
as conservative as before, and should stay that way: three of the four
real "total on a later page" cases examined so far are safe, but the
project's own test suite already proves a page-local signal cannot
reliably tell them apart from a genuine cross-document splice. This gate
must not be narrowed again on the strength of a handful of real examples
alone — only a substantially stronger structural signal (one that can
positively confirm narrative continuity between the identity page and
the value's page, not merely the absence of a competing value) would
justify revisiting this, and no such signal has been identified. Until
then, `VN/QU/318/18`-shaped cases are accepted as human-review workload,
per §23.6's original framing, not treated as a defect to keep chasing.
