#!/usr/bin/env python3
"""
ingest_manifest.py
------------------
Reads interfaces.manifest.yaml, validates every entry, and emits the GitHub Actions
matrix of interfaces to ingest. Only manifest-listed, enabled entries are ever returned,
and every value that later reaches a shell is checked against a strict pattern.

Usage:
    python scripts/ingest_manifest.py --manifest interfaces.manifest.yaml [--id CV07_02] [--path "/Integration Specs/x.docx"]

With $GITHUB_OUTPUT set, writes `matrix=<json>` and `has_work=true|false`.
"""
import argparse
import json
import os
import re
import sys

import yaml

PATTERNS = {
    "id": re.compile(r"^[A-Za-z0-9_]+$"),
    "name": re.compile(r"^[A-Za-z0-9_]+$"),
    "domain": re.compile(r"^[a-z0-9_]+$"),
    "variant": re.compile(r"^[a-z0-9_-]+$"),
}


def validate(entry):
    for key, pattern in PATTERNS.items():
        if not pattern.match(str(entry.get(key, ""))):
            raise ValueError(f"manifest entry {entry.get('id')!r}: invalid or missing '{key}'")
    if entry.get("template") not in ("json", "xml"):
        raise ValueError(f"manifest entry {entry['id']!r}: template must be 'json' or 'xml'")
    path = str(entry.get("sharepoint_path", ""))
    if not path.startswith("/") or ".." in path.split("/") or not path.lower().endswith(".docx"):
        raise ValueError(f"manifest entry {entry['id']!r}: sharepoint_path must be an absolute .docx path")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--id", default="")
    ap.add_argument("--path", default="")
    args = ap.parse_args()

    with open(args.manifest, encoding="utf-8") as fh:
        entries = (yaml.safe_load(fh) or {}).get("interfaces") or []

    seen = set()
    include = []
    for e in entries:
        validate(e)
        if e["id"] in seen:
            raise ValueError(f"duplicate id in manifest: {e['id']}")
        seen.add(e["id"])

        if not e.get("enabled", False):
            continue
        if args.id and e["id"] != args.id:
            continue
        if args.path and e["sharepoint_path"].strip("/").lower() != args.path.strip("/").lower():
            continue

        include.append({
            "id": e["id"],
            "name": e["name"],
            "domain": e["domain"],
            "template": e["template"],
            "variant": e["variant"],
            "sharepoint_path": e["sharepoint_path"],
            "base_branch": "develop" if e["variant"] == "default" else f"variant/{e['variant']}",
        })

    matrix = json.dumps({"include": include}, separators=(",", ":"))
    print(matrix)

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"matrix={matrix}\n")
            fh.write(f"has_work={'true' if include else 'false'}\n")


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
