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
