#!/usr/bin/env python3
"""
extract_interface_from_docx.py
-------------------------------
Turns one Andsoft "Technical Analysis" Word template into DRAFT Knowledge Hub
YAML (a fields file + an interfaces file) plus a review report, instead of a
human re-typing ~80 rows by hand for every interface.

This is step 1 of the repeatable pipeline: it gets you to a 90%-complete
draft in seconds. A human still reviews the flagged items (anything in the
review report), then the draft is promoted into domains/<name>/ and run
through validate_all.py + compile_knowledge_hub.py like any other domain.

Usage:
    python3 extract_interface_from_docx.py <path-to-docx> \
        --id CV07_01 --name CV07_01_TMS_SHIP_ORDERS \
        --out-dir domains/cv07_shippeo

What it reads from the document (by heading, not by fixed position, so it
survives minor template drift):
    - "Overview" section            -> source/target system, flow direction,
                                        operation, trigger, description
    - "3.x Endpoint" table           -> method, URL, idempotency, side effects
    - the nested field-mapping table (the one with a "Rank" column going
      0/1/2/3/4) -> every leaf field, its JSON path, data type, description,
      the vendor's own source-system column name, and any "Fixed value: X"
      constant called out in the description
    - "5. Business Rules" table     -> carried into the interface description
                                        as freeform notes (not modelled as
                                        fields - they're cross-field rules,
                                        not single fields)

Container rows (type "object"/"array") are NOT turned into fields - only
leaf scalars are, because the Field schema (field.schema.json) models
atomic business terms, not structural JSON nodes. The nesting is preserved
on each leaf field via `path` so nothing is lost.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml
from docx import Document

TYPE_MAP = {
    "string": "string",
    "boolean": "boolean",
    "datetime": "datetime",
    "date": "date",
    "object": "object",
    "array": "array",
}


def slugify(s):
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def parse_type_cell(raw):
    """'**string(35)**' -> ('string', '35') ; '**float(2.6)**' -> ('decimal', '2.6') ; '**boolean**' -> ('boolean', None)"""
    t = raw.strip().strip("*").strip()
    m = re.match(r"([a-zA-Z]+)\(?([0-9.]*)\)?", t)
    if not m:
        return t.lower(), None
    base, size = m.group(1).lower(), m.group(2) or None
    if base == "float":
        base = "decimal"
    if base == "datetime":
        base = "datetime"
    return base, size


def find_table_by_header(doc, must_contain):
    """Return the first table whose header row contains all of must_contain (case-insensitive substrings)."""
    for t in doc.tables:
        if not t.rows:
            continue
        header_cells = [c.text.strip().lower() for c in t.rows[0].cells]
        header_text = " | ".join(header_cells)
        if all(any(tok in hc for hc in header_cells) for tok in must_contain):
            return t
    return None


def extract_overview(doc):
    """Pull the bullet list under the 'Overview' heading."""
    overview = {"raw_bullets": [], "description": ""}
    capture = False
    desc_lines = []
    for p in doc.paragraphs:
        style = (p.style.name or "")
        text = p.text.strip()
        if style.startswith("Heading") and text.lower().startswith("overview"):
            capture = True
            continue
        if capture and style.startswith("Heading"):
            break
        if capture and text:
            clean = text.lstrip("-• ").strip()
            # Treat as a "Key: value" bullet regardless of the paragraph's
            # Word style name (templates vary in whether bullets use the
            # built-in "List Bullet" style or a custom numbered style) -
            # the reliable signal is the "Key: value" shape itself.
            if re.match(r"^[A-Za-z][A-Za-z /]{2,30}:\s*\S", clean):
                overview["raw_bullets"].append(clean)
            else:
                desc_lines.append(text)
    overview["description"] = " ".join(desc_lines).strip()
    return overview


def parse_overview_bullets(bullets):
    """Turn 'Source system: AndSoft TMS' style bullets into a dict."""
    out = {}
    for b in bullets:
        if ":" in b:
            k, v = b.split(":", 1)
            out[slugify(k)] = v.strip()
    return out


def extract_endpoint(doc):
    """3.1 Description table: Purpose / Direction / Requester / Responder / Method / URL / Content-Type / Idempotent / Side effects."""
    t = find_table_by_header(doc, ["purpose"]) or find_table_by_header(doc, ["method", "url"])
    info = {}
    if not t:
        return info
    for row in t.rows:
        cells = [c.text.strip() for c in row.cells]
        if len(cells) < 2:
            continue
        key = slugify(cells[0])
        val = " ".join(c for c in cells[1:] if c).strip()
        if key and val:
            info[key] = val
    return info


def extract_status_codes(doc):
    """The 'HTTP Status Codes' table (Code | Meaning | When returned) - needed
    to generate a real OpenAPI `responses:` block for interfaces like CV07_01
    that have no structured JSON response body, only status-code semantics."""
    t = find_table_by_header(doc, ["code", "meaning"]) or find_table_by_header(doc, ["code", "when"])
    codes = []
    if t is None:
        return codes
    for row in t.rows[1:]:
        cells = [c.text.strip() for c in row.cells]
        if len(cells) < 2 or not cells[0]:
            continue
        code_match = re.match(r"^\s*(\d{3})", cells[0])
        if not code_match:
            continue
        codes.append({
            "code": code_match.group(1),
            "meaning": cells[1] if len(cells) > 1 else "",
            "description": cells[2] if len(cells) > 2 else "",
        })
    return codes


def extract_required_headers(doc):
    """The HTTP headers/auth table (Header | Value | Notes). This is where an
    ambiguous or undecided authentication mechanism actually lives in the
    document - e.g. CV07_01 lists both a Bearer-token Authorization header
    AND an X-API-Key header, each marked 'Optional / To be confirmed',
    meaning the real auth method isn't decided yet. Previously this whole
    table was never read at all."""
    t = find_table_by_header(doc, ["header", "value"])
    headers = []
    if t is None:
        return headers
    for row in t.rows[1:]:
        cells = [c.text.strip() for c in row.cells]
        if len(cells) < 2 or not cells[0]:
            continue
        name = cells[0]
        value = cells[1] if len(cells) > 1 else ""
        notes = cells[2] if len(cells) > 2 else ""
        required = bool(re.search(r"required", notes, re.IGNORECASE)) and not re.search(r"optional", notes, re.IGNORECASE)
        headers.append({"header": name, "value": value, "notes": notes, "required": required})
    return headers


def extract_field_validation_rules(doc):
    """The field-level validation-rules table (Field | Rule | Error code |
    Error message / Note) - e.g. 'all *Date/dateTime fields must be ISO 8601
    UTC' or 'estimatedDepartureDate must not be earlier than today'. This is
    exactly the kind of constraint an OpenAPI schema should carry (format,
    pattern, a documented business condition) and previously it was dropped
    entirely - the field-mapping table was the only thing read."""
    t = find_table_by_header(doc, ["rule", "error"])
    rules = []
    if t is None:
        return rules
    for row in t.rows[1:]:
        cells = [c.text.strip() for c in row.cells]
        if len(cells) < 2 or not any(cells):
            continue
        rules.append({
            "field": cells[0] if len(cells) > 0 else "",
            "rule": cells[1] if len(cells) > 1 else "",
            "error_code": cells[2] if len(cells) > 2 else "",
            "message": cells[3] if len(cells) > 3 else "",
        })
    return rules


def extract_business_rules(doc):
    """The numbered business-rules table (# | Rule | Notes) - e.g. BR-01
    through BR-06 in CV07_01, defining when a PLN vs. an APLN is triggered
    and which fields become conditionally mandatory before the first PLN.
    This is the actual cross-field business logic of the interface and was
    previously dropped entirely - nothing in fields.yaml/interfaces.yaml
    reflected it."""
    t = find_table_by_header(doc, ["rule", "notes"])
    rules = []
    if t is None:
        return rules
    for row in t.rows[1:]:
        cells = [c.text.strip() for c in row.cells]
        if len(cells) < 2 or not any(cells):
            continue
        rules.append({
            "id": cells[0] if len(cells) > 0 else "",
            "rule": cells[1] if len(cells) > 1 else "",
            "notes": cells[2] if len(cells) > 2 else "",
        })
    return rules


def extract_json_example(doc):
    """Parses the worked 'Request body example' JSON block, when present.
    This is used as GROUND TRUTH for array-vs-object container typing - the
    Type column in the field-mapping table is not always consistent with the
    document's own example (see check_container_type_vs_example in
    lint_source_document.py, which found 9 such mismatches in CV07_01: e.g.
    'consignor' is typed array in the table but shown as a plain object in
    the example; 'tags'/'attributes'/'items'/'handlingUnits' are typed
    object but shown as arrays). It's also used to pull realistic example
    values into the generated OpenAPI spec instead of inventing placeholders.
    """
    capture = False
    lines = []
    for p in doc.paragraphs:
        style = p.style.name or ""
        text = p.text
        if style.startswith("Heading") and "example" in text.lower():
            capture = True
            continue
        if capture and style.startswith("Heading"):
            break
        if capture:
            lines.append(text)
    raw = "\n".join(lines).strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def infer_kinds_and_examples_from_json(example):
    """Walk a parsed JSON example, returning (kinds, examples).
    kinds: {dotted.path: 'object'|'array'} for every container found.
    examples: {dotted.path: representative scalar value} for every leaf found.
    Paths never carry '[]' markers here - an array and its item object share
    the same conceptual path (an array's items don't add their own path
    segment), so kind is looked up by plain dotted path, not encoded in it.
    """
    kinds, examples = {}, {}

    def walk(node, path):
        if isinstance(node, list):
            kinds[path] = "array"
            if node:
                item = node[0]
                # IMPORTANT: do not recurse via walk(item, path) here - that
                # would re-enter the dict/list branch below AT THE SAME PATH
                # and immediately overwrite the "array" marking we just set
                # with "object" (an array's items don't get their own path
                # segment, but they must not re-classify the array's own
                # path either). Instead, step directly into the item's
                # children, skipping the item's own classification.
                if isinstance(item, dict):
                    for k, v in item.items():
                        walk(v, f"{path}.{k}" if path else k)
                elif isinstance(item, list):
                    walk(item, path)  # array-of-arrays: genuinely same path, fine to recurse
                else:
                    examples.setdefault(path, item)
            return
        if isinstance(node, dict):
            kinds[path] = "object"
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
            return
        examples.setdefault(path, node)

    if example:
        for k, v in example.items():
            walk(v, k)
    return kinds, examples


def strip_brackets(path):
    """'shipment.orders[].pickUp.name' -> 'shipment.orders.pickUp.name' -
    the plain dotted path used to look up kinds/examples from the JSON
    example, which doesn't encode array-ness in the path itself."""
    return ".".join(seg[:-2] if seg.endswith("[]") else seg for seg in path.split("."))


