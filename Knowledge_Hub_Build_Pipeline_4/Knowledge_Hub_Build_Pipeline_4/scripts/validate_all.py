#!/usr/bin/env python3
"""
validate_all.py
----------------
Generic, multi-domain replacement for validate_oms_tms_examples.py. The
original validator hardcoded one domain's filenames; this one globs every
domain folder under domains/ so it keeps working unchanged as new domains
(one per batch of interfaces) are added - this is the CI gate referenced in
the Full Stack Developer JD ("Build and maintain CI checks that validate
every reference").

Checks, across ALL domains combined:
  1. Every field/interface/flow record validates against its JSON Schema.
  2. Every interface.fields[].field_id resolves to a field defined
     SOMEWHERE across all domains (fields can be shared/reused cross-domain).
  3. Every flow.steps[].interface_id resolves to an interface defined
     somewhere across all domains.
  4. No duplicate field_id or interface id across domains (a collision
     almost always means the same concept was redefined instead of reused,
     or two different concepts were accidentally given the same id).

Usage: python3 validate_all.py [--domains-dir domains] [--schemas-dir schemas]
Exit code 0 = all good (safe to merge/compile), 1 = failures found.
"""
import argparse
import glob
import json
import sys
from pathlib import Path

import yaml
from jsonschema import validate, ValidationError


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_schema(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domains-dir", default="domains")
    ap.add_argument("--schemas-dir", default="schemas")
    args = ap.parse_args()

    field_schema = load_schema(f"{args.schemas_dir}/field.schema.json")
    interface_schema = load_schema(f"{args.schemas_dir}/interface.schema.json")
    flow_schema = load_schema(f"{args.schemas_dir}/flow.schema.json")

    errors = []
    all_fields = {}       # field_id -> (domain, record)
    all_interfaces = {}   # id -> (domain, record)
    all_flows = {}        # id -> (domain, record)

    domain_dirs = sorted(d for d in glob.glob(f"{args.domains_dir}/*") if Path(d).is_dir())

    for d in domain_dirs:
        domain = Path(d).name
        fp, ip, flp = f"{d}/fields.yaml", f"{d}/interfaces.yaml", f"{d}/flows.yaml"

        if Path(fp).exists():
            for rec in (load_yaml(fp).get("fields") or []):
                try:
                    validate(instance=rec, schema=field_schema)
                except ValidationError as e:
                    errors.append(f"[{domain}][field.schema] {rec.get('field_id')}: {e.message}")
                fid = rec.get("field_id")
                if fid in all_fields:
                    other_domain = all_fields[fid][0]
                    errors.append(
                        f"[{domain}][dup] field_id '{fid}' already defined in domain "
                        f"'{other_domain}' - reuse it by reference instead of redefining, "
                        f"or rename one of them if they're genuinely different concepts."
                    )
                else:
                    all_fields[fid] = (domain, rec)

        if Path(ip).exists():
            for rec in (load_yaml(ip).get("interfaces") or []):
                try:
                    validate(instance=rec, schema=interface_schema)
                except ValidationError as e:
                    errors.append(f"[{domain}][interface.schema] {rec.get('id')}: {e.message}")
                iid = rec.get("id")
                if iid in all_interfaces:
                    other_domain = all_interfaces[iid][0]
                    errors.append(f"[{domain}][dup] interface id '{iid}' already defined in domain '{other_domain}'")
                else:
                    all_interfaces[iid] = (domain, rec)

        if Path(flp).exists():
            for rec in (load_yaml(flp).get("flows") or []):
                try:
                    validate(instance=rec, schema=flow_schema)
                except ValidationError as e:
                    errors.append(f"[{domain}][flow.schema] {rec.get('id')}: {e.message}")
                all_flows[rec.get("id")] = (domain, rec)

    # Cross-reference checks across the WHOLE merged set
    for iid, (domain, rec) in all_interfaces.items():
        for fref in rec.get("fields", []):
            fid = fref.get("field_id")
            if fid not in all_fields:
                errors.append(f"[{domain}][xref] Interface {iid} references unknown field_id '{fid}'")

    for flid, (domain, rec) in all_flows.items():
        for step in rec.get("steps", []):
            iid = step.get("interface_id")
            if iid is not None and iid not in all_interfaces:
                errors.append(f"[{domain}][xref] Flow {flid} step {step.get('step')} references unknown interface_id '{iid}'")

    print(f"Domains scanned:   {len(domain_dirs)} ({', '.join(Path(d).name for d in domain_dirs)})")
    print(f"Fields loaded:      {len(all_fields)}")
    print(f"Interfaces loaded:  {len(all_interfaces)}")
    print(f"Flows loaded:       {len(all_flows)}")
    print()

    if errors:
        print(f"FAILED - {len(errors)} issue(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("PASSED - all records valid, all field_id/interface_id references resolve, no duplicate ids.")


if __name__ == "__main__":
    main()
