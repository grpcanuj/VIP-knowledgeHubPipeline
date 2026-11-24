#!/usr/bin/env python3
"""
extract_interface_from_docx_xml.py
-----------------------------------
Counterpart of extract_interface_from_docx.py for the AndSoft *XML master-data*
template (e.g. CV10_01 - FMS -> TMS vehicule master data). That template differs
from the JSON "Rank" template: a flat mapping table (AndSoft Table | Column Name
| Column Type | FMS Source Field | XML Tag & Business Description), an embedded
XSD, several HTTP operations (POST/PUT/PATCH) on one root element, and requirement
levels written inside the description text ("Mandatory R" / "Optional O").

It writes the same artifacts as the JSON extractor, so validate_all.py,
compile_knowledge_hub.py, generate_openapi.py, generate_run_report.py and
generate_findings_tracker.py continue unchanged:
    fields.draft.yaml, interfaces.draft.yaml, REVIEW_REPORT.md, DOC_QUALITY_REPORT.md

The embedded XSD is treated as ground truth for the wire format (element names,
types, enumerations), the same way the JSON example is for the JSON template.

Usage:
    python scripts/extract_interface_from_docx_xml.py "<docx>" \
        --id CV10_01 --name CV10_01_MD_TRUCKS_TRAILERS --out-dir domains/cv10_fms [--promote]

--promote also writes fields.yaml / interfaces.yaml (skips the manual review step).
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import yaml
from docx import Document

from extract_interface_from_docx import dedupe_field_id, find_table_by_header, slugify

XS = "{http://www.w3.org/2001/XMLSchema}"
XSD_TYPE = {
    "string": "string", "boolean": "boolean", "int": "integer", "integer": "integer",
    "float": "decimal", "double": "decimal", "decimal": "decimal",
    "datetime": "datetime", "date": "date",
}
TABLE_TYPE = {
    "varchar": "string", "char": "string", "string": "string", "boolean": "boolean",
    "integer": "integer", "int": "integer", "float": "decimal", "decimal": "decimal",
    "datetime": "datetime", "date": "date",
}
TARGET_RE = re.compile(r"Target XML\s*<(\w+)>\s*\(([^)]*)\)\.?\s*")
HTTP_METHODS = "GET|POST|PUT|PATCH|DELETE"
SEVERITY_ORDER = {"blocking": 0, "advisory": 1, "informational": 2}


# ---------------------------------------------------------------- document readers

def paragraph_after(doc, marker):
    seen = False
    for p in doc.paragraphs:
        t = p.text.strip()
        if seen and t:
            return t
        if t.upper() == marker:
            seen = True
    return ""


def extract_description(doc):
    out, capture = [], False
    for p in doc.paragraphs:
        t = p.text.strip()
        if not capture:
            capture = t.upper() == "DESCRIPTION"
            continue
        if not t:
            continue
        if (p.style.name or "").startswith("Heading") or t.isupper():
            break
        out.append(t)
    return " ".join(out)


def extract_version(doc):
    t = find_table_by_header(doc, ["date", "action"])
    if t is not None and len(t.rows) > 1:
        m = re.search(r"\bV\d+(?:\.\d+)*\b", t.rows[-1].cells[1].text)
        if m:
            return m.group(0)
    return "V1.0"


def extract_endpoint(doc):
    info = {"style": None, "base_url": None, "headers": [], "operations": []}
    block = next((p.text for p in doc.paragraphs if p.text.strip().upper().startswith("END POINT")), "")
    section = None
    for line in block.splitlines():
        s = line.strip()
        low = s.lower()
        if not s:
            continue
        if low.startswith("architecture style:"):
            info["style"] = s.split(":", 1)[1].strip().split()[0]
        elif low.startswith("base url:"):
            info["base_url"] = s.split(":", 1)[1].strip()
        elif low.startswith("http headers"):
            section = "headers"
        elif low.startswith("operations"):
            section = "ops"
        elif s.startswith("-"):
            body = s.lstrip("- ").strip()
            if section == "headers" and ":" in body:
                name, value = body.split(":", 1)
                info["headers"].append({"header": name.strip(), "value": value.strip()})
            elif section == "ops":
                m = re.match(rf"^(.+?):\s*({HTTP_METHODS})\s+(\S+)", body)
                if m:
                    sc = re.search(r"Scenario\s+(\d+)", m.group(1))
                    info["operations"].append({
                        "name": m.group(1).strip(), "method": m.group(2),
                        "path": m.group(3), "scenario": int(sc.group(1)) if sc else None,
                    })
    return info


def extract_scenarios(doc):
    out = []
    for p in doc.paragraphs:
        t = p.text.strip()
        m = re.match(r"^Scenario\s+(\d+)\s*\S\s*(.+?):", t)
        if not m:
            continue
        method = re.search(rf"(?:synchronous\s+|\ba\s+)({HTTP_METHODS})\s+request", t, re.I)
        code = re.search(r"returns HTTP\s+(\d{3})", t)
        out.append({
            "number": int(m.group(1)), "name": m.group(2).strip(), "text": t,
            "method": method.group(1).upper() if method else None,
            "code": code.group(1) if code else None,
        })
    return out


def extract_cardinality_rules(doc):
    rules, post_mandatory = [], []
    for p in doc.paragraphs:
        t = p.text.strip()
        if re.match(rf"^-\s*({HTTP_METHODS})\s*\(", t) or t.startswith("To support partial payloads"):
            rules.append(t.lstrip("- ").strip())
        m = re.match(r"^-\s*POST\s*\(.*mandatory elements\s*\(([^)]+)\)", t)
        if m:
            post_mandatory = [x.strip() for x in m.group(1).split(",") if x.strip()]
    return rules, post_mandatory


def extract_mapping(doc):
    t = find_table_by_header(doc, ["column name", "column type"])
    if t is None:
        raise RuntimeError(
            "Could not find the XML field-mapping table (expected a header with 'AndSoft Column Name' "
            "and 'Column Type'). If this is the JSON 'Rank' template, use extract_interface_from_docx.py."
        )
    header = [c.text.strip().lower() for c in t.rows[0].cells]
    idx = {
        "table": next((i for i, h in enumerate(header) if "table" in h), None),
        "column": next((i for i, h in enumerate(header) if "column name" in h), None),
        "type": next((i for i, h in enumerate(header) if "column type" in h), None),
        "source": next((i for i, h in enumerate(header) if "source" in h), None),
        "desc": next((i for i, h in enumerate(header) if "description" in h), None),
    }
    missing = [k for k, v in idx.items() if v is None]
    if missing:
        raise RuntimeError(f"Mapping table found but column(s) {missing} not identified; header read as {header}.")
    rows = []
    for r in t.rows[1:]:
        c = [x.text.strip() for x in r.cells]
        if len(c) <= max(idx.values()) or not c[idx["column"]]:
            continue
        rows.append({
            "table": c[idx["table"]], "column": c[idx["column"]], "col_type": c[idx["type"]],
            "fms_source": c[idx["source"]], "desc_raw": c[idx["desc"]],
        })
    return rows


def extract_mapping_caption(doc):
    for p in doc.paragraphs:
        m = re.search(r"\(Source\s+(.+?)\s+to\s+(.+?)\)", p.text)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return None, None


def extract_xsd(doc):
    raw = next((t.rows[0].cells[0].text for t in doc.tables
                if len(t.rows) == 1 and "<xs:schema" in t.rows[0].cells[0].text), None)
    if raw is None:
        return None
    try:
        schema = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", raw.strip()))
    except ET.ParseError:
        return None
    top = schema.find(f"{XS}element")
    if top is None:
        return None
    elements = []
    for el in top.iter(f"{XS}element"):
        if el is top:
            continue
        restriction = el.find(f".//{XS}restriction")
        xsd_type = el.get("type") or (restriction.get("base") if restriction is not None else "xs:string")
        elements.append({
            "name": el.get("name"), "xsd_type": xsd_type.split(":")[-1].lower(),
            "enum": [e.get("value") for e in el.iter(f"{XS}enumeration")],
        })
    return {"root": top.get("name"), "elements": elements}


def extract_status_codes(doc):
    t = find_table_by_header(doc, ["http status", "reason"])
    out = []
    if t is None:
        return out
    for r in t.rows[1:]:
        c = [x.text.strip() for x in r.cells]
        if len(c) >= 3 and re.match(r"^\d{3}$", c[0]):
            out.append({"code": c[0], "meaning": c[1], "description": c[2], "action": c[3] if len(c) > 3 else ""})
    return out


def extract_error_codes(doc):
    t = find_table_by_header(doc, ["error code", "error message"])
    out = []
    if t is None:
        return out
    for r in t.rows[1:]:
        c = [x.text.strip() for x in r.cells]
        if len(c) >= 4 and c[0]:
            out.append({"code": c[0], "message": c[1], "system_action": c[2], "http_status": c[3]})
    return out


def extract_response_examples(doc):
    out = []
    for t in doc.tables:
        if len(t.rows) != 1:
            continue
        txt = t.rows[0].cells[0].text.strip()
        if not txt.startswith("<RESPONSE"):
            continue
        try:
            root = ET.fromstring(txt)
        except ET.ParseError:
            continue
        out.append({"root": root.tag, "attrs": dict(root.attrib),
                    "children": [(c.tag, (c.text or "").strip()) for c in root]})
    return out


# ---------------------------------------------------------------- record building

def parse_column_type(raw):
    m = re.match(r"\s*([A-Za-z]+)\s*(?:\(\s*([\d.]+)\s*\))?", raw or "")
    if not m:
        return "string", None
    return TABLE_TYPE.get(m.group(1).lower(), "string"), m.group(2)


def split_description(desc):
    desc = desc.replace("\n", " ").strip()
    tag = req = None
    m = TARGET_RE.search(desc)
    if m:
        tag, req = m.group(1), m.group(2).strip()
        desc = desc[:m.start()] + desc[m.end():]
    return tag, req, re.sub(r"\s+", " ", desc).strip()


def classify_requirement(req):
    """Returns (status, qualifier); status None when the row carries no R/O marker."""
    if req is None:
        return None, ""
    m = re.match(r"(Mandatory R|Optional O)\s*(.*)$", req)
    if not m:
        return None, req
    kind, qualifier = m.group(1), m.group(2).strip()
    if kind == "Optional O":
        return "optional", qualifier
    return ("conditional" if qualifier.lower().startswith("on ") else "mandatory"), qualifier


def build_field_records(mapping, xsd, source_system, target_system):
    xsd_by_name = {e["name"]: e for e in (xsd["elements"] if xsd else [])}
    seen_ids, records, interface_fields, review, findings = set(), [], [], [], []
    covered_tags = set()

    for row in mapping:
        col = row["column"]
        tag, req, desc = split_description(row["desc_raw"])
        wire_tag = tag or (col if col in xsd_by_name else None)
        status, qualifier = classify_requirement(req)
        table_type, size = parse_column_type(row["col_type"])
        el = xsd_by_name.get(wire_tag) if wire_tag else None
        allowed = None
        data_type = table_type
        if el:
            covered_tags.add(wire_tag)
            xsd_type = XSD_TYPE.get(el["xsd_type"], "string")
            if xsd_type != table_type:
                findings.append({
                    "rule": "structure-type-vs-xsd-mismatch", "severity": "blocking", "path": wire_tag,
                    "message": f"The mapping table's Column Type says '{row['col_type']}' ({table_type}), but the "
                               f"embedded XSD declares <{wire_tag}> as xs:{el['xsd_type']} ({xsd_type}). The XSD is "
                               f"treated as ground truth for the generated OpenAPI schema; the disagreement itself "
                               f"should go back to Andsoft.",
                })
            data_type = "enum" if el["enum"] else xsd_type
            allowed = el["enum"] or None
        if tag and tag != col:
            findings.append({
                "rule": "structure-xml-tag-mismatch", "severity": "advisory", "path": f"{row['table']}.{col}",
                "message": f"AndSoft column '{col}' is sent as XML element <{tag}> - the wire name differs from the "
                           f"column name. Confirm which is intended.",
            })

        fid = dedupe_field_id(col, seen_ids)
        quality_rules = []
        if qualifier:
            quality_rules.append(f"Requirement as stated in the document: {req}.")
        if "DEPRECATED" in desc.upper():
            quality_rules.append("Marked DEPRECATED / REMOVED in the source document.")
            review.append((fid, f"{row['table']}.{col}",
                           "Row is marked DEPRECATED / REMOVED in the mapping table - confirm it should stay in the glossary."))
            findings.append({
                "rule": "consistency-deprecated-field", "severity": "advisory", "path": f"{row['table']}.{col}",
                "message": "A row marked DEPRECATED / REMOVED is still listed in the mapping table. Remove it from "
                           "the document or confirm it is kept for reference only.",
            })

        rec = {
            "field_id": fid, "name": wire_tag or col,
            "description": desc or col, "data_type": data_type,
            "status": status or "optional",
            "source_system": source_system if row["fms_source"].upper().startswith("FMS") else target_system,
            "sensitivity": "internal", "quality_rules": quality_rules,
        }
        if allowed:
            rec["allowed_values"] = allowed
        if size and data_type in ("string", "enum"):
            rec["format"] = f"max length {size}"
        records.append(rec)

        if wire_tag:
            entry = {"field_id": fid, "required": False, "io": "request", "path": wire_tag}
            if not row["fms_source"].upper().startswith("NONE"):
                entry["source_field"] = row["fms_source"]
            interface_fields.append(entry)
        else:
            remark = ("Not part of the XML payload (no 'Target XML' tag in the mapping row and no matching XSD "
                      "element) - confirm whether it is transmitted or stays glossary-only.")
            review.append((fid, f"{row['table']}.{col}", remark))
            findings.append({
                "rule": "completeness-mapping-without-xml-tag", "severity": "informational",
                "path": f"{row['table']}.{col}",
                "message": "Listed in the mapping table but has no XML tag and no XSD element, so it is not in the "
                           "generated request schema. Confirm whether it is transmitted.",
            })
        if status is None and wire_tag:
            review.append((fid, wire_tag, "No Mandatory R / Optional O marker in the description - defaulted to optional."))

    for el in (xsd["elements"] if xsd else []):
        if el["name"] in covered_tags:
            continue
        fid = dedupe_field_id(el["name"], seen_ids)
        data_type = "enum" if el["enum"] else XSD_TYPE.get(el["xsd_type"], "string")
        rec = {
            "field_id": fid, "name": el["name"],
            "description": "Declared in the embedded XSD only; the mapping table gives no row, description or source.",
            "data_type": data_type, "status": "optional", "source_system": source_system,
            "sensitivity": "internal", "quality_rules": [],
        }
        if el["enum"]:
            rec["allowed_values"] = el["enum"]
        records.append(rec)
        interface_fields.append({"field_id": fid, "required": False, "io": "request", "path": el["name"]})
        review.append((fid, el["name"], "Declared in the XSD but has no row in the mapping table - no description or "
                                        "source supplied; confirm with Andsoft."))
        findings.append({
            "rule": "completeness-xsd-only-element", "severity": "advisory", "path": el["name"],
            "message": f"<{el['name']}> exists in the embedded XSD but not in the mapping table, so it has no "
                       f"description or source mapping.",
        })
    return records, interface_fields, review, findings


def build_response(examples, iface_slug):
    if not examples:
        return [], [], None
    root = examples[0]["root"]
    attr_values, tag_order, tag_samples = defaultdict(list), [], {}
    for ex in examples:
        for k, v in ex["attrs"].items():
            if v not in attr_values[k]:
                attr_values[k].append(v)
        for tag, val in ex["children"]:
            if tag not in tag_samples:
                tag_order.append(tag)
                tag_samples[tag] = val
    present_in_all = {t for t in tag_order if all(t in {c[0] for c in ex["children"]} for ex in examples)}

    records, fields = [], []
    seen = set()
    for attr, values in attr_values.items():
        fid = dedupe_field_id(f"{iface_slug}-response-{attr}", seen)
        records.append({
            "field_id": fid, "name": f"Response {attr}",
            "description": f"Attribute '{attr}' of the <{root}> element; values seen in the document examples: "
                           f"{', '.join(values)}.",
            "data_type": "enum" if len(values) > 1 else "string", "status": "mandatory",
            "source_system": "AndSoft TMS", "sensitivity": "internal", "quality_rules": [],
            **({"allowed_values": values} if len(values) > 1 else {}),
        })
        fields.append({"field_id": fid, "required": True, "io": "response", "path": attr, "xml_attribute": True})
    for tag in tag_order:
        fid = dedupe_field_id(f"{iface_slug}-response-{tag}", seen)
        records.append({
            "field_id": fid, "name": f"Response {tag}",
            "description": f"<{tag}> element of the <{root}> XML response (example value: {tag_samples[tag]}).",
            "data_type": "string", "status": "mandatory" if tag in present_in_all else "conditional",
            "source_system": "AndSoft TMS", "sensitivity": "internal", "quality_rules": [],
        })
        fields.append({"field_id": fid, "required": tag in present_in_all, "io": "response", "path": tag})
    return records, fields, root


def derive_status_code_scope(codes, scenarios):
    scenario_codes = {s["method"]: s["code"] for s in scenarios if s["method"] and s["code"]}
    out = []
    for c in codes:
        d = c["description"].upper()
        if c["code"].startswith("2"):
            methods = [m for m, code in scenario_codes.items() if code == c["code"]]
        else:
            methods = set()
            if "INSERT" in d:
                methods.add("POST")
            if re.search(r"\bUPDATE\b|\bPUT\b", d):
                methods.add("PUT")
            if re.search(r"SOFT DELETE|\bPATCH\b", d):
                methods.add("PATCH")
            methods = sorted(methods)
        entry = {"code": c["code"], "meaning": c["meaning"],
                 "description": c["description"] + (f" Action: {c['action']}." if c["action"] else "")}
        if methods:
            entry["applies_to"] = methods
        out.append(entry)
    return out


# ---------------------------------------------------------------- document-level lint

def lint_document(endpoint, auth_text, post_mandatory, mapping_required_tags, error_codes, examples, status_codes):
    findings = []
    base = endpoint["base_url"] or ""
    if not base or "TBD" in base.upper() or re.search(r"\[[^\]]+\]", base):
        findings.append({
            "rule": "completeness-endpoint-url", "severity": "blocking", "path": "(endpoint)",
            "message": f"Endpoint base URL is still a placeholder: '{base or 'missing'}'. This needs a real value "
                       f"from Andsoft before cutover.",
        })
    ops = endpoint["operations"]
    if ops and base:
        coll = "/" + ops[0]["path"].strip("/").split("/")[0]
        path_part = re.sub(r"^https?://[^/]+", "", base)
        if path_part.rstrip("/").endswith(coll):
            findings.append({
                "rule": "structure-base-url-overlap", "severity": "advisory", "path": "(endpoint)",
                "message": f"The Base URL already ends with '{coll}' and the operations repeat it "
                           f"('{ops[0]['method']} {ops[0]['path']}'), so a literal join would give '{coll}{coll}'. "
                           f"Confirm the real base path.",
            })
    auth_blob = " ".join([auth_text] + [h["value"] for h in endpoint["headers"] if h["header"].lower() == "authorization"])
    if re.search(r"api.?key", auth_blob, re.I) and re.search(r"bearer|oauth", auth_blob, re.I):
        findings.append({
            "rule": "completeness-auth-method", "severity": "blocking", "path": "(endpoint headers)",
            "message": f"More than one authentication mechanism is offered with no decision ('{auth_blob.strip()}'). "
                       f"Confirm one definitive method with Andsoft before cutover.",
        })
    if post_mandatory and set(post_mandatory) != set(mapping_required_tags):
        findings.append({
            "rule": "consistency-mandatory-list", "severity": "advisory", "path": "(document structure)",
            "message": f"The POST mandatory list ({', '.join(post_mandatory)}) differs from the elements marked "
                       f"Mandatory R in the mapping table ({', '.join(sorted(mapping_required_tags))}).",
        })
    for e in error_codes:
        if not re.match(r"^ENT0\d{4}$", e["code"]):
            findings.append({
                "rule": "consistency-error-code-format", "severity": "advisory", "path": e["code"],
                "message": f"Error code '{e['code']}' does not follow the 'ENT0nnnn' pattern of the other codes in the table.",
            })
    documented = {e["code"] for e in error_codes}
    used = {v for ex in examples for k, v in ex["children"] if k == "ERROR_CODE"}
    for code in sorted(used - documented):
        findings.append({
            "rule": "consistency-error-code-undocumented", "severity": "advisory", "path": code,
            "message": f"'{code}' is returned in a response example but is not listed in the error-code table.",
        })
    return findings


# ---------------------------------------------------------------- writers

def write_yaml(path, header, payload):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True, width=100)


def write_review_report(path, args, counts, extras, review, iface):
    n_fields, n_rows = counts
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# Extraction review report - {args.name}\n\n")
        fh.write(f"Source document: `{Path(args.docx_path).name}`\n\n")
        fh.write(f"- Leaf fields extracted: **{n_fields}** unique glossary fields from **{n_rows}** payload occurrences\n")
        fh.write(f"- Template: XML master-data (flat mapping table + embedded XSD)\n")
        fh.write(f"- Endpoint info found: {'yes' if extras['endpoint']['base_url'] else 'no - check manually'}\n")
        fh.write(f"- Operations found: {len(extras['endpoint']['operations'])}\n")
        fh.write(f"- Required headers: {len(iface['required_headers'])} header(s) found\n")
        fh.write(f"- Field-level validation rules: {len(iface['field_validation_rules'])} rule(s) found\n")
        fh.write(f"- Business rules: {len(iface['business_rules'])} rule(s) found\n")
        fh.write(f"- Error codes: {len(iface['error_codes'])} found\n\n")
        fh.write("## Needs human review before promoting\n\n")
        for fid, p, remark in review:
            fh.write(f"- `{fid}` (path `{p}`): {remark}\n")
        if not review:
            fh.write("None flagged - still eyeball data_type/status/sensitivity defaults below.\n")
        fh.write(
            "\n## Defaults applied automatically (confirm or correct)\n\n"
            "- Every field defaulted to `sensitivity: internal`; the template doesn't carry this, so a reviewer must set it.\n"
            "- `status` comes from the Mandatory R / Optional O marker; 'Mandatory R on POST' became `conditional`, "
            "and rows with no marker defaulted to `optional`.\n"
            "- Interface fields are all `required: false`, matching the XSD (every element has `minOccurs=\"0\"`); "
            "cardinality per HTTP method is in `business_rules` and each field's `status`.\n"
            "- Field names are the vendor's XML tag / column names, not business terms - supply business names in review.\n"
            "- `data_type` is taken from the XSD where the element exists there, otherwise from the Column Type.\n"
            f"- Source system `{iface['source_system']}` / target `{iface['target_system']}` came from the mapping-table "
            "caption (override with --source-system / --target-system).\n"
            "- `owner` and `flow_owner` are `TBD`: the template names no accountable owner.\n"
            "- `idempotent` / `retry_policy` are omitted: the template does not state them.\n"
            f"- `message_format` derived from the Content-Type header (`{iface['message_format']}`).\n\n"
            "## New LLD fields - manual completion required\n\n"
            "These are not present anywhere in AndSoft's document and are left empty on purpose - get the real "
            "value from the owning team during review/promote rather than guessing one:\n\n"
            "- `volume_profile` - expected volume, peak window, latency SLA.\n"
            "- `deduplication_strategy` - the document does not state one; POST returns 409 when the record exists.\n"
            "- `monitoring` - key metrics, alert thresholds, dashboard/tool.\n"
            "- `acceptance_criteria` - UAT sign-off criteria for this interface.\n"
            "- `test_data_ref` - cross-reference to the Testing Hub's test-suite id, once assigned.\n"
        )


def write_quality_report(path, docx_name, findings):
    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))
    by_sev = defaultdict(list)
    for f in findings:
        by_sev[f["severity"]].append(f)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# Document quality report - {docx_name}\n\n")
        fh.write("Checks the vendor document's own internal consistency and completeness - distinct from "
                 "REVIEW_REPORT.md. These are the XML-template checks; they complement, not replace, the JSON "
                 "template checks in lint_source_document.py.\n\n")
        fh.write(f"**{len(by_sev['blocking'])} blocking · {len(by_sev['advisory'])} advisory · "
                 f"{len(by_sev['informational'])} informational**\n\n")
        for sev, title in [
            ("blocking", "## Blocking - resolve before this interface is built against"),
            ("advisory", "## Advisory - likely fine, worth a second look"),
            ("informational", "## Informational - judgement calls to confirm, not necessarily problems"),
        ]:
            items = by_sev[sev]
            fh.write(f"{title} ({len(items)})\n\n")
            if not items:
                fh.write("None.\n\n")
                continue
            for it in items:
                fh.write(f"- **[{it['rule']}]** `{it['path']}` — {it['message']}\n")
            fh.write("\n")
    return {k: len(v) for k, v in by_sev.items()}


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx_path")
    ap.add_argument("--id", required=True, help="Interface ID, e.g. CV10_01")
    ap.add_argument("--name", required=True, help="Interface name, e.g. CV10_01_MD_TRUCKS_TRAILERS")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--source-system")
    ap.add_argument("--target-system")
    ap.add_argument("--promote", action="store_true", help="Also write final fields.yaml / interfaces.yaml")
    args = ap.parse_args()

    doc = Document(args.docx_path)
    cap_source, cap_target = extract_mapping_caption(doc)
    source_system = args.source_system or cap_source or "TBD"
    target_system = args.target_system or cap_target or "TBD"

    endpoint = extract_endpoint(doc)
    scenarios = extract_scenarios(doc)
    cardinality_rules, post_mandatory = extract_cardinality_rules(doc)
    mapping = extract_mapping(doc)
    xsd = extract_xsd(doc)
    if xsd is None:
        print("NOTE: no parseable embedded XSD found - types/enums come from the mapping table only.", file=sys.stderr)
    status_codes = extract_status_codes(doc)
    error_codes = extract_error_codes(doc)
    examples = extract_response_examples(doc)
    auth_text = paragraph_after(doc, "AUTHENTICATION")

    records, request_fields, review, findings = build_field_records(mapping, xsd, source_system, target_system)
    n_request_records = len(records)
    resp_records, resp_fields, resp_root = build_response(examples, slugify(args.id))
    for r in resp_records:
        review.append((r["field_id"], r["name"],
                       "No formal description in the document - inferred from the XML response example only."))
    records += resp_records

    mapping_required = {f["name"] for f in records if f["status"] in ("mandatory", "conditional")
                        and not f["field_id"].startswith(slugify(args.id) + "-response-")}
    findings += lint_document(endpoint, auth_text, post_mandatory, mapping_required, error_codes, examples, status_codes)

    headers = []
    for h in endpoint["headers"]:
        notes = auth_text if h["header"].lower() == "authorization" else ""
        headers.append({"header": h["header"], "value": h["value"], "notes": notes, "required": True})

    content_type = next((h["value"] for h in endpoint["headers"] if h["header"].lower() == "content-type"), "")
    message_format = {"application/xml": "XML", "text/xml": "XML", "application/json": "JSON"}.get(
        content_type.split(";")[0].strip().lower(), content_type or "TBD")

    business_rules = [{"id": f"BR-{i:02d}", "rule": t, "notes": ""}
                      for i, t in enumerate([s["text"] for s in scenarios] + cardinality_rules, start=1)]

    validation_rules = []
    schema_error_code = next((v for ex in examples if ex["attrs"].get("status") == "ERROR"
                              for k, v in ex["children"] if k == "ERROR_CODE"), "")
    if post_mandatory:
        validation_rules.append({
            "field": ", ".join(post_mandatory), "rule": "Mandatory on POST (full creation)",
            "error_code": schema_error_code, "message": "Missing required elements fail XSD schema validation (HTTP 400).",
        })
    for rec in records:
        if rec.get("allowed_values") and not rec["field_id"].startswith(slugify(args.id) + "-response-"):
            code = re.search(r"\((ERR_[A-Z_]+)\)", rec["description"])
            validation_rules.append({
                "field": rec["name"], "rule": f"Must be one of: {', '.join(rec['allowed_values'])}",
                "error_code": code.group(1) if code else "", "message": "Value outside the XSD enumeration.",
            })
    iso = [r["name"] for r in records if "ISO-8601" in r["description"].upper()]
    if iso:
        validation_rules.append({"field": ", ".join(iso), "rule": "Standard ISO-8601 date/time format",
                                 "error_code": "", "message": ""})

    ops = endpoint["operations"]
    scenario_names = "; ".join(s["name"] for s in scenarios)
    iface = {
        "id": args.id, "name": args.name,
        "description": extract_description(doc),
        "source_system": source_system, "target_system": target_system,
        "protocol": endpoint["style"] or "REST",
        "method": ops[0]["method"] if ops else "POST",
        "endpoint_url": endpoint["base_url"] or "TBD",
        "frequency": f"Synchronous, on record change in {source_system}: {scenario_names}" if scenarios else "TBD",
        "owner": "TBD", "spec_type": "vendor-template", "spec_version": extract_version(doc), "status": "documented",
        "response_contract": (f"XML <{resp_root}> body with attribute(s) {', '.join(a for e in examples[:1] for a in e['attrs'])} "
                              f"and elements {', '.join(t for t, _ in examples[0]['children'])} (see response examples)")
                             if examples else "TBD",
        "response_status_codes": derive_status_code_scope(status_codes, scenarios),
        "required_headers": headers,
        "operations": ops,
        "request_root_element": xsd["root"] if xsd else None,
        "response_root_element": resp_root,
        "field_validation_rules": validation_rules,
        "business_rules": business_rules,
        "error_codes": error_codes,
        "fields": request_fields + resp_fields,
        "flow_owner": "TBD", "message_format": message_format,
        "volume_profile": None, "deduplication_strategy": None, "monitoring": None,
        "acceptance_criteria": [], "test_data_ref": None,
    }
    iface = {k: v for k, v in iface.items() if v is not None or k in (
        "volume_profile", "deduplication_strategy", "monitoring", "test_data_ref")}

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    draft_note = f"# AUTO-GENERATED DRAFT from {Path(args.docx_path).name} - review before promoting.\n"
    write_yaml(out_dir / "fields.draft.yaml", draft_note + f"# Domain: {args.name}\n\n", {"fields": records})
    write_yaml(out_dir / "interfaces.draft.yaml", draft_note + "\n", {"interfaces": [iface]})
    write_review_report(out_dir / "REVIEW_REPORT.md", args, (len(records), len(request_fields) + len(resp_fields)),
                        {"endpoint": endpoint}, review, iface)
    counts = write_quality_report(out_dir / "DOC_QUALITY_REPORT.md", Path(args.docx_path).name, findings)

    if args.promote:
        promoted = f"# Domain: {args.name}\n# Promoted automatically (--promote) without manual review.\n\n"
        write_yaml(out_dir / "fields.yaml", promoted, {"fields": records})
        write_yaml(out_dir / "interfaces.yaml", promoted, {"interfaces": [iface]})

    print(f"Wrote drafts + reports to {out_dir}{' and promoted to final YAML' if args.promote else ''}")
    print(f"{len(records)} unique fields ({n_request_records} from the mapping/XSD, {len(resp_records)} from response examples); "
          f"{len(review)} flagged for review.")
    print(f"{counts.get('blocking', 0)} blocking, {counts.get('advisory', 0)} advisory, "
          f"{counts.get('informational', 0)} informational finding(s).")


if __name__ == "__main__":
    main()