def correct_paths_against_example(raw_fields, example):
    """Re-derive each field's '[]' array markers from the document's own
    worked JSON example where it's available, instead of trusting the
    Type column alone (see infer_kinds_and_examples_from_json - the Type
    column disagreed with the example for 9 of CV07_01's 25 containers).
    Falls back to the original Type-column-derived marker wherever the
    example doesn't cover a given branch. field_id naming is unaffected
    (it's derived from segment NAMES, never from the '[]' marker), so this
    only improves the stored `path` metadata's accuracy - nothing is
    renamed or re-keyed."""
    kinds, _ = infer_kinds_and_examples_from_json(example)
    if not kinds:
        return raw_fields
    for f in raw_fields:
        segs = f["path"].split(".")
        corrected = []
        cur_plain = ""
        for i, seg in enumerate(segs):
            is_leaf = (i == len(segs) - 1)
            name = seg[:-2] if seg.endswith("[]") else seg
            cur_plain = f"{cur_plain}.{name}" if cur_plain else name
            if is_leaf:
                corrected.append(name)
                continue
            kind = kinds.get(cur_plain)
            if kind == "array":
                corrected.append(name + "[]")
            elif kind == "object":
                corrected.append(name)
            else:
                corrected.append(seg)  # example doesn't cover this branch - keep original
        f["path"] = ".".join(corrected)
    return raw_fields


