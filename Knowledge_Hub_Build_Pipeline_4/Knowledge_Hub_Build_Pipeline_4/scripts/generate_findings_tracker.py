#!/usr/bin/env python3
"""
generate_findings_tracker.py
------------------------------
Consolidates REVIEW_REPORT.md (Stage 1 - fields needing human review before
promotion) and DOC_QUALITY_REPORT.md (Stage 1.5 - Andsoft document quality
findings) for one interface into a single Excel findings tracker.

Several lint/review rules repeat the exact same boilerplate explanation once
per affected field, only the field name / path (and occasionally a couple of
other interpolated values) differing each time - e.g. 12 separate rows all
reading "'<name>' has neither a Field-AndSoft source column value nor a
'Fixed value:' note - genuinely unmapped...". Reading the same sentence 12
times is noise, not signal. This script normalizes each rule's message back
to its shared template, GROUPS every occurrence that shares one, and writes
ONE row per distinct remark - with the specific field(s)/path(s) it applies
to listed together in their own columns - rather than one row per
occurrence. Nothing is dropped: the per-occurrence specifics that aren't
just "which field" (e.g. which direction a type mismatch goes, how many
times a path repeats) are folded into the Path column entry for that item
instead of being repeated in the Remarks column.

Usage:
    python3 scripts/generate_findings_tracker.py \
        --domain-dir domains/cv07_shippeo --interface-id CV07_01 \
        --domain-name cv07_shippeo --out output/CV07_01_Findings_Tracker.xlsx
"""
import argparse
import re
from datetime import date
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

FONT_NAME = "Arial"
HEADER_FILL = PatternFill(start_color="1F3864", end_color="1F3864", fill_type="solid")
HEADER_FONT = Font(name=FONT_NAME, size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name=FONT_NAME, size=10)
SEVERITY_FILLS = {
    "Review": PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"),
    "Blocking": PatternFill(start_color="FCE4E4", end_color="FCE4E4", fill_type="solid"),
    "Advisory": PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"),
    "Informational": PatternFill(start_color="E8F0FE", end_color="E8F0FE", fill_type="solid"),
}

COLUMNS = [
    ("Domain", 16),
    ("Interface ID", 12),
    ("S.No", 6),
    ("Source Report", 20),
    ("Severity", 13),
    ("Rule / Category", 26),
    ("# Items", 8),
    ("Field ID(s)", 28),
    ("Path(s)", 56),
    ("Remarks", 70),
    ("Status", 10),
    ("Creation Date", 14),
    ("Closed Date", 14),
]


# ---------------------------------------------------------------------------
# Per-rule normalization: strips the interpolated, per-occurrence part(s) out
# of a rendered message, returning (shared_template, per_item_detail). Rules
# not listed here fall back to treating the raw remark text as the template -
# which still correctly merges occurrences whose text is already byte-
# identical (e.g. REVIEW_REPORT.md's "needs human review" items all read the
# exact same sentence after the field_id/path, no regex needed for those).
# ---------------------------------------------------------------------------

def _norm_source_mapping(remark, path):
    m = re.match(r"^'[^']+' (has neither .+)$", remark)
    return (m.group(1) if m else remark), path


def _norm_camelcase(remark, path):
    m = re.match(r"^'[^']+' (doesn't follow .+)$", remark)
    return (m.group(1) if m else remark), path


def _norm_missing_description(remark, path):
    m = re.match(r"^No usable description for '[^']+' \(got: [^)]*\)\. (.+)$", remark)
    template = f"No usable description for this field. {m.group(1)}" if m else remark
    return template, path


def _norm_type_mismatch(remark, path):
    m = re.match(
        r"^The field-mapping table's Type column says '([a-z]+)', but the document's own "
        r"worked JSON example shows '([^']+)' as an '([a-z]+)'\. (.+)$",
        remark,
    )
    if not m:
        return remark, path
    table_kind, mpath, example_kind, tail = m.groups()
    template = (
        "The field-mapping table's Type column disagrees with the document's own worked JSON "
        f"example for the path(s) listed. {tail}"
    )
    detail = f"{mpath} (table says '{table_kind}', example shows '{example_kind}')"
    return template, detail


def _norm_duplicate_path(remark, path):
    m = re.match(
        r"^The exact same path '[^']+' appears (\d+) times (with identical description and "
        r"value.+?instead of) \d+ times\.$",
        remark,
    )
    if not m:
        return remark, path
    n, mid = m.groups()
    template = f"The exact same path appears multiple times {mid} repeating it that many times."
    detail = f"{path} (repeated {n}x)"
    return template, detail


def _norm_repeated_array_instance(remark, path):
    m = re.match(
        r"^'[^']+' is documented via (\d+) example rows with different values \(([^)]*)\) "
        r"rather than one row describing the array shape once\. (.+)$",
        remark,
    )
    if not m:
        return remark, path
    n, values, tail = m.groups()
    template = (
        "Documented via multiple example rows with different values rather than one row "
        f"describing the array shape once. {tail}"
    )
    detail = f"{path} ({n} example(s): {values or 'varies'})"
    return template, detail


