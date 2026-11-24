#!/usr/bin/env python3
"""
fetch_from_sharepoint.py
------------------------
Downloads one vendor .docx from SharePoint Online (Microsoft Graph, app-only auth) and
records its version in a lock file. Exits without downloading to disk when the content
hash matches the lock entry, so unchanged documents never produce a new PR.

Environment: SP_TENANT_ID, SP_CLIENT_ID, SP_CLIENT_SECRET,
             SP_SITE  e.g. contoso.sharepoint.com:/sites/IntegrationHub

Usage:
    python scripts/fetch_from_sharepoint.py --id CV07_02 \
        --sharepoint-path "/Integration Specs/Shippeo/CV07_02_TMS_2_SHIP_EVENTS.docx" \
        --out-dir /tmp/specs --lock source_docs.lock.json

With $GITHUB_OUTPUT set, writes `changed=true|false` and `docx_path=<file>`.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
MAX_BYTES = 25 * 1024 * 1024
TIMEOUT = 60


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def get_token():
    try:
        tenant, client, secret = (os.environ[k] for k in ("SP_TENANT_ID", "SP_CLIENT_ID", "SP_CLIENT_SECRET"))
    except KeyError as exc:
        fail(f"missing environment variable {exc}")
    r = requests.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client,
            "client_secret": secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        fail(f"token request failed ({r.status_code}); check the app registration and secret")
    return r.json()["access_token"]


def graph_get(session, url, **kw):
    r = session.get(url, timeout=TIMEOUT, **kw)
    if r.status_code == 404:
        fail(f"not found in SharePoint: {url.split('/v1.0')[-1]}")
    if r.status_code in (401, 403):
        fail(f"access denied ({r.status_code}); the app needs Sites.Selected access to this site")
    r.raise_for_status()
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--sharepoint-path", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--lock", required=True)
    args = ap.parse_args()

    site = os.environ.get("SP_SITE") or fail("missing environment variable SP_SITE")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {get_token()}"

    site_id = graph_get(session, f"{GRAPH}/sites/{quote(site, safe=':/')}").json()["id"]
    item = graph_get(
        session,
        f"{GRAPH}/sites/{site_id}/drive/root:{quote(args.sharepoint_path, safe='/')}",
        params={"$select": "id,name,eTag,size,file,lastModifiedDateTime,lastModifiedBy"},
    ).json()

    name = item.get("name", "")
    if "file" not in item or not name.lower().endswith(".docx"):
        fail(f"{args.sharepoint_path} is not a .docx file")
    if item.get("size", 0) > MAX_BYTES:
        fail(f"{name} is larger than {MAX_BYTES // (1024 * 1024)} MB")

    # Graph redirects to a pre-authenticated URL; requests drops the Authorization header on the cross-host hop.
    content = graph_get(session, f"{GRAPH}/sites/{site_id}/drive/items/{item['id']}/content").content
    if len(content) > MAX_BYTES or not content.startswith(b"PK"):
        fail(f"{name} is not a valid .docx package")

    sha = hashlib.sha256(content).hexdigest()

    lock_path = Path(args.lock)
    lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else {}
    changed = lock.get(args.id, {}).get("sha256") != sha

    docx_path = ""
    if changed:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        docx_path = str(out_dir / safe_name)
        Path(docx_path).write_bytes(content)

        modified_by = ((item.get("lastModifiedBy") or {}).get("user") or {}).get("displayName", "")
        lock[args.id] = {
            "sharepoint_path": args.sharepoint_path,
            "sharepoint_item_id": item["id"],
            "etag": item.get("eTag", ""),
            "last_modified": item.get("lastModifiedDateTime", ""),
            "modified_by": modified_by,
            "sha256": sha,
        }
        lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"{args.id}: {'changed' if changed else 'unchanged'} (sha256 {sha[:12]})")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
            fh.write(f"docx_path={docx_path}\n")


if __name__ == "__main__":
    main()