def extract_fields(doc):
    """
    The nested field-mapping table has columns: Rank, Field, Type, Description,
    Field AndSoft (vendor source-column name). Rank is the nesting depth
    (0 = top container, 1/2/3/4 = deeper). We walk rows top to bottom,
    maintaining a path stack keyed by rank, so every leaf gets its full
    dotted path, e.g. shipment.orders[].pickUp.dates[].dateTime.
    """
    t = find_table_by_header(doc, ["rank", "field", "type"])
    if t is None:
        raise RuntimeError(
            "Could not find the field-mapping table (expected a 'Rank | Field | Type | "
            "Description | Field AndSoft' header). The template may have changed - "
            "check find_table_by_header()."
        )

    # Resolve each column's PURPOSE from the header row's text, rather than
    # assuming a fixed column order. This is what lets the script survive a
    # template where Andsoft reordered their own columns (e.g. put "Field
    # AndSoft" before "Description") - something a position-based read would
    # silently get wrong instead of erroring. We still require the same SET
    # of columns to exist; a genuinely missing column (no andsoft-source
    # column at all) degrades gracefully (see andsoft_idx check below), but
    # a missing rank/field/type/description column is a hard stop, same as
    # not finding the table at all - better to stop than guess.
    header_cells = [c.text.strip().lower() for c in t.rows[0].cells]
    rank_idx = next((i for i, h in enumerate(header_cells) if "rank" in h), None)
    name_idx = next((i for i, h in enumerate(header_cells) if h.strip() == "field"), None)
    if name_idx is None:
        name_idx = next((i for i, h in enumerate(header_cells) if "field" in h and "andsoft" not in h), None)
    type_idx = next((i for i, h in enumerate(header_cells) if "type" in h), None)
    desc_idx = next((i for i, h in enumerate(header_cells) if "description" in h), None)
    andsoft_idx = next((i for i, h in enumerate(header_cells) if "andsoft" in h), None)

    missing = [n for n, i in [("rank", rank_idx), ("field", name_idx), ("type", type_idx), ("description", desc_idx)] if i is None]
    if missing:
        raise RuntimeError(
            f"Field-mapping table found, but couldn't identify the column(s) for: {', '.join(missing)}. "
            f"Header row read as: {header_cells}. The template's column labels changed enough that "
            f"automatic column detection failed - check this table by hand before proceeding; do not "
            f"guess a position, since the last column-reordering incident silently misassigned data."
        )
    if andsoft_idx is None:
        print(
            "NOTE: no 'Field AndSoft' (vendor source-column) column found in this table - "
            "every field will be flagged needs_review for a missing source column.",
            file=sys.stderr,
        )

    fields = []
    path_stack = {}  # rank -> name
    is_array_at_rank = {}

    rows = t.rows[1:]  # skip header
    for row in rows:
        cells = [c.text.strip() for c in row.cells]
        if len(cells) <= max(rank_idx, name_idx, type_idx, desc_idx):
            continue
        rank_raw, name_raw, type_raw, desc_raw = cells[rank_idx], cells[name_idx], cells[type_idx], cells[desc_idx]
        andsoft_raw = cells[andsoft_idx] if andsoft_idx is not None and andsoft_idx < len(cells) else ""

        if not rank_raw.strip().isdigit():
            continue
        rank = int(rank_raw.strip())
        name = name_raw.strip().strip("*").strip()
        if not name:
            continue

        base_type, size = parse_type_cell(type_raw)

        # Build path from ancestors (ranks 0..rank-1)
        ancestors = [path_stack[r] for r in sorted(path_stack) if r < rank]
        path = ".".join(ancestors + [name]) if ancestors else name
        # mark arrays encountered along the ancestor chain with []
        path_parts = []
        for r in sorted(path_stack):
            if r >= rank:
                break
            seg = path_stack[r]
            if is_array_at_rank.get(r):
                seg = seg + "[]"
            path_parts.append(seg)
        path = ".".join(path_parts + [name])

        if base_type in ("object", "array"):
            # container node: remember it on the stack, do not emit as a field
            path_stack[rank] = name
            is_array_at_rank[rank] = (base_type == "array")
            # truncate deeper stack levels (new branch starting)
            for r in list(path_stack):
                if r > rank:
                    path_stack.pop(r, None)
                    is_array_at_rank.pop(r, None)
            continue

        # leaf scalar field
        for r in list(path_stack):
            if r > rank:
                path_stack.pop(r, None)
                is_array_at_rank.pop(r, None)

        fixed_value = None
        m = re.search(r"[Ff]ixed value:\s*([^\n.]+)", desc_raw)
        if m:
            fixed_value = m.group(1).strip().rstrip(".")

        andsoft_source = andsoft_raw.strip().strip("[]").strip()
        if andsoft_source in ("", "?"):
            andsoft_source = None

        parent = path_parts[-1].replace("[]", "") if path_parts else "root"
        fields.append(
            {
                "leaf_name": name,
                "parent": parent,
                "path": path,
                "data_type": base_type,
                "size": size,
                "description": desc_raw.strip(),
                "fixed_value": fixed_value,
                "source_field": andsoft_source,
                "needs_review": andsoft_source is None or "?" in andsoft_raw or "TBD" in desc_raw.upper(),
            }
        )
    return fields


