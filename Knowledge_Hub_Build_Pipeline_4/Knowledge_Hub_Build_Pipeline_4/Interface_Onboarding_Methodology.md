# Interface Onboarding Methodology — Integration Knowledge Hub

A repeatable, configuration-driven procedure for turning an Andsoft interface
document into a validated Knowledge Hub entry: glossary fields, an interface
record, and an OpenAPI specification.

## Objective

Andsoft produces each interface's design as a Word document, following a
standard template that captures the agreed contract specification
requirements to be detailed for every integration: an overview, an endpoint
definition, and a nested field-mapping table. The objective of this
automation is to generate, directly from that Andsoft Integration
Specification document, every output the Integration Knowledge Hub needs: a
standardized glossary of fields, a validated interface record, and an
OpenAPI specification — without manually rebuilding each of those outputs by
hand for every interface. The OpenAPI specification is only one of the
outputs produced; the same pipeline also produces the Knowledge Hub's
glossary and interface data, and the document-quality reports used to
validate Andsoft's documentation.

## The seven stages

```
Andsoft Integration Specification .docx → 1. Extract → 1.5 Lint → 2. Review → 3. Validate → 4. Compile → 5. Publish
                                                                                      ↘ 4b. Generate OpenAPI
```

| Stage | What it does | Who/what runs it | Output |
|---|---|---|---|
| 1. Extract | Reads the Andsoft document by heading/table-header text and pulls out the endpoint, every leaf field, and its nesting path | Automatic (script) | `fields.draft.yaml`, `interfaces.draft.yaml`, `REVIEW_REPORT.md` |
| 1.5 Lint | Checks the Andsoft document's own internal quality — naming, missing descriptions, mismatched fixed values, type-vs-example disagreements | Automatic (script) | `DOC_QUALITY_REPORT.md` (blocking / advisory / informational findings) |
| 2. Review | A reviewer applies a short list of interface-specific judgement calls (sensitivity, conditional vs. mandatory, etc.) | Human, a few minutes | Promotes `*.draft.yaml` → final `fields.yaml` / `interfaces.yaml` |
| 3. Validate | Confirms every field/interface/flow record is schema-valid and every cross-reference resolves, across all interfaces combined | Automatic (CI gate) | Pass/fail — blocks the next stage on failure |
| 4. Compile | Turns the validated YAML into the data file the Knowledge Hub application reads, with no changes to the application's UI code | Automatic (script) | `exampleData.js` |
| 4b. Generate OpenAPI | Builds a real, structurally validated OpenAPI 3.0.3 specification for the interface from the same validated YAML | Automatic (script) | `<interface_id>.openapi.yaml` / `.json` |
| 5. Publish | Rebuilds the application with the generated data file | Automatic (build step) | Production bundle updated — zero component changes |

Each stage reads the previous stage's output and refuses to proceed if that
output doesn't pass its own checks — so a defective Andsoft document or a
skipped review step stops at that stage rather than silently flowing
downstream.

## Per-interface run report

Every time this pipeline runs against an interface, the actual numbers it
produces — how many fields were extracted, how many were flagged for review,
how many lint findings came back and at what severity, whether validation
passed, whether the OpenAPI specification validated — are specific to that
interface's document and change every time Andsoft revises it. That detail
does not belong in this methodology document, which stays the same for
every interface.

`scripts/generate_run_report.py` produces exactly that: one
`RUN_REPORT_<interface_id>.md` per interface, written alongside its domain
folder, consolidating the outcome of every stage in a single pipeline run —
Stage 1's extraction counts, Stage 1.5's lint severity breakdown, Stage 2's
review/promotion status, a live re-run of Stage 3's validation, Stage 4's
compile confirmation, Stage 4b's OpenAPI re-validation, and a flag for
Stage 5's publish step (which happens outside this pipeline's scripts and is
confirmed separately). Each interface's full onboarding history is then
traceable from one document, without re-reading this methodology or
re-running every script by hand.

## How this pipeline behaves

This is an internal, automated pipeline, not a one-time manual build. Once
set up, it regenerates its outputs automatically whenever Andsoft supplies a
new interface document, or revises a document already onboarded:

- The extraction, lint, validation, compilation, and OpenAPI-generation
  scripts are built once and reused unchanged for every interface.
- Each run reads whatever Andsoft document is current for that interface —
  new or revised — and regenerates the glossary fields, interface record,
  and OpenAPI specification from that document's content.
- Only the review step needs a person: a short, interface-specific rule
  list capturing judgement calls (sensitivity, conditional vs. mandatory,
  etc.), typically a few minutes of work.

| | Built once | Runs again automatically per document |
|---|---|---|
| Extraction, lint, validation, compilation, OpenAPI generation | Built and proven | Re-run on every new or revised Andsoft document — seconds |
| Review rules | Format established | A short, interface-specific rule list — minutes |
| Net new engineering | The pipeline itself | None |

This is what keeps onboarding a new interface — or re-onboarding one after
Andsoft revises its document — fast and consistent.

## Components involved

- **Schemas** — `field.schema.json`, `interface.schema.json`, `flow.schema.json` define what a valid record looks like.
- **Domains** — one folder per interface group, each holding its own draft and final YAML plus its review/lint reports.
- **Scripts** — extract, lint, validate, compile, generate-OpenAPI, and generate-run-report, each doing one stage (or, for the last, consolidating the others) and nothing else.
- **Andsoft documentation standard** — a companion guideline for Andsoft, generated from the same lint rules, so future documents need fewer round trips to fix.