NORMALIZERS = {
    "completeness-source-mapping": _norm_source_mapping,
    "naming-camelcase": _norm_camelcase,
    "completeness-description": _norm_missing_description,
    "structure-type-vs-example-mismatch": _norm_type_mismatch,
    "structure-duplicate-path": _norm_duplicate_path,
    "structure-repeated-array-instance": _norm_repeated_array_instance,
}


def normalize(rule, remark, path):
    fn = NORMALIZERS.get(rule)
    if fn:
        return fn(remark, path)
    return remark, path  # fallback: exact-text grouping only


def load_path_to_field_id(domain_dir):
    """Best-effort path -> field_id lookup from interfaces.yaml, so
    DOC_QUALITY_REPORT.md rows (which only carry a path, not a field_id)
    can still show a Field ID when one resolves. Two lookups are built: an
    exact match, and a bracket-insensitive one (stripping '[]' markers) as
    a fallback - lint checks run against the document's ORIGINAL, pre-
    correction paths (correct_paths_against_example runs AFTER extraction,
    not before linting), which sometimes only differ from the corrected
    path stored in interfaces.yaml by an array marker. Not every path will
    resolve even with the fallback; the Path column stays the reliable
    identifier either way."""
    exact, stripped = {}, {}
    p = Path(domain_dir) / "interfaces.yaml"
    if not p.exists():
        return exact, stripped
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for iface in data.get("interfaces", []):
        for f in iface.get("fields", []):
            if f.get("path"):
                exact[f["path"]] = f["field_id"]
                stripped.setdefault(f["path"].replace("[]", ""), f["field_id"])
    return exact, stripped


def resolve_field_id(path, exact, stripped):
    return exact.get(path) or stripped.get(path.replace("[]", "")) or ""


