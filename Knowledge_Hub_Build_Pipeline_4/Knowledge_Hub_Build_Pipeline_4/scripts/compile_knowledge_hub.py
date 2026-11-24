#!/usr/bin/env python3
"""
compile_knowledge_hub.py
--------------------------
The actual "static-site compile pipeline that turns validated YAML into the
Glossary, Interface Index, Flow Diagram, and Traceability HTML pages" that
the Full Stack Developer JD describes. This is the step that replaces the
React app's hand-typed src/data/exampleData.js with a generated file of the
exact same shape, so NONE of the four page components (GlossaryPage,
InterfaceIndexPage, FlowViewPage, TraceabilityPage) need to change - they
already import FIELDS / INTERFACES / FLOWS / REQUIREMENTS from that module
and call getField()/getInterface()/getRequirement(). Only where that module
comes from changes: from a human typing demo values, to this script reading
every domains/*/{fields,interfaces,flows}.yaml.

Run validate_all.py first (or let this script call it) - compiling
unvalidated YAML would bake broken cross-references straight into the UI.

Usage:
    python3 compile_knowledge_hub.py --out ../t1_app/src/data/exampleData.generated.js
"""
import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path

import yaml

SENSITIVITY_LABEL = {"public": "Public", "internal": "Internal", "confidential": "Confidential", "pii": "PII"}
STATUS_LABEL = {
    "mandatory": "Mandatory on every record",
    "conditional": "Conditional - present only when the triggering business rule applies",
    "optional": "Optional",
}


def load_yaml(path):
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def humanize_data_type(field):
    dt = field.get("data_type", "string")
    fmt = field.get("format")
    base = {
        "string": "String",
        "integer": "Integer",
        "decimal": "Decimal",
        "boolean": "Boolean",
        "date": "Date",
        "datetime": "DateTime, ISO-8601",
        "enum": "String (enum)",
    }.get(dt, dt)
    if fmt and dt not in ("datetime",):
        return f"{base} ({fmt})"
    return base


def compile_fields(all_fields, field_to_interfaces):
    out = []
    for fid, (domain, f) in sorted(all_fields.items()):
        allowed = f.get("allowed_values")
        quality_rules = f.get("quality_rules") or []
        fixed = next(
            (r for r in quality_rules if r.lower().startswith("fixed value")), None
        )
        out.append({
            "id": fid,
            "definition": f.get("description") or f.get("name", fid),
            "owner": f.get("source_system", "TBD"),
            "sensitivity": SENSITIVITY_LABEL.get(f.get("sensitivity", "internal"), "Internal"),
            "usedIn": sorted(field_to_interfaces.get(fid, [])),
            "businessTerm": f.get("name", fid),
            "object": domain,
            "dataType": humanize_data_type(f),
            "length": f.get("format", "—"),
            "allowedValues": ", ".join(allowed) if allowed else (fixed or "—"),
            "mandatory": STATUS_LABEL.get(f.get("status", "mandatory"), f.get("status", "mandatory")),
            "sourceSystem": f.get("source_system", "TBD"),
            "targetSystems": ", ".join(sorted({
                iface["target_system"] for iface in (
                    all_fields_interfaces_for(fid, field_to_interfaces)
                )
            })) or "—",
            "transformationRules": fixed or "None documented",
            "dataQualityRules": "; ".join(r for r in quality_rules if not r.lower().startswith("fixed value")) or "None documented",
        })
    return out


_IFACE_LOOKUP_CACHE = {}


def all_fields_interfaces_for(fid, field_to_interfaces):
    return [_IFACE_LOOKUP_CACHE[iid] for iid in field_to_interfaces.get(fid, []) if iid in _IFACE_LOOKUP_CACHE]


def compile_interfaces(all_interfaces):
    out = []
    field_to_interfaces = {}
    for iid, (domain, i) in all_interfaces.items():
        _IFACE_LOOKUP_CACHE[iid] = i
        for fref in i.get("fields", []):
            field_to_interfaces.setdefault(fref["field_id"], set()).add(iid)

    for iid, (domain, i) in sorted(all_interfaces.items()):
        out.append({
            "id": iid,
            "name": i.get("name", iid),
            "source": i.get("source_system", "TBD"),
            "target": i.get("target_system", "TBD"),
            "type": f"{i.get('protocol', 'REST')}" + (" / Webhook" if i.get("protocol") == "REST" and i.get("response_contract") else ""),
            "specVersion": i.get("spec_version", "TBD"),
            "owner": i.get("owner", "TBD"),
            "path": f"{i.get('method', 'POST')} {i.get('endpoint_url', 'TBD')}",
            "frequency": i.get("frequency", "TBD"),
            "fields": [fref["field_id"] for fref in i.get("fields", [])],
            "usedByRequirement": i.get("used_by_requirement"),
            "hasOwnSpec": i.get("spec_type") not in ("vendor-template", "none", None),
        })
    return out, field_to_interfaces