def dedupe_field_id(base, seen):
    base = slugify(base)
    if base not in seen:
        seen.add(base)
        return base
    i = 2
    while f"{base}-{i}" in seen:
        i += 1
    seen.add(f"{base}-{i}")
    return f"{base}-{i}"


def ancestors_of(path):
    """'shipment.orders[].pickUp.dates[].dateTime' -> ['shipment','orders','pickUp','dates']"""
    parts = [p.replace("[]", "") for p in path.split(".")]
    return parts[:-1]  # drop the leaf itself


def build_field_records(raw_fields, interface_id):
    """Collapse raw leaf rows into unique glossary Field records (by field_id),
    since the same leaf name (name/address/city/...) recurs under many
    parents and each occurrence is a *distinct* business concept.

    Naming starts from 1 level of ancestor context (parent-leaf, e.g.
    'pickup-name'). But generic array-wrapper names (dates, identifications,
    tags, attributes, references, items...) recur under *different*
    grandparents (pickUp.dates vs consignee.dates), so a 1-level name alone
    would silently collapse two distinct business fields into one. We detect
    that specific case - same (parent, leaf) combo reached via a different
    ancestor chain - and escalate those to 2-level names (grandparent-parent-
    leaf, e.g. 'pickup-dates-datetime' / 'consignee-dates-datetime') instead
    of silently losing one of the fields.
    """
    # Group occurrences by (parent, leaf_name) and record every distinct
    # ancestor chain seen for that combo.
    groups = {}
    for idx, f in enumerate(raw_fields):
        combo = (f["parent"], f["leaf_name"])
        anc = tuple(ancestors_of(f["path"]))
        groups.setdefault(combo, {}).setdefault(anc, []).append(idx)

    needs_escalation = {combo for combo, by_anc in groups.items() if len(by_anc) > 1}

    seen_ids = set()
    id_for_index = {}
    for combo, by_anc in groups.items():
        parent, leaf = combo
        for anc, idxs in by_anc.items():
            if combo in needs_escalation:
                grandparent = anc[-2] if len(anc) >= 2 else "root"
                base = f"{grandparent}-{parent}-{leaf}"
            else:
                base = f"{parent}-{leaf}"
            fid = dedupe_field_id(base, seen_ids)
            for i in idxs:
                id_for_index[i] = fid

    field_id_by_occurrence = [id_for_index[i] for i in range(len(raw_fields))]

    # second pass: build one Field record per unique field_id, AGGREGATING
    # every occurrence that shares that field_id - not just the first one.
    # This matters because a repeatable array slot (e.g. shipment.orders[].
    # attributes.{name,value}) legitimately recurs several times in the
    # document with different example values each time (carrier_code,
    # origin_location_code, destination_location_code, client, ...). Taking
    # only the first occurrence's fixed_value/description would silently
    # throw the other examples away. Instead, every distinct fixed_value
    # seen across occurrences is collected: a single value stays a plain
    # fixed-value note, two or more distinct values is evidence of a
    # controlled vocabulary, so the field is promoted to data_type "enum"
    # with those values as allowed_values - a reviewer can rename it (e.g.
    # "attribute name" is really an enum of known attribute keys) but
    # nothing is lost by default.
    by_fid = {}
    for f, fid in zip(raw_fields, field_id_by_occurrence):
        by_fid.setdefault(fid, []).append(f)

    field_records = []
    for fid, occurrences in by_fid.items():
        first = occurrences[0]
        name_human = first["leaf_name"][0].upper() + re.sub(r"(?<!^)(?=[A-Z])", " ", first["leaf_name"][1:])
        name_human = f"{first['parent'].replace('-', ' ').title()} {name_human}".strip()

        distinct_fixed_values = []
        for o in occurrences:
            if o["fixed_value"] and o["fixed_value"] not in distinct_fixed_values:
                distinct_fixed_values.append(o["fixed_value"])

        # Distinct free-text descriptions across occurrences - NOT the same
        # thing as distinct fixed values. tags.label in CV07_01 has no fixed
        # value on any occurrence, but 4 completely different meanings
        # ("Traffic code" / "SAP code of the carrier" / "RTTV system of the
        # customer" / "trip is in rupture flag"). Picking just one (even the
        # longest) would silently discard the other three meanings. Keep all
        # of them, in document order, deduplicated.
        distinct_descriptions = []
        for o in occurrences:
            d = o["description"].strip()
            if d and d not in distinct_descriptions:
                distinct_descriptions.append(d)

        if len(distinct_descriptions) <= 1:
            description = distinct_descriptions[0] if distinct_descriptions else ""
        else:
            description = (
                f"Reused for {len(distinct_descriptions)} distinct purposes across the array slots "
                f"this field appears in: " + " | ".join(distinct_descriptions)
            )

        data_type = first["data_type"] if first["data_type"] in (
            "string", "integer", "decimal", "boolean", "date", "datetime", "enum"
        ) else "string"

        rec = {
            "field_id": fid,
            "name": name_human,
            "description": description or f"{first['leaf_name']} under {first['parent']}.",
            "data_type": data_type,
            "status": "mandatory",
            "source_system": "AndSoft TMS",
            "sensitivity": "internal",
            "quality_rules": [],
            "_review": {
                "andsoft_source_column": first["source_field"],
                "fixed_value": first["fixed_value"],
                "json_path": first["path"],
                "needs_review": any(o["needs_review"] for o in occurrences),
                "raw_size": first["size"],
                "occurrence_count": len(occurrences),
            },
        }

        if len(distinct_fixed_values) == 1:
            rec["quality_rules"].append(f"Fixed value supplied by the interface spec: {distinct_fixed_values[0]}")
        elif len(distinct_fixed_values) > 1:
            rec["data_type"] = "enum"
            rec["allowed_values"] = distinct_fixed_values
            rec["quality_rules"].append(
                f"Observed as a repeatable array slot with {len(occurrences)} documented example "
                f"value(s) in the source spec: {', '.join(distinct_fixed_values)}. Confirm with Andsoft "
                f"whether this is the complete set of allowed values or just the examples shown."
            )
        elif len(distinct_descriptions) > 1:
            rec["quality_rules"].append(
                f"This generic attribute name is reused for {len(distinct_descriptions)} unrelated "
                f"purposes across its occurrences, with no fixed value to tell them apart "
                f"programmatically - worth raising with Andsoft as a design question (should these "
                f"be separate named fields instead of one generic '{first['leaf_name']}'?) rather "
                f"than something the glossary can safely model as one field."
            )

        if first["size"]:
            rec["format"] = f"max length {first['size']}" if data_type == "string" else first["size"]
        field_records.append(rec)

    return field_records, field_id_by_occurrence


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx_path")
    ap.add_argument("--id", required=True, help="Interface ID, e.g. CV07_01")
    ap.add_argument("--name", required=True, help="Interface name, e.g. CV07_01_TMS_SHIP_ORDERS")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    doc = Document(args.docx_path)
    overview = extract_overview(doc)
    overview_kv = parse_overview_bullets(overview["raw_bullets"])
    endpoint = extract_endpoint(doc)
    status_codes = extract_status_codes(doc)
    required_headers = extract_required_headers(doc)
    field_validation_rules = extract_field_validation_rules(doc)
    business_rules = extract_business_rules(doc)
    json_example = extract_json_example(doc)
    raw_fields = extract_fields(doc)
    raw_fields = correct_paths_against_example(raw_fields, json_example)
    field_records, field_id_by_occurrence = build_field_records(raw_fields, args.id)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- draft fields.yaml ----
    fields_for_yaml = []
    review_notes = []
    for rec in field_records:
        review = rec.pop("_review")
        fields_for_yaml.append(rec)
        if review["needs_review"]:
            review_notes.append(
                f"- `{rec['field_id']}` (path `{review['json_path']}`): AndSoft source column not supplied "
                f"in the template (shown as '?' or TBD) - confirm with AndSoft before build."
            )

    fields_yaml_path = out_dir / "fields.draft.yaml"
    with open(fields_yaml_path, "w", encoding="utf-8") as fh:
        fh.write(f"# AUTO-GENERATED DRAFT from {Path(args.docx_path).name} - review before promoting.\n")
        fh.write(f"# Domain: {args.name}\n\n")
        yaml.safe_dump({"fields": fields_for_yaml}, fh, sort_keys=False, allow_unicode=True, width=100)

    # ---- draft interfaces.yaml ----
    interface_fields = []
    seen_ids = set()
    for f, fid in zip(raw_fields, field_id_by_occurrence):
        if fid in seen_ids:
            continue
        seen_ids.add(fid)
        entry = {"field_id": fid, "required": True, "io": "request", "path": f["path"]}
        if f["fixed_value"]:
            entry["fixed_value"] = f["fixed_value"]
        if f["source_field"]:
            entry["source_field"] = f["source_field"]
        interface_fields.append(entry)

    # protocol/frequency/owner used to be hardcoded literals here regardless of what the
    # document actually said - a real bug (see REVIEW_REPORT's "Defaults applied
    # automatically" note). trigger/source-system/content-type were already being parsed
    # into overview_kv/endpoint above and then discarded; use them instead.
    trigger_text = overview_kv.get("trigger") or endpoint.get("trigger") or "TBD"
    owner_value = overview_kv.get("owner") or overview_kv.get("source-system", "TBD")
    content_type = (endpoint.get("content-type") or "").strip().lower()
    message_format = {
        "application/json": "JSON",
        "application/xml": "XML",
        "text/xml": "XML",
        "text/csv": "CSV",
    }.get(content_type, endpoint.get("content-type", "TBD"))

    iface = {
        "id": args.id,
        "name": args.name,
        "description": overview["description"],
        "source_system": overview_kv.get("source-system", "TBD"),
        "target_system": overview_kv.get("target-system", "TBD"),
        "protocol": "REST",
        "method": endpoint.get("method", "POST"),
        "endpoint_url": endpoint.get("url", "TBD"),
        "frequency": trigger_text,
        "owner": owner_value,
        "spec_type": "vendor-template",
        "spec_version": "V1.0",
        "status": "documented",
        "idempotent": "No" not in endpoint.get("idempotent", "Yes"),
        "retry_policy": endpoint.get("idempotent", ""),
        "response_contract": "status-code only, no structured body (see endpoint table)",
        "response_status_codes": status_codes,
        "required_headers": required_headers,
        "field_validation_rules": field_validation_rules,
        "business_rules": business_rules,
        "fields": interface_fields,
        # --- new LLD fields (VIP RFP deliverables: HLD/LLD/RACI/etc) ---
        # flow_owner / message_format are derivable from what's already in the document.
        # The other four genuinely are not present in AndSoft's template (confirmed by
        # direct keyword search) and are left empty on purpose - see the review report's
        # "New LLD fields" section for what to fill in and how.
        "flow_owner": owner_value,
        "message_format": message_format,
        "volume_profile": None,
        "deduplication_strategy": None,
        "monitoring": None,
        "acceptance_criteria": [],
        "test_data_ref": None,
    }

    interfaces_yaml_path = out_dir / "interfaces.draft.yaml"
    with open(interfaces_yaml_path, "w", encoding="utf-8") as fh:
        fh.write(f"# AUTO-GENERATED DRAFT from {Path(args.docx_path).name} - review before promoting.\n\n")
        yaml.safe_dump({"interfaces": [iface]}, fh, sort_keys=False, allow_unicode=True, width=100)

    # ---- review report ----
    report_path = out_dir / "REVIEW_REPORT.md"
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(f"# Extraction review report - {args.name}\n\n")
        fh.write(f"Source document: `{Path(args.docx_path).name}`\n\n")
        fh.write(f"- Leaf fields extracted: **{len(field_records)}** unique glossary fields "
                 f"from **{len(raw_fields)}** payload occurrences\n")
        fh.write(f"- Overview bullets found: {len(overview['raw_bullets'])}\n")
        fh.write(f"- Endpoint info found: {'yes' if endpoint else 'no - check manually'}\n")
        fh.write(f"- Required headers table: {len(required_headers)} header(s) found\n")
        fh.write(f"- Field-level validation rules table: {len(field_validation_rules)} rule(s) found\n")
        fh.write(f"- Business rules table: {len(business_rules)} rule(s) found\n\n")
        if not required_headers or not field_validation_rules or not business_rules:
            missing = [n for n, v in (
                ("headers/auth", required_headers), ("field validation rules", field_validation_rules),
                ("business rules", business_rules)) if not v]
            fh.write(
                f"**Note:** no {', '.join(missing)} table was found in this document - either this "
                f"interface genuinely has none, or the template doesn't use the same table headers this "
                f"script looks for. Confirm by hand before assuming nothing was missed; see "
                f"`DOC_QUALITY_REPORT.md`'s `coverage-ignored-tables` check for an automated cross-check.\n\n"
            )
        fh.write("## Needs human review before promoting\n\n")
        if review_notes:
            fh.write("\n".join(review_notes) + "\n\n")
        else:
            fh.write("None flagged - still eyeball data_type/status/sensitivity defaults below.\n\n")
        fh.write(
            "## Defaults applied automatically (confirm or correct)\n\n"
            "- Every field defaulted to `status: mandatory`, `sensitivity: internal`, "
            "`source_system: AndSoft TMS` - the template doesn't carry these, so a reviewer "
            "must set the real value per field.\n"
            "- `data_type` defaults to `string` when the template used a type the schema "
            "doesn't recognise.\n"
            "- Interface `source_system` / `target_system` / `frequency` (from the Overview's "
            "`Trigger:` bullet) came from the document; confirm they parsed correctly.\n"
            "- `owner` defaults to the Overview's `Source system` bullet - this template has "
            "no explicit `Owner:` bullet, so confirm who is actually accountable.\n"
            "- `protocol` defaults to `REST` - this template never states a protocol "
            "explicitly; confirm manually for any interface that isn't a REST call.\n"
            f"- `flow_owner` defaults to the same value as `owner` (`{iface['owner']}`) - "
            "update it once RACI ownership is confirmed, if it differs.\n"
            f"- `message_format` derived from the endpoint table's Content-Type "
            f"(`{iface['message_format']}`).\n\n"
            "## New LLD fields - manual completion required\n\n"
            "These are not present anywhere in AndSoft's document (confirmed by direct "
            "keyword search across every paragraph and table cell) and are left empty on "
            "purpose - get the real value from the owning team during review/promote "
            "rather than guessing one:\n\n"
            "- `volume_profile` - expected volume, peak window, latency SLA.\n"
            f"- `deduplication_strategy` - this interface's own extracted `idempotent` flag "
            f"is `{iface['idempotent']}`, with retry policy: \"{(iface['retry_policy'] or '')[:160]}"
            f"{'...' if len(iface['retry_policy'] or '') > 160 else ''}\". Check whether any "
            "field marked `fixed_value` in fields.yaml (constant per message) is being assumed "
            "as a dedup key before relying on one - a fixed value can't disambiguate messages.\n"
            "- `monitoring` - key metrics, alert thresholds, dashboard/tool.\n"
            "- `acceptance_criteria` - UAT sign-off criteria for this interface.\n"
            "- `test_data_ref` - cross-reference to the Testing Hub's test-suite id, once assigned "
            "(Testing Hub scope itself is unchanged).\n"
        )

    print(f"Wrote {fields_yaml_path}")
    print(f"Wrote {interfaces_yaml_path}")
    print(f"Wrote {report_path}")
    print(f"\n{len(field_records)} unique fields from {len(raw_fields)} payload leaf occurrences.")
    print(f"{sum(1 for r in review_notes)} field(s) flagged for manual review.")


if __name__ == "__main__":
    main()
