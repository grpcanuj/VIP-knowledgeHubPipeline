# Tower 1 — Integration Knowledge Hub: from Andsoft Word templates to a real, configuration-driven tool

## The problem this solves

Andsoft owns the design and build of every interface, but isn't ready with Swagger/OpenAPI. What they can give us today is one Word document per interface (a "Technical Analysis" template) describing the endpoint and a nested field-mapping table. The Knowledge Hub cannot wait for Swagger, and it also cannot be rebuilt by hand for every one of the 100+ interfaces still to come — the whole point of calling it "configuration-driven" is that interface #2 onward must be materially faster than interface #1.

This was solved by building a real pipeline, not a one-off walkthrough, and proving it end-to-end against the one real document provided (`CV07_01_TMS_2_SHIP_ORDERS.docx` — TMS → Shippeo, Create/Update/Cancel a transport order, PLN/APLN). Everything described below actually ran against that file; the numbers quoted are the real output, not illustrative ones.

## The seven stages

```
Andsoft .docx → 1. Extract → 1.5 Lint → 2. Review → 3. Validate → 4. Compile → 5. Publish
                                                                        ↘ 4b. Generate OpenAPI
```

Stage 4 now branches: the same validated YAML compiles into both the React app's data file (4) and a real, validated OpenAPI 3.0.3 spec per interface (4b) — see its own section below.

### Stage 1 — Extract (automatic, seconds per interface)

`scripts/extract_interface_from_docx.py <docx> --id <ID> --name <NAME> --out-dir domains/<domain>`

Reads the document by **heading and table-header text**, not fixed row/column positions, so it tolerates the normal drift between Andsoft's templates:

- The Overview section → source system, target system, flow direction, description.
- The endpoint table (Purpose / Direction / Method / URL / Idempotent / Side effects) → protocol, method, URL, retry policy.
- The nested field-mapping table (the one with a `Rank` column going 0→4) → every **leaf** field, walking the rank column as a nesting stack so each field gets its full JSON path (e.g. `shipment.orders[].pickUp.dates[].dateTime`). Container rows (`object`/`array` types) are not turned into fields — only scalars are, because a glossary field is a business term, not a structural node.
- Any `Fixed value: X` called out in a row's description is captured as a constant, and the vendor's own source-column name (the "Field AndSoft" column) is preserved for traceability back to the document.
- Rows where the AndSoft source column is `?` or blank are flagged for review rather than silently guessed at.

