# Run Report — CV07_02

Generated: 2026-11-06 12:44 UTC
Domain: `domains/cv07_shippeo`

**Overall: ❌ FAIL**

One consolidated record of this interface's pipeline run, stage by stage — replaces having to cross-reference `REVIEW_REPORT.md`, `DOC_QUALITY_REPORT.md`, and the console output of each script separately.

## ✅ Stage 1 — Extract — OK

Extracted **80** unique glossary fields from **99** payload occurrences.

**16** field(s) flagged for human review (no AndSoft source-column mapping) — see `REVIEW_REPORT.md` for the full list.

## ❌ Stage 1.5 — Lint — FAIL

**24 blocking · 6 advisory · 5 informational** finding(s) against the Andsoft document's own internal consistency — see `DOC_QUALITY_REPORT.md`.

Blocking findings must be resolved with Andsoft before this interface is built against.

## ✅ Stage 2 — Review — OK

Promoted to final: **80** field(s) and **1** interface(s) in `fields.yaml` / `interfaces.yaml`.

## ✅ Stage 3 — Validate — OK

Ran `validate_all.py` across all domains just now:

```
Domains scanned:   3 (cv07_02_shippeo_events, cv07_shippeo, oms_tms_planification)
Fields loaded:      115
Interfaces loaded:  5
Flows loaded:       2

PASSED - all records valid, all field_id/interface_id references resolve, no duplicate ids.
```

## ✅ Stage 4 — Compile — OK

`output/exampleData.generated.js` exists and contains a reference to `CV07_02`.

## ❓ Stage 4b — Generate OpenAPI — UNKNOWN

`CV07_02.openapi.yaml`/`.json` present, but `openapi_spec_validator` is not installed so re-validation was skipped.

## 🔧 Stage 5 — Publish — MANUAL

Publishing (rebuilding the Knowledge Hub application with this compiled data file) happens outside this pipeline's scripts. Confirm separately by running the application's build and checking the production bundle contains this interface's data.