def generate_mermaid(flow):
    lines = ["flowchart TD"]
    steps = flow.get("steps", [])
    node_id = lambda n: f"S{n}"
    for s in steps:
        label = s["description"].replace('"', "'")
        lines.append(f'  {node_id(s["step"])}["{label}"]')
    for a, b in zip(steps, steps[1:]):
        iid = b.get("interface_id")
        if iid:
            lines.append(f'  {node_id(a["step"])} -->|"{iid}"| {node_id(b["step"])}')
        else:
            lines.append(f'  {node_id(a["step"])} --> {node_id(b["step"])}')
    return "\n".join(lines)


def compile_flows(all_flows):
    out = []
    for flid, (domain, fl) in sorted(all_flows.items()):
        out.append({
            "id": flid,
            "name": fl.get("name", flid),
            "deliverable": "#5",
            "description": (fl.get("description") or "").strip(),
            "interfaces": sorted({s["interface_id"] for s in fl.get("steps", []) if s.get("interface_id")}),
            "diagram": generate_mermaid(fl),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domains-dir", default="domains")
    ap.add_argument("--schemas-dir", default="schemas")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip-validate", action="store_true")
    args = ap.parse_args()

    if not args.skip_validate:
        r = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "validate_all.py"),
             "--domains-dir", args.domains_dir, "--schemas-dir", args.schemas_dir],
            capture_output=True, text=True,
        )
        print(r.stdout)
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            print("Refusing to compile: validate_all.py found errors. Fix them first.", file=sys.stderr)
            sys.exit(1)

    domain_dirs = sorted(d for d in glob.glob(f"{args.domains_dir}/*") if Path(d).is_dir())

    all_fields, all_interfaces, all_flows = {}, {}, {}
    for d in domain_dirs:
        domain = Path(d).name
        for rec in (load_yaml(f"{d}/fields.yaml").get("fields") or []):
            all_fields[rec["field_id"]] = (domain, rec)
        for rec in (load_yaml(f"{d}/interfaces.yaml").get("interfaces") or []):
            all_interfaces[rec["id"]] = (domain, rec)
        for rec in (load_yaml(f"{d}/flows.yaml").get("flows") or []):
            all_flows[rec["id"]] = (domain, rec)

    interfaces_out, field_to_interfaces = compile_interfaces(all_interfaces)
    fields_out = compile_fields(all_fields, field_to_interfaces)
    flows_out = compile_flows(all_flows)

    js = []
    js.append("// AUTO-GENERATED by compile_knowledge_hub.py - do not hand-edit.")
    js.append("// Source of truth is domains/*/{fields,interfaces,flows}.yaml - edit those and recompile.")
    js.append(f"// Compiled from {len(domain_dirs)} domain(s): {', '.join(Path(d).name for d in domain_dirs)}")
    js.append("")
    js.append(f"export const FIELDS = {json.dumps(fields_out, indent=2)};")
    js.append("")
    js.append(f"export const INTERFACES = {json.dumps(interfaces_out, indent=2)};")
    js.append("")
    js.append(f"export const FLOWS = {json.dumps(flows_out, indent=2)};")
    js.append("")
    js.append("// Requirements/test-evidence are owned by Tower 2 (system of record for test")
    js.append("// execution) - Tower 1 holds only a thin pointer, refreshed via the Tower 2 API/")
    js.append("// event feed, not redefined here. Populate via a requirements.yaml per domain,")
    js.append("// or wire the live Tower 2 query, once that integration is built.")
    js.append("export const REQUIREMENTS = [];")
    js.append("")
    js.append("export function getField(id) {\n  return FIELDS.find((f) => f.id === id);\n}")
    js.append("export function getInterface(id) {\n  return INTERFACES.find((i) => i.id === id);\n}")
    js.append("export function getRequirement(id) {\n  return REQUIREMENTS.find((r) => r.id === id);\n}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(js) + "\n", encoding="utf-8")

    print(f"\nCompiled {len(fields_out)} fields, {len(interfaces_out)} interfaces, {len(flows_out)} flows -> {out_path}")


if __name__ == "__main__":
    main()