**Run on CV07_01:** 99 payload leaf occurrences → 80 unique glossary fields, 16 flagged for review (all genuine `?`/TBD gaps in Andsoft's own document, not extraction failures). Output: `fields.draft.yaml`, `interfaces.draft.yaml`, `REVIEW_REPORT.md`.

One real wrinkle the script had to handle and now handles for every future interface too: generic wrapper names (`dates`, `identifications`, `tags`, `attributes`, `references`, `items`...) repeat under different parents — `pickUp.dates[].dateTime` and `consignee.dates[].dateTime` both have the immediate parent `dates`. A naive "parent + leaf name" field ID would have silently collapsed these two genuinely different fields into one. The script detects that specific collision (same parent+leaf reached via a different ancestor chain) and automatically escalates just those to a two-level name (`pickup-dates-datetime` / `consignee-dates-datetime`), leaving the simple one-level names (`consignor-name`, `pickup-city`, ...) untouched everywhere there's no ambiguity.

### Stage 1.5 — Lint (automatic, document-quality gate)

`scripts/lint_source_document.py <docx> --out-dir domains/<domain>` runs right after extraction and checks the **vendor document's own internal consistency and completeness** — distinct from Stage 1's review report, which only flags fields with no source-column mapping. This is the "OpenAPI/Swagger-lint equivalent" for a Word-template input: since Andsoft's documents aren't machine-readable specs yet, this substitutes for the kind of schema-linting that would normally be automatic. It writes `DOC_QUALITY_REPORT.md`, with findings in three tiers:

- **Blocking** — must be resolved with Andsoft before this interface is built against (missing source mappings, a genuine copy-paste duplicate row, an unfinished "TBD" endpoint URL).
- **Advisory** — probably fine, worth a second look (a fixed value that disagrees with its own source column; an exactly-repeated row that's redundant but not wrong).
- **Informational** — judgement calls to confirm, not necessarily problems (the same generic attribute name — `name`, `city`, `dateTime`, `identifier`...— recurring under different parent objects; confirm each is genuinely a distinct business concept rather than a copy-paste artifact).

**Run on CV07_01:** 13 blocking, 3 advisory, 21 informational. One real bug surfaced and got fixed while building this: a repeatable array slot (`attributes.name`/`value`, documented via 4 example rows with 4 different values — `carrier_code`, `origin_location_code`, `destination_location_code`, `client`) was initially having 3 of its 4 values silently dropped by the extraction script, which only kept the first occurrence. Fixed so that when the same field_id recurs with different fixed values, they're now aggregated into that field's `allowed_values` and the field is promoted to `data_type: enum` — nothing is silently lost anymore. A second, subtler case (`tags.label`, which repeats under one generic name for four *unrelated* meanings with no fixed value to tell them apart) is now preserved too — all four meanings are kept in the field's description, with a quality-rule flag recommending Andsoft consider separate named fields instead.

The same rule set that `lint_source_document.py` encodes is written up in plain language in `VENDOR_DOCUMENTATION_STANDARD.md` — a one-page guideline for Andsoft to follow on future interface documents, covering: every field needs a source mapping or a stated fixed value; a fixed value shouldn't contradict its own source column; field names should be camelCase per their own stated convention; a generic attribute name reused for unrelated meanings should get a specific description per occurrence (or ideally a dedicated field); a repeatable array shape is best described once with a table of known values rather than one full row per example; every field needs a real description; endpoint URLs need to be finalized before cutover; and the Rank column should stay numerically consistent. The two documents are deliberately kept in lockstep — the checks ARE the standard, just expressed as code in one place and prose in the other.

### Stage 2 — Review (human, minutes per interface — not hours)

The reviewer's judgement calls are not 80 individual hand-edits. They're expressed as a short rule list in `scripts/promote_cv07_draft.py` — e.g. "these field_ids are protocol constants → sensitivity: public", "these carry a tax ID → sensitivity: confidential", "these two are conditional, not mandatory, per Business Rule BR-01." For CV07_01 that list was 4 rules covering all 80 fields. For interface #2, it's a new short list tailored to that interface's own quirks — still minutes, not a re-type of the whole table.

Running it promotes `*.draft.yaml` → `fields.yaml` / `interfaces.yaml` (the files the next stage actually reads).

### Stage 3 — Validate (automatic, CI gate)

`scripts/validate_all.py` is the generalized replacement for the old `validate_oms_tms_examples.py` (which hardcoded one domain's filenames). It now globs every folder under `domains/`, so it keeps working unchanged as domain #2, #3, ... #100+ are added. It checks, across **all** domains combined:

1. Every field / interface / flow record validates against its JSON Schema (`field.schema.json`, the newly-written `interface.schema.json`, `flow.schema.json`).
2. Every interface's `field_id` reference resolves to a field defined somewhere.
3. Every flow's `interface_id` reference resolves to an interface defined somewhere.
4. No `field_id` or interface `id` is defined twice across domains.

Run against the combined set (existing `oms_tms_planification` domain + new `cv07_shippeo` domain): **PASSED — 91 fields, 4 interfaces, 2 flows, zero errors.** This is the gate a pull request has to clear before anything merges — exactly the CI check the Full Stack Developer JD already commits to building.

A schema was missing before this: `interface.schema.json` didn't exist on disk even though the old validator already imported it. It's been written now (and copied back to your outputs folder), extended with a few optional fields the IF-101-style examples didn't need but a deeply-nested vendor payload does: `path` (the JSON path), `fixed_value`, `source_field` (the vendor's own column name, for traceability), and `io` (request/response leg).

### Stage 4 — Compile (automatic)

`scripts/compile_knowledge_hub.py` is the actual "static-site compile pipeline that turns validated YAML into the Glossary, Interface Index, Flow Diagram, and Traceability pages" that the Full Stack Developer JD describes. It:

- Refuses to run if Stage 3 found errors (compiling broken cross-references into the UI is worse than refusing to build).
- Reads every `domains/*/{fields,interfaces,flows}.yaml`.
- Emits one generated file, `exampleData.js`, in **exactly** the shape the four page components already import (`FIELDS`, `INTERFACES`, `FLOWS`, `REQUIREMENTS`, `getField()`, `getInterface()`, `getRequirement()`) — so **zero lines change** in `GlossaryPage.jsx`, `InterfaceIndexPage.jsx`, `FlowViewPage.jsx`, or `TraceabilityPage.jsx`. Only where that data module comes from changes: from a developer hand-typing demo rows, to this script.
- Generates each flow's Mermaid diagram from its `steps` array rather than anyone hand-drawing it (exactly the intent already written as a comment in the existing `flows_oms_tms_planification.yaml`).
- Deliberately leaves `REQUIREMENTS` empty with an explanatory comment rather than fabricating test-evidence rows: that data is Tower 2's system of record (its own test-execution views), and Tower 1 should hold only a thin pointer/status, refreshed from Tower 2's API or event feed — not redefined here. That's the same system-of-record boundary already agreed for the Traceability view.

### Stage 4b — Generate OpenAPI (automatic — the actual Swagger deliverable Andsoft intended to supply)

`scripts/generate_openapi.py --domains-dir domains --out-dir output/openapi` reads the same validated `fields.yaml`/`interfaces.yaml` Stage 4 reads, and produces a real OpenAPI 3.0.3 spec per interface (`<id>.openapi.yaml` and `.json`) — structurally validated with `openapi_spec_validator` before it's written to disk; the script refuses to write a spec that fails validation rather than ship something broken.

The hard part is reconstructing the real nested JSON shape from a flat list of fields. Each field's `path` (e.g. `shipment.orders[].pickUp.dates[].dateTime`) is walked segment by segment — `[]` means "this level is an array of objects," anything else is a plain object — to rebuild the exact nesting, with every leaf's data type, format, max length, allowed values and example value filled in from its glossary entry.

This is only correct because of a fix made upstream, in Stage 1: the vendor document's own "Type" column (object vs. array) turned out to disagree with its own worked JSON example for **9 of CV07_01's 25 nested containers** — e.g. `consignor`/`customer`/`carrier`/`consignmentNote`/`documentProperties` are typed "array" in the table but shown as plain objects in the example; `attributes`/`tags`/`items`/`handlingUnits` are typed "object" but shown as arrays. Trusting the Type column alone would have produced a structurally wrong OpenAPI spec. The pipeline now parses the document's own worked example and uses it as ground truth, correcting each field's stored `path` before anything downstream (OpenAPI generation, and in principle any future direct build) ever sees it. The disagreement itself is also now a dedicated lint rule (`structure-type-vs-example-mismatch`) worth raising with Andsoft.

A second, smaller defect surfaced the same way: the endpoint URL itself contains a literal space (`https://TBD/api/v1/ tms-2-ship-orders/{orderId}`) baked into the vendor document — now its own lint rule (`structure-url-whitespace`) rather than something that would have silently broken a generated client.

**Run on CV07_01:** a request schema with the full real nesting — arrays correctly wrapping `pickUp.dates`, `attributes`, `tags`, `items`, `handlingUnits`, `references`, etc.; objects correctly *not* wrapped for `consignor`/`customer`/`carrier`; the repeated-array-instance fields from Stage 1.5 correctly rendered as `enum` (e.g. `attributes.name: [carrier_code, origin_location_code, destination_location_code, client]`); and a `responses:` block built from the document's own HTTP Status Codes table (202 Accepted / 520 Server error, with their actual descriptions) rather than invented placeholders, since CV07_01 has no structured JSON response body. The same script ran against the two pre-existing, simpler IF-101/IF-102/IF-103 examples too — it handles both a deeply nested, path-based interface and a flat, no-path one without needing separate code paths.

This is a compile step, not a one-off: once a new interface's `fields.yaml`/`interfaces.yaml` exist and pass Stage 3's validation, `generate_openapi.py` produces its spec with no additional manual work — exactly the "second and further 100+ interfaces take less time" requirement, now extended to the Swagger deliverable itself, not just the Knowledge Hub's internal data.

### Stage 5 — Publish (no code change, just a rebuild)

The generated file replaces `src/data/exampleData.js`, `npm run build` runs, and the production bundle now contains the real CV07_01 data — confirmed by grepping the built bundle for `CV07_01` and for the two collision-resolved field IDs (`pickup-dates-datetime`, `consignee-dates-datetime`), both present. No React component was touched.

## What this means for interfaces #2 through #100+

| | Interface #1 (CV07_01, this run) | Interface #2 onward |
|---|---|---|
| Extraction | Built the script itself + ran it | Run the existing script (seconds) |
| Review | Wrote the first rule-list format + applied it | Write a short, interface-specific rule list (minutes) |
| Validate / Compile | Built both scripts + ran them | Run the existing scripts (seconds) |
| Net new engineering per interface | None — this was the one-time cost | None |

The work that doesn't scale down is the one-time pipeline build, which is now done. What's left per interface is: get the vendor's Word doc, run the extractor, spend a few minutes writing/adjusting the review rules for anything genuinely interface-specific, run validate+compile. That is the "second and further 100+ interfaces take less time" requirement.

## Known open items (flagged, not hidden)

- **16 fields on CV07_01 are genuinely incomplete in Andsoft's own document** (shown as `?` or without a source column) — these need an answer from Andsoft, not an engineering fix. See `REVIEW_REPORT.md`.
- **Swagger migration path**: when Andsoft does publish OpenAPI specs, `spec_type` flips from `vendor-template` to `OpenAPI` and `hasOwnSpec` becomes true — the data model already has a field for this, nothing structural changes.
- **Flows and Requirements are out of scope for this extraction.** Flows are designed by the architecture team (not read from a vendor interface doc) and Requirements/test evidence belong to Tower 2. The compiler already reflects that boundary rather than papering over it.
- **The field.schema.json enum doesn't model structural object/array container nodes** — by design (a glossary field is a business term, a container is structure). The container nesting isn't lost though: it's preserved on every leaf field via `path`.

## Files delivered

- `interface.schema.json` — the schema the old validator already expected but that didn't exist on disk yet.
- `Knowledge_Hub_Build_Pipeline.zip` — schemas, both domains (existing `oms_tms_planification` + new `cv07_shippeo`), all four scripts, the compiled output, and the source Word document.
- `Tower1_Integration_Knowledge_Hub_React_v2_CV07_01.zip` — the same React app, rebuilt with the real compiled data wired in (original hand-typed demo file kept alongside as `exampleData.manual_demo.js.bak` for comparison).
