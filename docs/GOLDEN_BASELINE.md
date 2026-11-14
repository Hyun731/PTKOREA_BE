# Golden baseline workflow

A golden baseline turns an approved factbook into versioned facts and claims without committing the customer source files or extracted customer data.

## Storage boundary

Keep the real baseline directory outside this repository or in access-controlled storage. Never commit the source PDF, meeting notes, rendered pages, extracted text, real facts, or real claims.

The repository may contain only:

- the schema and validator in `core/golden_baseline.py`
- the validation CLI in `tools/validate_golden_baseline.py`
- synthetic fixtures under `tests/fixtures/golden_baseline`
- non-customer-specific documentation

## Directory contract

```text
private-baseline/
├── baseline.json
├── slides.csv
├── facts.csv
└── claims.csv
```

`baseline.json` fixes the baseline ID, version, effective period, brands, slide count, and source file hashes. It stores metadata only; source files remain outside the directory used by Git.

`slides.csv` maps every page exactly once. Page numbers must cover `1..slide_count` without gaps. `fact_status` and `claim_status` are `pending`, `complete`, or `not_applicable`; strict validation blocks every remaining `pending` page.

`facts.csv` stores numeric evidence. Derived facts require a calculation. Source URLs are optional, but when present they must use HTTP or HTTPS.

`claims.csv` stores headlines, evidence statements, insights, conclusions, and recommendations separately from facts. Multiple fact IDs use semicolons, for example `F-AWARE-001;F-GAP-001`.

## Review states

- `customer_approved`: explicitly approved in the supplied final version
- `source_checked`: verified against the cited source
- `needs_review`: extracted but not yet verified

Normal validation permits `needs_review` while the ledger is being prepared. Strict validation blocks it before the baseline is used for a GAP report.

## Validation

```bash
python -m tools.validate_golden_baseline /absolute/path/to/private-baseline
python -m tools.validate_golden_baseline /absolute/path/to/private-baseline --strict
```

After generating an outline, measure balanced brand/page coverage and claim overlap without moving the private data
into Git:

```bash
python -m tools.evaluate_golden_gap /absolute/path/to/private-baseline outline.json \
  --brand-alias "Brand Alpha=Alpha"
```

Repeat `--brand-alias` when generated section names use localized or abbreviated brand names. The output reports
per-brand page coverage, lexical claim coverage, missing slots, and unassigned generated slides.

## Import preview

Preview how a strict baseline maps into an existing project's accepted inputs before writing anything:

```bash
python -m tools.import_golden_baseline /absolute/path/to/private-baseline \
  --database-url sqlite:////absolute/path/to/copied.db \
  --project-id PRJ-example \
  --brand-map "Brand Alpha=B1" \
  --brand-map "Brand Beta=B2" \
  --brand-map "Brand Gamma=B3"
```

Add `--apply` only after reviewing the unsupported-fact report. The importer creates deterministic, accepted
source/material/claim rows and only converts facts whose units fit the application's manual fact contract.
Unsupported units and negative values remain explicit in the report instead of being silently coerced. Re-running
the same import is idempotent. Claims that reference unsupported facts or still contain unbound digits are imported
as pending, so they cannot introduce unsupported numbers into a generated deck. Always use a copied database for
evaluation before changing a live project.

The validator checks:

- file presence and row schemas
- source hashes, dates, URLs, and derived calculations
- complete and unique slide pages
- consistent baseline IDs and brands
- unique fact and claim IDs
- claim-to-fact references
- evidence page references
- unresolved review states in strict mode

Use `tests/fixtures/golden_baseline` only as a synthetic example. It is not customer data and must not be replaced with real values.
