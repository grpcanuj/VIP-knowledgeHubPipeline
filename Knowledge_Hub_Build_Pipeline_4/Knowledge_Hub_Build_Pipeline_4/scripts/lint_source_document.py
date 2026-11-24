#!/usr/bin/env python3
"""
lint_source_document.py
-------------------------
A document-quality linter, run right after extraction and before human
review. This is NOT the same job as REVIEW_REPORT.md (which flags fields
missing a source-column mapping). This checks the VENDOR DOCUMENT's own
internal consistency and completeness - the kind of thing an OpenAPI/Swagger
linter (spectral, openapi-lint, etc.) would catch if Andsoft's input were
already a machine-readable spec. Since it's a Word template instead, these
checks substitute for that.

Every rule below is something a reviewer could in principle catch by eye,
but won't reliably catch across 100+ documents and ~80 fields each -
exactly the kind of mechanical check that should never be a human's job.

Findings are written to DOC_QUALITY_REPORT.md next to REVIEW_REPORT.md.
The same rule set is what scripts/VENDOR_DOCUMENTATION_STANDARD.md is
distilled from - these checks ARE the standard, just expressed as code
instead of prose, so the two can never drift apart.

Usage:
    python3 lint_source_document.py <docx> --out-dir domains/<domain>
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from docx import Document

from extract_interface_from_docx import (
    extract_overview, extract_endpoint, extract_fields, parse_overview_bullets,
    extract_json_example, infer_kinds_and_examples_from_json, strip_brackets, ancestors_of,
    extract_required_headers, extract_field_validation_rules, extract_business_rules,
    find_table_by_header,
)

ACRONYM_ALLOWLIST = {"EAN", "VIN", "VIS", "CMR", "GPS", "RTTV", "UUID", "API", "URL", "ID"}

MEASURE_HINTS = ("weight", "volume", "quantity", "length", "width", "height", "distance")
UNIT_KEYWORDS = (
    "kg", "kilogram", "lb", "pound", "cm", "centimeter", "centimetre", "mm", "millimeter",
    "millimetre", "m3", "m³", "cubic", "liter", "litre", "km", "mile", "ton", "tonne", "gram",
)
CONDITIONAL_PATTERN = re.compile(r"mandatory|must be (?:filled|present)|required before", re.IGNORECASE)
DATETIME_FORMAT_PATTERN = re.compile(r"iso\s*8601|yyyy-mm-dd|utc|timezone", re.IGNORECASE)
AUTH_HEADER_PATTERN = re.compile(r"auth|api.?key|token", re.IGNORECASE)
AMBIGUOUS_NOTE_PATTERN = re.compile(r"to be confirmed|tbd|optional", re.IGNORECASE)


def check_camel_case(raw_fields):
    """Field/attribute names should be camelCase per the document's own
    Section 2.2 convention - flag anything that isn't, except recognised
    acronyms used as a whole name."""
    findings = []
    for f in raw_fields:
        name = f["leaf_name"]
        if name.upper() in ACRONYM_ALLOWLIST:
            continue
        if not re.match(r"^[a-z][a-zA-Z0-9]*$", name):
            findings.append({
                "rule": "naming-camelcase",
                "severity": "advisory",
                "path": f["path"],
                "message": f"'{name}' doesn't follow the document's own stated camelCase "
                           f"convention (Section 2.2) for JSON field names.",
            })
    return findings


def check_missing_description(raw_fields):
    findings = []
    for f in raw_fields:
        desc = (f["description"] or "").strip()
        if len(desc) < 8 and not f["fixed_value"]:
            findings.append({
                "rule": "completeness-description",
                "severity": "blocking",
                "path": f["path"],
                "message": f"No usable description for '{f['leaf_name']}' "
                           f"(got: {desc!r}). A reviewer can't tell what this field means "
                           f"without asking Andsoft.",
            })
    return findings


def check_source_mapping_gap(raw_fields):
    findings = []
    for f in raw_fields:
        if not f["source_field"] and not f["fixed_value"]:
            findings.append({
                "rule": "completeness-source-mapping",
                "severity": "blocking",
                "path": f["path"],
                "message": f"'{f['leaf_name']}' has neither a Field-AndSoft source column "
                           f"value nor a 'Fixed value:' note - genuinely unmapped, needs an "
                           f"answer from Andsoft before this field can be built against.",
            })
    return findings


def check_fixed_value_source_mismatch(raw_fields):
    """If the description says 'Fixed value: X' but the AndSoft source
    column shows something else, the document contradicts itself."""
    findings = []
    for f in raw_fields:
        if f["fixed_value"] and f["source_field"]:
            a = f["fixed_value"].strip().strip("'\"").lower()
            b = f["source_field"].strip().strip("'\"").lower()
            if a != b and a not in b and b not in a:
                findings.append({
                    "rule": "consistency-fixed-value",
                    "severity": "advisory",
                    "path": f["path"],
                    "message": f"Description says \"Fixed value: {f['fixed_value']}\" but the "
                               f"AndSoft source column shows \"{f['source_field']}\" - confirm "
                               f"which one is actually correct.",
                })
    return findings


def check_repeated_leaf_different_context(raw_fields):
    """The exact issue flagged by the reviewer: the same attribute name
    (dateTime, name, identifier, qualifier...) recurs under different
    parent objects. That's often fine (pickUp.name vs consignee.name are
    legitimately different business concepts) - but it should be an
    explicit, confirmed judgement call, not something that slides through
    unexamined. One finding per distinct leaf name with 2+ distinct
    parents, listing every context side by side."""
    by_leaf = defaultdict(list)
    for f in raw_fields:
        by_leaf[f["leaf_name"]].append(f)
    findings = []
    for leaf, occurrences in by_leaf.items():
        parents = sorted({o["parent"] for o in occurrences})
        if len(parents) > 1:
            contexts = "; ".join(f"{o['parent']} (\"{o['description'][:60]}\")" for o in occurrences)
            findings.append({
                "rule": "semantics-repeated-name",
                "severity": "informational",
                "path": leaf,
                "message": f"'{leaf}' appears under {len(parents)} different parents: {contexts}. "
                           f"Confirm these are genuinely distinct fields with the meaning stated per "
                           f"context, not a copy-paste artifact in the source document.",
            })
    return findings


def check_duplicate_full_path(raw_fields):
    """A path repeating isn't automatically an error: Andsoft's template
    sometimes documents a repeatable array slot (e.g. a generic {name,
    value} attribute pair) by showing several concrete example rows
    instead of describing the shape once. That's legitimate - it's how
    the document communicates the array's allowed values - so it's only
    flagged as a real duplicate-row mistake when the repeats are IDENTICAL
    (same description AND same fixed value, i.e. truly nothing new on the
    second row). Repeats with different values are reclassified as
    'repeated array instance' and marked informational, not blocking -
    exactly the pattern spotted in CV07_01's attributes/tags/references
    arrays, each shown via 3-4 example rows with different values."""
    by_path = defaultdict(list)
    for f in raw_fields:
        by_path[f["path"]].append(f)

    findings = []
    for path, occurrences in by_path.items():
        if len(occurrences) < 2:
            continue
        signatures = {(o["description"].strip(), o["fixed_value"]) for o in occurrences}
        if len(signatures) == 1:
            findings.append({
                "rule": "structure-duplicate-path",
                "severity": "advisory",
                "path": path,
                "message": f"The exact same path '{path}' appears {len(occurrences)} times with "
                           f"identical description and value - nothing is missing or wrong (the "
                           f"repeated value IS the complete, unambiguous answer), but the document "
                           f"could say it once instead of {len(occurrences)} times.",
            })
        else:
            values = ", ".join(sorted({o["fixed_value"] for o in occurrences if o["fixed_value"]}))
            findings.append({
                "rule": "structure-repeated-array-instance",
                "severity": "informational",
                "path": path,
                "message": f"'{path}' is documented via {len(occurrences)} example rows with "
                           f"different values ({values or 'varies'}) rather than one row describing "
                           f"the array shape once. Not an error - this is how the glossary learns the "
                           f"allowed values - but worth feeding back to Andsoft as a documentation "
                           f"pattern: describe the repeatable shape once, with a short table of known "
                           f"values, rather than repeating the full row per example.",
            })
    return findings


def check_container_type_vs_example(raw_fields, example):
    """The Type column (object/array) in the field-mapping table is NOT
    always consistent with the document's own worked JSON example - and the
    example is the ground truth, since that's the literal bytes a real
    integration would send/receive. A mismatch here isn't a minor wording
    issue: it means a generated OpenAPI schema (or anyone hand-building
    against the table alone) would get the wrong shape - an object where
    the wire format is actually an array, or vice versa."""
    if not example:
        return [{
            "rule": "completeness-no-json-example",
            "severity": "advisory",
            "path": "(document)",
            "message": "No parseable worked JSON example found in the document - container "
                       "object/array typing could only be checked against the Type column, "
                       "which is known to be unreliable on its own (see the next check when an "
                       "example IS present). Ask Andsoft to include one.",
        }]

    kinds, _examples = infer_kinds_and_examples_from_json(example)

    # Rebuild each container's DECLARED kind the same way extract_fields does
    # (via the '[]' suffix convention), from the raw per-leaf paths.
    declared = {}
    for f in raw_fields:
        ancestors = ancestors_of(f["path"])  # already strips '[]', so re-derive with markers
        segs = f["path"].split(".")[:-1]
        cur = ""
        for seg in segs:
            is_array = seg.endswith("[]")
            name = seg[:-2] if is_array else seg
            cur = f"{cur}.{name}" if cur else name
            declared[cur] = "array" if is_array else "object"

    findings = []
    for path, declared_kind in sorted(declared.items()):
        actual_kind = kinds.get(path)
        if actual_kind and actual_kind != declared_kind:
            findings.append({
                "rule": "structure-type-vs-example-mismatch",
                "severity": "blocking",
                "path": path,
                "message": f"The field-mapping table's Type column says '{declared_kind}', but the "
                           f"document's own worked JSON example shows '{path}' as an '{actual_kind}'. "
                           f"The example is treated as ground truth for the generated OpenAPI schema; "
                           f"the Type column disagreement itself should go back to Andsoft.",
            })
    return findings


def check_endpoint_placeholders(endpoint, overview_kv):
    findings = []
    url = endpoint.get("url", "")
    if re.search(r"\s", url):
        findings.append({
            "rule": "structure-url-whitespace",
            "severity": "blocking",
            "path": "(endpoint)",
            "message": f"Endpoint URL contains a literal space: '{url}'. This will produce a broken "
                       f"path in any generated client/server code - confirm the real URL with Andsoft "
                       f"rather than silently stripping the space.",
        })
    if "TBD" in url.upper():
        findings.append({
            "rule": "completeness-endpoint-url",
            "severity": "blocking",
            "path": "(endpoint)",
            "message": f"Endpoint URL is still a placeholder: '{url}'. This needs a real value "
                       f"from Andsoft before cutover, even if build can start against the rest "
                       f"of the contract.",
        })
    return findings


def check_coverage_gaps(doc, required_headers, field_validation_rules, business_rules):
    """Three tables in Andsoft's template carry real contract content that
    used to be silently dropped entirely: the HTTP headers/auth table, the
    field-level validation-rules table, and the numbered business-rules
    table. Now that the extractor reads all three, this check guards
    against the NEXT interface's template quietly breaking that - if a
    table matching one of these shapes exists with data rows but nothing
    was extracted from it, something is wrong with either the document or
    the extractor, and it should stop the build rather than slide through
    unnoticed the way these three tables did for CV07_01."""
    findings = []
    checks = [
        (["header", "value"], required_headers, "an HTTP headers/auth table (Header | Value | Notes)"),
        (["rule", "error"], field_validation_rules, "a field-level validation-rules table (Field | Rule | Error code)"),
        (["rule", "notes"], business_rules, "a numbered business-rules table (# | Rule | Notes)"),
    ]
    for tokens, extracted, label in checks:
        t = find_table_by_header(doc, tokens)
        if t is not None and len(t.rows) > 1 and not extracted:
            header_cells = [c.text.strip() for c in t.rows[0].cells]
            findings.append({
                "rule": "coverage-ignored-tables",
                "severity": "blocking",
                "path": "(document structure)",
                "message": f"Found {label} with header row {header_cells} and data rows, but zero "
                           f"records were extracted from it. Either this table's row format doesn't "
                           f"match what the extractor expects, or this content is being silently "
                           f"dropped - check it by hand before promoting this interface.",
            })
    return findings


def check_auth_method(required_headers):
    """CV07_01's own headers table lists 'Authorization' TWICE - once
    marked flatly 'Required' (Bearer token), once marked 'Optional / To be
    confirmed' - alongside a third candidate, 'X-API-Key', also 'Optional /
    To be confirmed'. That's a direct self-contradiction, not just an
    unresolved choice: the document can't simultaneously require and not
    require the same header. A client/server can't be built, and an
    OpenAPI securitySchemes block can't be generated correctly, without
    Andsoft resolving this to one method."""
    findings = []
    auth_like = [h for h in required_headers if AUTH_HEADER_PATTERN.search(h["header"])]
    if len(auth_like) < 2:
        return findings
    ambiguous = [h for h in auth_like if AMBIGUOUS_NOTE_PATTERN.search(h.get("notes", ""))]
    distinct_names = sorted({h["header"] for h in auth_like})
    conflicting_same_header = any(
        len({h["required"] for h in auth_like if h["header"] == name}) > 1
        for name in distinct_names
    )
    if len(distinct_names) >= 2 and (ambiguous or conflicting_same_header):
        detail = "; ".join(
            f"`{h['header']}` ({'required' if h['required'] else 'optional'}" +
            (f": {h['notes']}" if h.get("notes") else "") + ")"
            for h in auth_like
        )
        findings.append({
            "rule": "completeness-auth-method",
            "severity": "blocking",
            "path": "(endpoint headers)",
            "message": f"The headers table lists more than one candidate authentication mechanism, "
                       f"with conflicting or unresolved requirement status: {detail}. The actual "
                       f"authentication method for this interface isn't decided; confirm one, "
                       f"definitive method with Andsoft before cutover.",
        })
    return findings


def check_conditional_mandatory_rules(business_rules, field_validation_rules):
    """BR-01 in CV07_01 names nine specific fields that are 'mandatory
    before the first PLN can be sent' - a genuinely CONDITIONAL requirement
    - yet REVIEW_REPORT.md's own disclosed default is 'every field
    defaulted to status: mandatory' with no conditional distinction. This
    doesn't try to auto-map business-language field names (e.g. 'ETD',
    'Truck plate') to glossary field_ids - that mapping is a judgement
    call, not something worth faking with fragile fuzzy matching - it
    surfaces every conditional-mandatory rule so a reviewer can make that
    call deliberately instead of it staying invisible."""
    findings = []
    for br in business_rules:
        text = f"{br.get('rule', '')} {br.get('notes', '')}"
        if CONDITIONAL_PATTERN.search(text):
            findings.append({
                "rule": "consistency-conditional-mandatory",
                "severity": "advisory",
                "path": f"(business rule {br.get('id') or '?'})",
                "message": f"Business rule {br.get('id') or '?'} states a conditional requirement: "
                           f"\"{br.get('rule', '').strip()}\" Confirm the glossary field(s) this refers "
                           f"to are marked status: conditional (citing this rule) rather than left at "
                           f"the default plain mandatory/optional.",
            })
    for fv in field_validation_rules:
        text = f"{fv.get('rule', '')} {fv.get('message', '')}"
        if fv.get("field") and CONDITIONAL_PATTERN.search(text):
            findings.append({
                "rule": "consistency-conditional-mandatory",
                "severity": "advisory",
                "path": fv.get("field", ""),
                "message": f"Validation rule on '{fv.get('field')}' states: \"{fv.get('rule', '').strip()}\" "
                           f"Confirm the corresponding glossary field(s) reflect this conditional "
                           f"requirement rather than the default plain mandatory status.",
            })
    return findings


def check_datetime_format(raw_fields, field_validation_rules, business_rules):
    """CV07_01 states its date/time format convention (ISO 8601 UTC) only
    once, centrally, in the validation-rules table - not per field. That's
    fine as long as it's stated SOMEWHERE; this flags the document-level
    case where it's stated nowhere at all, which would otherwise only
    surface once someone tries to build the OpenAPI format/pattern and
    has no source to confirm it against."""
    datetime_fields = [f for f in raw_fields if f["data_type"] in ("date", "datetime")]
    if not datetime_fields:
        return []
    all_text = " ".join(f"{r.get('rule', '')} {r.get('message', '')}" for r in field_validation_rules)
    all_text += " " + " ".join(f"{r.get('rule', '')} {r.get('notes', '')}" for r in business_rules)
    if DATETIME_FORMAT_PATTERN.search(all_text):
        return []
    return [{
        "rule": "completeness-datetime-format",
        "severity": "advisory",
        "path": "(document structure)",
        "message": f"{len(datetime_fields)} date/datetime field(s) are defined, but no format or "
                   f"timezone convention (e.g. ISO 8601 UTC) is stated anywhere in the document - "
                   f"neither per field nor in a central validation rule. Confirm the expected format "
                   f"with Andsoft.",
    }]


def check_units_in_description(raw_fields):
    """grossWeight (float(5.3), description 'Weight of the car') never
    states its unit anywhere in the description - it's only inferable from
    the AndSoft source-column name TMQTUNIT_KG. A numeric field whose unit
    lives only in a source-system code name, not in text a reader can
    check, is a real ambiguity risk for anyone building against the
    document rather than the source system."""
    findings = []
    for f in raw_fields:
        if f["data_type"] != "decimal":
            continue
        name_l = f["leaf_name"].lower()
        desc_l = f["description"].lower()
        if not any(h in name_l or h in desc_l for h in MEASURE_HINTS):
            continue
        if any(u in desc_l for u in UNIT_KEYWORDS):
            continue
        source = f.get("source_field") or ""
        hint = (f" (its AndSoft source column name '{source}' may hint at one, but that shouldn't "
                f"be the only place the unit is stated)") if any(u in source.lower() for u in UNIT_KEYWORDS) else ""
        findings.append({
            "rule": "completeness-units",
            "severity": "advisory",
            "path": f["path"],
            "message": f"'{f['leaf_name']}' ({f['description'] or 'no description'}) looks like a "
                       f"measurable quantity but its description doesn't state a unit of measure{hint}. "
                       f"Confirm the unit explicitly with Andsoft.",
        })
    return findings


SEVERITY_ORDER = {"blocking": 0, "advisory": 1, "informational": 2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx_path")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    doc = Document(args.docx_path)
    overview = extract_overview(doc)
    overview_kv = parse_overview_bullets(overview["raw_bullets"])
    endpoint = extract_endpoint(doc)
    raw_fields = extract_fields(doc)
    json_example = extract_json_example(doc)
    required_headers = extract_required_headers(doc)
    field_validation_rules = extract_field_validation_rules(doc)
    business_rules = extract_business_rules(doc)

    findings = []
    findings += check_camel_case(raw_fields)
    findings += check_missing_description(raw_fields)
    findings += check_source_mapping_gap(raw_fields)
    findings += check_fixed_value_source_mismatch(raw_fields)
    # check_repeated_leaf_different_context (rule: semantics-repeated-name) is
    # intentionally NOT run here. The same leaf name recurring under different
    # PARENT objects (e.g. consignor.city / customer.city / carrier.city) is
    # normal, expected schema reuse - the parent is the namespace, exactly like
    # two DB tables both having an `id` column - not a document defect. Flagging
    # it, even as informational, was just noise for a reviewer to wade through.
    # The function is kept for reference/possible future use; it is simply not
    # wired into the active check list. (What IS still worth flagging - the
    # same field SLOT under the SAME parent overloaded for unrelated meanings,
    # e.g. attributes.name / tags.label - is covered separately by
    # check_duplicate_full_path's structure-repeated-array-instance finding.)
    findings += check_duplicate_full_path(raw_fields)
    findings += check_endpoint_placeholders(endpoint, overview_kv)
    findings += check_container_type_vs_example(raw_fields, json_example)
    findings += check_coverage_gaps(doc, required_headers, field_validation_rules, business_rules)
    findings += check_auth_method(required_headers)
    findings += check_conditional_mandatory_rules(business_rules, field_validation_rules)
    findings += check_datetime_format(raw_fields, field_validation_rules, business_rules)
    findings += check_units_in_description(raw_fields)

    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))

    out_path = Path(args.out_dir) / "DOC_QUALITY_REPORT.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    by_severity = defaultdict(list)
    for f in findings:
        by_severity[f["severity"]].append(f)

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(f"# Document quality report - {Path(args.docx_path).name}\n\n")
        fh.write(
            "Checks the vendor document's own internal consistency and completeness - "
            "distinct from REVIEW_REPORT.md, which only flags fields with no source-column "
            "mapping. Every rule here is also written up, in plain language, in "
            "VENDOR_DOCUMENTATION_STANDARD.md - the two are kept in lockstep on purpose.\n\n"
        )
        fh.write(f"**{len(by_severity['blocking'])} blocking · {len(by_severity['advisory'])} advisory · "
                 f"{len(by_severity['informational'])} informational**\n\n")

        for sev, title in [
            ("blocking", "## Blocking - resolve before this interface is built against"),
            ("advisory", "## Advisory - likely fine, worth a second look"),
            ("informational", "## Informational - judgement calls to confirm, not necessarily problems"),
        ]:
            items = by_severity[sev]
            fh.write(f"{title} ({len(items)})\n\n")
            if not items:
                fh.write("None.\n\n")
                continue
            for it in items:
                fh.write(f"- **[{it['rule']}]** `{it['path']}` — {it['message']}\n")
            fh.write("\n")

    print(f"Wrote {out_path}")
    print(f"{len(by_severity['blocking'])} blocking, {len(by_severity['advisory'])} advisory, "
          f"{len(by_severity['informational'])} informational finding(s).")
    return 1 if by_severity["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
