#!/usr/bin/env python3
"""
run_pipeline.py
---------------
Runs the whole pipeline in order from the pipeline folder (cross-platform):

  1. Stage 1 / 1.5  extract + lint, for manifest interfaces whose .docx is in --docs-dir
  2. Stage 3        validate_all.py
  3. Stage 4        compile_knowledge_hub.py   -> output/exampleData.generated.js (+ copy into the UI)
  4. Stage 4b       generate_openapi.py        -> output/openapi                  (+ copy into the UI)
  5. Stage 5        run report + HTML + findings tracker per interface, collected in --reports-dir

Stage 3/4/4b failures stop the run. Extract, lint and report problems are reported and the run continues,
because a failing quality verdict on a vendor document is a finding, not a broken build.

Usage (from the pipeline folder):
    python scripts/run_pipeline.py --ui-dir "<ui folder>" [--docs-dir <folder with .docx>] [--reports-dir output/reports]
"""
import argparse
import html
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

PY = sys.executable


def run(args, fatal=True, label=""):
    print(f"\n$ {' '.join(str(a) for a in args)}", flush=True)
    rc = subprocess.call([PY, *map(str, args)])
    if rc != 0:
        msg = f"{label or args[0]} exited with {rc}"
        if fatal:
            sys.exit(f"ERROR: {msg}")
        print(f"WARNING: {msg} (continuing)", flush=True)
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ui-dir", required=True)
    ap.add_argument("--docs-dir", default="")
    ap.add_argument("--reports-dir", default="output/reports")
    ap.add_argument("--manifest", default="interfaces.manifest.yaml")
    args = ap.parse_args()

    ui = Path(args.ui_dir)
    reports = Path(args.reports_dir)
    out = Path("output")
    docs = Path(args.docs_dir) if args.docs_dir else None
    entries = (yaml.safe_load(open(args.manifest, encoding="utf-8")) or {}).get("interfaces") or []

    shutil.rmtree(reports, ignore_errors=True)
    reports.mkdir(parents=True)
    out.mkdir(exist_ok=True)

    if docs:
        print(f"\n== Stage 1 / 1.5: extract + lint from {docs}")
        for e in entries:
            docx = docs / e["sharepoint_path"].rsplit("/", 1)[-1]
            if not docx.is_file():
                print(f"  {e['id']}: {docx.name} not found in docs dir, skipped")
                continue
            domain_dir = Path("domains") / e["domain"]
            script = "extract_interface_from_docx.py" if e["template"] == "json" else "extract_interface_from_docx_xml.py"
            run(["scripts/" + script, docx, "--id", e["id"], "--name", e["name"], "--out-dir", domain_dir],
                fatal=False, label=f"extract {e['id']}")
            run(["scripts/lint_source_document.py", docx, "--out-dir", domain_dir], fatal=False, label=f"lint {e['id']}")
            run(["scripts/generate_findings_tracker.py", "--domain-dir", domain_dir, "--domain-name", e["domain"],
                 "--interface-id", e["id"], "--out", reports / f"{e['id']}_Findings_Tracker.xlsx"],
                fatal=False, label=f"tracker {e['id']}")
    else:
        print("\n== Stage 1 / 1.5 skipped (no --docs-dir)")

    print("\n== Stage 3: validate")
    run(["scripts/validate_all.py"])

    print("\n== Stage 4: compile")
    run(["scripts/compile_knowledge_hub.py", "--out", out / "exampleData.generated.js"])
    shutil.copyfile(out / "exampleData.generated.js", ui / "src" / "data" / "exampleData.js")

    print("\n== Stage 4b: OpenAPI")
    shutil.rmtree(out / "openapi", ignore_errors=True)
    run(["scripts/generate_openapi.py", "--out-dir", out / "openapi"])
    shutil.copytree(out / "openapi", ui / "public" / "openapi", dirs_exist_ok=True)

    print("\n== Stage 5: run reports")
    pages = []
    for e in entries:
        domain_dir = Path("domains") / e["domain"]
        if not (domain_dir / "interfaces.yaml").is_file():
            continue
        run(["scripts/generate_run_report.py", "--domain-dir", domain_dir, "--interface-id", e["id"]],
            fatal=False, label=f"run report {e['id']}")
        dest = reports / e["domain"]
        dest.mkdir(parents=True, exist_ok=True)
        for md in sorted(domain_dir.glob("*.md")):
            if md.name not in (f"RUN_REPORT_{e['id']}.md", "DOC_QUALITY_REPORT.md", "REVIEW_REPORT.md"):
                continue
            shutil.copyfile(md, dest / md.name)
            page = dest / (md.stem + ".html")
            rc = run(["scripts/md_to_html.py", md, "--out", page, "--title", f"{e['id']} - {md.stem}"],
                     fatal=False, label=f"html {md.name}")
            if rc == 0:
                pages.append((e["id"], md.stem, page.relative_to(reports).as_posix()))

    items = "\n".join(
        f'<li><b>{html.escape(i)}</b> &ndash; <a href="{html.escape(p)}">{html.escape(t)}</a></li>' for i, t, p in sorted(set(pages))
    ) or "<li>No reports were generated.</li>"
    (reports / "index.html").write_text(
        f"<!doctype html><meta charset='utf-8'><title>Pipeline reports</title>"
        f"<body style='font-family:Segoe UI,Arial,sans-serif;margin:2rem'><h1>Pipeline reports</h1><ul>{items}</ul>"
        f"<p><a href='../'>Back to the Knowledge Hub</a></p></body>",
        encoding="utf-8",
    )
    print(f"\nPipeline finished. Reports: {reports.resolve()}")


if __name__ == "__main__":
    main()