def parse_review_report(path):
    """Returns a list of dicts from REVIEW_REPORT.md: the per-field 'needs
    human review' items, plus the general 'defaults applied' notes."""
    rows = []
    if not Path(path).exists():
        return rows
    text = Path(path).read_text(encoding="utf-8")

    m = re.search(r"## Needs human review before promoting\n(.*?)(\n##|\Z)", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            fm = re.match(r"^- `([^`]+)` \(path `([^`]+)`\): (.+)$", line.strip())
            if fm:
                field_id, path_, remark = fm.groups()
                rows.append({
                    "source": "REVIEW_REPORT.md",
                    "severity": "Review",
                    "rule": "missing-source-mapping",
                    "field_id": field_id,
                    "path": path_,
                    "remark": remark,
                })

    m = re.search(r"## Defaults applied automatically \(confirm or correct\)\n(.*?)(\n##|\Z)", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            gm = re.match(r"^- (.+)$", line.strip())
            if gm:
                rows.append({
                    "source": "REVIEW_REPORT.md",
                    "severity": "Review",
                    "rule": "default-applied",
                    "field_id": "(general)",
                    "path": "",
                    "remark": gm.group(1),
                })
    return rows


def parse_doc_quality_report(path, exact_lookup, stripped_lookup):
    """Returns a list of dicts from DOC_QUALITY_REPORT.md across its three
    severity sections (Blocking / Advisory / Informational)."""
    rows = []
    if not Path(path).exists():
        return rows
    text = Path(path).read_text(encoding="utf-8")

    for severity in ("Blocking", "Advisory", "Informational"):
        m = re.search(rf"## {severity}[^\n]*\n(.*?)(\n## |\Z)", text, re.DOTALL)
        if not m:
            continue
        for line in m.group(1).splitlines():
            fm = re.match(r"^- \*\*\[([a-z0-9-]+)\]\*\* `([^`]+)` — (.+)$", line.strip())
            if fm:
                rule, path_, remark = fm.groups()
                rows.append({
                    "source": "DOC_QUALITY_REPORT.md",
                    "severity": severity,
                    "rule": rule,
                    "field_id": resolve_field_id(path_, exact_lookup, stripped_lookup),
                    "path": path_,
                    "remark": remark,
                })
    return rows


def consolidate(rows):
    """Groups rows sharing (source, severity, rule, normalized template)
    into one row each, rather than repeating the same remark once per
    occurrence. Field ID and Path are tracked as ALIGNED pairs - line N of
    the Field ID column corresponds to line N of the Path column for a
    given row - rather than two independently-deduplicated lists, so a
    reader never sees a Field ID column with fewer lines than the Path
    column and wonders whether something is missing or mismatched."""
    groups = {}
    order = []
    for row in rows:
        template, detail = normalize(row["rule"], row["remark"], row["path"])
        key = (row["source"], row["severity"], row["rule"], template)
        if key not in groups:
            groups[key] = {
                "source": row["source"], "severity": row["severity"], "rule": row["rule"],
                "remark": template, "items": [], "seen_details": set(), "count": 0,
            }
            order.append(key)
        g = groups[key]
        g["count"] += 1
        fid = row.get("field_id") or ""
        detail = detail or fid or "(general)"
        if detail not in g["seen_details"]:
            g["seen_details"].add(detail)
            g["items"].append((fid, detail))
    return [groups[k] for k in order]


def build_workbook(rows, domain_name, interface_id, created_date, out_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Findings Tracker"

    for col_idx, (header, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[1].height = 20
    ws.freeze_panes = "A2"

    for i, row in enumerate(rows, start=1):
        r = i + 1
        field_id_col = "\n".join(fid for fid, _ in row["items"])
        path_col = "\n".join(detail for _, detail in row["items"])
        values = [
            domain_name,
            interface_id,
            i,
            row["source"],
            row["severity"],
            row["rule"],
            row["count"],
            field_id_col,
            path_col,
            row["remark"],
            "Open",
            created_date,
            None,
        ]
        fill = SEVERITY_FILLS.get(row["severity"])
        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=col_idx, value=value)
            cell.font = BODY_FONT
            cell.alignment = Alignment(vertical="top", wrap_text=(col_idx in (8, 9, 10)))
            if fill and col_idx == 5:
                cell.fill = fill
        ws.cell(row=r, column=12).number_format = "yyyy-mm-dd"
        ws.cell(row=r, column=13).number_format = "yyyy-mm-dd"

    last_row = len(rows) + 1
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{last_row}"

    dv = DataValidation(type="list", formula1='"Open,In Progress,Closed"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(f"K2:K{max(last_row, 2)}")

    # --- Summary sheet ---
    ws2 = wb.create_sheet("Summary")
    ws2.column_dimensions["A"].width = 24
    ws2.column_dimensions["B"].width = 16
    ws2.column_dimensions["C"].width = 16
    headers = ["Source Report / Severity", "Distinct Remarks (Open)", "Affected Items (Open)"]
    for col_idx, header in enumerate(headers, start=1):
        cell = ws2.cell(row=1, column=col_idx, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL

    summary_rows = [
        ("REVIEW_REPORT.md - Review", "REVIEW_REPORT.md", "Review"),
        ("DOC_QUALITY_REPORT.md - Blocking", "DOC_QUALITY_REPORT.md", "Blocking"),
        ("DOC_QUALITY_REPORT.md - Advisory", "DOC_QUALITY_REPORT.md", "Advisory"),
        ("DOC_QUALITY_REPORT.md - Informational", "DOC_QUALITY_REPORT.md", "Informational"),
    ]
    for i, (label, source, severity) in enumerate(summary_rows, start=2):
        ws2.cell(row=i, column=1, value=label).font = BODY_FONT
        count_formula = (
            f'=COUNTIFS(\'Findings Tracker\'!D2:D{last_row},"{source}",'
            f'\'Findings Tracker\'!E2:E{last_row},"{severity}",'
            f'\'Findings Tracker\'!K2:K{last_row},"Open")'
        )
        items_formula = (
            f'=SUMIFS(\'Findings Tracker\'!G2:G{last_row},'
            f'\'Findings Tracker\'!D2:D{last_row},"{source}",'
            f'\'Findings Tracker\'!E2:E{last_row},"{severity}",'
            f'\'Findings Tracker\'!K2:K{last_row},"Open")'
        )
        for col, formula in ((2, count_formula), (3, items_formula)):
            c = ws2.cell(row=i, column=col, value=formula)
            c.font = BODY_FONT
            c.alignment = Alignment(horizontal="center")

    total_row = len(summary_rows) + 2
    ws2.cell(row=total_row, column=1, value="Total open").font = Font(name=FONT_NAME, size=10, bold=True)
    for col in (2, 3):
        ws2.cell(row=total_row, column=col,
                 value=f"=SUM({get_column_letter(col)}2:{get_column_letter(col)}{total_row - 1})").font = \
            Font(name=FONT_NAME, size=10, bold=True)

    wb.save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain-dir", required=True, help="e.g. domains/cv07_shippeo")
    ap.add_argument("--domain-name", required=True, help="e.g. cv07_shippeo")
    ap.add_argument("--interface-id", required=True, help="e.g. CV07_01")
    ap.add_argument("--created-date", default=date.today().isoformat())
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    exact_lookup, stripped_lookup = load_path_to_field_id(args.domain_dir)

    raw_rows = []
    raw_rows.extend(parse_review_report(Path(args.domain_dir) / "REVIEW_REPORT.md"))
    raw_rows.extend(parse_doc_quality_report(
        Path(args.domain_dir) / "DOC_QUALITY_REPORT.md", exact_lookup, stripped_lookup))

    if not raw_rows:
        print("No findings parsed - check that REVIEW_REPORT.md / DOC_QUALITY_REPORT.md exist and match expected format.")

    rows = consolidate(raw_rows)

    created = date.fromisoformat(args.created_date)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    build_workbook(rows, args.domain_name, args.interface_id, created, args.out)
    total_items = sum(r["count"] for r in rows)
    print(f"Wrote {args.out} ({len(rows)} distinct remark(s) covering {total_items} raw finding(s))")


if __name__ == "__main__":
    main()
