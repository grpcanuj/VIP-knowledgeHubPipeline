#!/usr/bin/env python3
"""
generate_run_report.py
-----------------------
Closes the gap flagged against the onboarding methodology: previously every
stage wrote its own, separate report (REVIEW_REPORT.md from Stage 1,
DOC_QUALITY_REPORT.md from Stage 1.5) and nothing recorded Stage 3's
validation result, Stage 4/4b's compile and OpenAPI-generation outcome, or
Stage 5's publish status. This script reads whatever each stage already
produced on disk and writes ONE consolidated RUN_REPORT.md per interface,
covering every stage of a single pipeline run end to end.

It does not re-run the extraction or lint stages (those already wrote their
own reports); it DOES re-run Stage 3 (validate_all.py) live, since that
result is cheap to reproduce and must always reflect the current state of
every domain, not a stale snapshot.

Usage:
    python3 scripts/generate_run_report.py \
        --domain-dir domains/cv07_shippeo --interface-id CV07_01 \
        --domains-dir domains --schemas-dir schemas \
        --openapi-dir output/openapi --compiled-js output/exampleData.generated.js

Writes <domain-dir>/RUN_REPORT_<interface-id>.md
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

try:
    from openapi_spec_validator import validate as validate_openapi
    from openapi_spec_validator.exceptions import OpenAPIError as OpenAPIValidationError
    HAVE_VALIDATOR = True
except ImportError:
    HAVE_VALIDATOR = False


def load_yaml(path):
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def section(title, status_icon, body):
    return f"## {status_icon} {title}\n\n{body.strip()}\n"


def stage1_extract_summary(domain_dir, interface_id):
    review_path = Path(domain_dir) / "REVIEW_REPORT.md"
    if not review_path.exists():
        return "SKIPPED", (
            "No `REVIEW_REPORT.md` found in this domain folder. Either this interface "
            "was not onboarded through the extraction script (a pre-existing example), "
            "or extraction has not been run yet."
        )
    text = review_path.read_text(encoding="utf-8")
    m = re.search(r"Leaf fields extracted:\s*\*\*(\d+)\*\*.*?from\s*\*\*(\d+)\*\*", text)
    unique_fields, occurrences = (m.group(1), m.group(2)) if m else ("?", "?")
    needs_review = len(re.findall(r"^- `", text, flags=re.MULTILINE))
    # the "Needs human review" bullets and "Defaults applied" bullets share the
    # same `- `` prefix; count only the ones inside the review section.
    review_section_match = re.search(
        r"## Needs human review before promoting\n(.*?)(\n##|\Z)", text, re.DOTALL
    )
    review_items = len(re.findall(r"^- `", review_section_match.group(1), re.MULTILINE)) if review_section_match else 0
    body = (
        f"Extracted **{unique_fields}** unique glossary fields from **{occurrences}** payload occurrences.\n\n"
        f"**{review_items}** field(s) flagged for human review (no AndSoft source-column mapping) "
        f"— see `REVIEW_REPORT.md` for the full list."
    )
    return "OK", body


def stage1_5_lint_summary(domain_dir):
    quality_path = Path(domain_dir) / "DOC_QUALITY_REPORT.md"
    if not quality_path.exists():
        return "SKIPPED", "No `DOC_QUALITY_REPORT.md` found — lint has not been run for this domain."
    text = quality_path.read_text(encoding="utf-8")
    m = re.search(r"\*\*(\d+) blocking.*?(\d+) advisory.*?(\d+) informational\*\*", text)
    if not m:
        return "UNKNOWN", "`DOC_QUALITY_REPORT.md` exists but its summary line could not be parsed."
    blocking, advisory, informational = m.groups()
    status = "FAIL" if int(blocking) > 0 else "OK"
    body = (
        f"**{blocking} blocking · {advisory} advisory · {informational} informational** finding(s) "
        f"against the Andsoft document's own internal consistency — see `DOC_QUALITY_REPORT.md`.\n\n"
        + ("Blocking findings must be resolved with Andsoft before this interface is built against."
           if int(blocking) > 0 else "No blocking findings — document quality is clear to proceed.")
    )
    return status, body


def stage2_review_summary(domain_dir, interface_id):
    draft_fields = load_yaml(Path(domain_dir) / "fields.draft.yaml").get("fields")
    final_fields = load_yaml(Path(domain_dir) / "fields.yaml").get("fields")
    draft_ifaces = load_yaml(Path(domain_dir) / "interfaces.draft.yaml").get("interfaces")
    final_ifaces = load_yaml(Path(domain_dir) / "interfaces.yaml").get("interfaces")

    has_draft = draft_fields is not None or draft_ifaces is not None
    has_final = final_fields is not None or final_ifaces is not None

    if has_final:
        n_fields = len(final_fields or [])
        n_ifaces = len(final_ifaces or [])
        return "OK", (
            f"Promoted to final: **{n_fields}** field(s) and **{n_ifaces}** interface(s) in "
            f"`fields.yaml` / `interfaces.yaml`."
        )
    if has_draft:
        return "PENDING", (
            "Draft files exist (`fields.draft.yaml` / `interfaces.draft.yaml`) but have not yet been "
            "promoted to final. Apply the review rule list for this interface, then promote before "
            "Stage 3 validation."
        )
    return "SKIPPED", "No draft or final field/interface files found for this domain."


def stage3_validate(domains_dir, schemas_dir):
    cmd = [sys.executable, "scripts/validate_all.py", "--domains-dir", domains_dir, "--schemas-dir", schemas_dir]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        return "FAIL", f"Could not run `validate_all.py`: {e}"
    output = (result.stdout or "").strip() + ("\n" + result.stderr.strip() if result.stderr else "")
    status = "OK" if result.returncode == 0 else "FAIL"
    body = f"Ran `validate_all.py` across all domains just now:\n\n```\n{output}\n```"
    return status, body


def stage4_compile(compiled_js, interface_id):
    p = Path(compiled_js)
    if not p.exists():
        return "SKIPPED", f"Compiled data file `{compiled_js}` not found — Stage 4 has not been run."
    text = p.read_text(encoding="utf-8")
    found = interface_id in text
    status = "OK" if found else "FAIL"
    body = (
        f"`{compiled_js}` exists and {'contains' if found else 'does NOT contain'} a reference to "
        f"`{interface_id}`."
    )
    if not found:
        body += " Re-run Stage 4 after confirming this interface is promoted to final YAML."
    return status, body


def stage4b_openapi(openapi_dir, interface_id):
    yaml_path = Path(openapi_dir) / f"{interface_id}.openapi.yaml"
    json_path = Path(openapi_dir) / f"{interface_id}.openapi.json"
    if not yaml_path.exists() or not json_path.exists():
        return "SKIPPED", f"No OpenAPI spec found for `{interface_id}` under `{openapi_dir}` — Stage 4b has not been run."
    spec = json.loads(json_path.read_text(encoding="utf-8"))
    if HAVE_VALIDATOR:
        try:
            validate_openapi(spec)
            return "OK", f"`{interface_id}.openapi.yaml`/`.json` present and **re-validated OK** against OpenAPI 3.0.3 just now."
        except OpenAPIValidationError as e:
            return "FAIL", f"`{interface_id}.openapi.yaml`/`.json` present but **fails validation**:\n\n```\n{e}\n```"
    return "UNKNOWN", f"`{interface_id}.openapi.yaml`/`.json` present, but `openapi_spec_validator` is not installed so re-validation was skipped."


def stage5_publish(compiled_js):
    p = Path(compiled_js)
    if not p.exists():
        return "SKIPPED", "No compiled data file to publish."
    return "MANUAL", (
        "Publishing (rebuilding the Knowledge Hub application with this compiled data file) happens "
        "outside this pipeline's scripts. Confirm separately by running the application's build and "
        "checking the production bundle contains this interface's data."
    )


ICONS = {"OK": "✅", "FAIL": "❌", "PENDING": "🟡", "SKIPPED": "⚪", "UNKNOWN": "❓", "MANUAL": "🔧"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain-dir", required=True, help="e.g. domains/cv07_shippeo")
    ap.add_argument("--interface-id", required=True, help="e.g. CV07_01")
    ap.add_argument("--domains-dir", default="domains")
    ap.add_argument("--schemas-dir", default="schemas")
    ap.add_argument("--openapi-dir", default="output/openapi")
    ap.add_argument("--compiled-js", default="output/exampleData.generated.js")
    args = ap.parse_args()

    stages = []
    s1 = stage1_extract_summary(args.domain_dir, args.interface_id)
    stages.append(("Stage 1 — Extract", *s1))
    s15 = stage1_5_lint_summary(args.domain_dir)
    stages.append(("Stage 1.5 — Lint", *s15))
    s2 = stage2_review_summary(args.domain_dir, args.interface_id)
    stages.append(("Stage 2 — Review", *s2))
    s3 = stage3_validate(args.domains_dir, args.schemas_dir)
    stages.append(("Stage 3 — Validate", *s3))
    s4 = stage4_compile(args.compiled_js, args.interface_id)
    stages.append(("Stage 4 — Compile", *s4))
    s4b = stage4b_openapi(args.openapi_dir, args.interface_id)
    stages.append(("Stage 4b — Generate OpenAPI", *s4b))
    s5 = stage5_publish(args.compiled_js)
    stages.append(("Stage 5 — Publish", *s5))

    overall = "FAIL" if any(st == "FAIL" for _, st, _ in stages) else (
        "PENDING" if any(st == "PENDING" for _, st, _ in stages) else "OK"
    )

    lines = [
        f"# Run Report — {args.interface_id}",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Domain: `{args.domain_dir}`",
        "",
        f"**Overall: {ICONS[overall]} {overall}**",
        "",
        "One consolidated record of this interface's pipeline run, stage by stage — replaces "
        "having to cross-reference `REVIEW_REPORT.md`, `DOC_QUALITY_REPORT.md`, and the console "
        "output of each script separately.",
        "",
    ]
    for title, status, body in stages:
        lines.append(section(f"{title} — {status}", ICONS.get(status, ""), body))

    out_path = Path(args.domain_dir) / f"RUN_REPORT_{args.interface_id}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path} (overall: {overall})")


if __name__ == "__main__":
    main()
