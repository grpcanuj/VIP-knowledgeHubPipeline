#!/usr/bin/env python3
"""
fetch_from_local.py
-------------------
Picks up one vendor .docx that is already on the VM and records its version in a lock file.
Exits "unchanged" when the content hash matches the lock entry, so unchanged documents never
produce a new PR. Only the file name is taken from the manifest; the file must sit directly
inside --docs-dir.

Usage:
    python scripts/fetch_from_local.py --id CV07_02 --docs-dir /srv/knowledge-hub/docs \
        --file CV07_02_TMS_2_SHIP_EVENTS.docx --lock source_docs.lock.json

With $GITHUB_OUTPUT set, writes `changed=true|false` and `docx_path=<file>`.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 25 * 1024 * 1024


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--docs-dir", required=True)
    ap.add_argument("--file", required=True, help="File name only, e.g. CV07_02_TMS_2_SHIP_EVENTS.docx")
    ap.add_argument("--lock", required=True)
    args = ap.parse_args()

    if Path(args.file).name != args.file or not args.file.lower().endswith(".docx"):
        fail(f"--file must be a plain .docx file name, got {args.file!r}")

    docs_dir = Path(args.docs_dir).resolve()
    docx = (docs_dir / args.file).resolve()
    if docx.parent != docs_dir:
        fail(f"{args.file} resolves outside {docs_dir}")
    if not docx.is_file():
        fail(f"not found on the VM: {docx}")
    if docx.stat().st_size > MAX_BYTES:
        fail(f"{args.file} is larger than {MAX_BYTES // (1024 * 1024)} MB")

    content = docx.read_bytes()
    if not content.startswith(b"PK"):
        fail(f"{args.file} is not a valid .docx package")

    sha = hashlib.sha256(content).hexdigest()
    lock_path = Path(args.lock)
    lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else {}
    changed = lock.get(args.id, {}).get("sha256") != sha

    if changed:
        lock[args.id] = {
            "file": args.file,
            "last_modified": datetime.fromtimestamp(docx.stat().st_mtime, timezone.utc).isoformat(),
            "sha256": sha,
        }
        lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"{args.id}: {'changed' if changed else 'unchanged'} (sha256 {sha[:12]})")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
            fh.write(f"docx_path={docx if changed else ''}\n")


if __name__ == "__main__":
    main()
