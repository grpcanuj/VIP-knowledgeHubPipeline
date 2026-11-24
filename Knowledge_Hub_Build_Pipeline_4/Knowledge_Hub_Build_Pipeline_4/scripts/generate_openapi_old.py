#!/usr/bin/env python3
"""
generate_openapi.py
---------------------
Generates a real OpenAPI 3.0.3 spec per interface from the validated
fields.yaml/interfaces.yaml - the same source of truth compile_knowledge_hub.py
reads for the React app. This is exactly the Swagger/OpenAPI deliverable
Andsoft originally intended to supply directly; until they do, we derive it
from their Word-template documents instead, through the same pipeline.

Each field's `path` (e.g. 'shipment.orders[].pickUp.dates[].dateTime') is
walked to reconstruct the real nested JSON Schema - '[]' marks an array
container, everything else is a plain object - and that path has ALREADY
been corrected against the document's own worked JSON example (see
correct_paths_against_example in extract_interface_from_docx.py), not left
to the vendor's Type column alone, which was wrong for 9 of CV07_01's 25
containers.

Usage:
    python3 generate_openapi.py --domains-dir domains --schemas-dir schemas \
        --out-dir output/openapi
Writes one <interface_id>.openapi.yaml + .json per interface, plus
validates each with openapi_spec_validator before writing (refuses to
write a spec that doesn't validate).
"""
import argparse
import glob
import json
import re
import sys
from pathlib import Path

import yaml

try:
    from openapi_spec_validator import validate as validate_openapi
    from openapi_spec_validator.exceptions import OpenAPIError as OpenAPIValidationError
    HAVE_VALIDATOR = True
except ImportError:
    HAVE_VALIDATOR = False


DATA_TYPE_MAP = {
    "string": {"type": "string"},
    "integer": {"type": "integer"},
    "decimal": {"type": "number", "format": "float"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
    "datetime": {"type": "string", "format": "date-time"},
    "enum": {"type": "string"},
}


def load_yaml(path):
    p = Path(path)
    if not p.exists():
        return {}
    with open(p) as fh:
        return yaml.safe_load(fh) or {}


def load_all_fields(domains_dir):
    registry = {}
    for d in sorted(glob.glob(f"{domains_dir}/*")):
        if not Path(d).is_dir():
            continue
        for rec in (load_yaml(f"{d}/fields.yaml").get("fields") or []):
            registry[rec["field_id"]] = rec
    return registry


def field_schema(field_rec, fixed_value=None):
    """Render one leaf Field record as an OpenAPI schema fragment."""
    dt = field_rec.get("data_type", "string")
    schema = dict(DATA_TYPE_MAP.get(dt, {"type": "string"}))

    if field_rec.get("allowed_values"):
        schema["enum"] = list(field_rec["allowed_values"])
    elif dt == "enum":
        # schema says enum but no allowed_values recorded - leave as plain
        # string rather than emit an invalid empty enum.
        schema["type"] = "string"

    fmt = field_rec.get("format", "")
    m = re.match(r"max length (\d+)", fmt or "")
    if m and schema.get("type") == "string":
        schema["maxLength"] = int(m.group(1))

    if field_rec.get("description"):
        schema["description"] = field_rec["description"]

    example = fixed_value or (schema.get("enum", [None])[0])
    if example:
        schema["example"] = example

    return schema


class TreeNode:
    __slots__ = ("kind", "children", "field_id", "required", "fixed_value")

    def __init__(self):
        self.kind = None        # "object" | "array" | "leaf"
        self.children = {}
        self.field_id = None
        self.required = False
        self.fixed_value = None


def build_tree(fields_refs):
    root = TreeNode()
    root.kind = "object"
    for fref in fields_refs:
        # Older/simpler interface records (written before `path` existed in
        # the schema - e.g. the original IF-101/IF-102/IF-103 examples) have
        # no path at all: every field is a top-level flat property, so the
        # field_id itself is the path.
        path = fref.get("path", fref["field_id"])
        segs = path.split(".")
        node = root
        for i, seg in enumerate(segs):
            is_array = seg.endswith("[]")
            name = seg[:-2] if is_array else seg
            is_leaf = (i == len(segs) - 1)
            if is_leaf:
                child = node.children.setdefault(name, TreeNode())
                child.kind = "leaf"
                child.field_id = fref["field_id"]
                child.required = bool(fref.get("required"))
                child.fixed_value = fref.get("fixed_value")
            else:
                child = node.children.setdefault(name, TreeNode())
                if child.kind is None:
                    child.kind = "array" if is_array else "object"
                node = child
    return root


def render_node(node, fields_registry):
    if node.kind == "leaf":
        rec = fields_registry.get(node.field_id, {"data_type": "string"})
        return field_schema(rec, fixed_value=node.fixed_value)

    if node.kind == "array":
        # Our model doesn't carry a separate "array-of-scalars" case in this
        # dataset; every array container here wraps an object. If a future
        # interface has an array of plain scalars (no children), fall back
        # to a generic object items schema rather than guessing a type.
        if node.children:
            items_obj = TreeNode()
            items_obj.kind = "object"
            items_obj.children = node.children
            return {"type": "array", "items": render_node(items_obj, fields_registry)}
        return {"type": "array", "items": {"type": "object"}}

    # object
    props = {}
    required = []
    for name, child in node.children.items():
        props[name] = render_node(child, fields_registry)
        if child.required:
            required.append(name)
    schema = {"type": "object", "properties": props}
    if required:
        schema["required"] = sorted(required)
    return schema


def build_path_item(iface, request_schema_ref, response_schema_ref=None):
    method = (iface.get("method") or "POST").lower()
    responses = {}
    for sc in (iface.get("response_status_codes") or []):
        responses[sc["code"]] = {"description": sc.get("description") or sc.get("meaning", "")}
    if not responses:
        responses["200"] = {"description": "Successful response"}

    if response_schema_ref:
        for code in list(responses):
            if code.startswith("2"):
                responses[code]["content"] = {
                    "application/json": {"schema": {"$ref": response_schema_ref}}
                }

    operation = {
        "tags": [iface.get("source_system", iface["id"])],
        "summary": iface.get("name", iface["id"]),
        "description": iface.get("description", ""),
        "operationId": re.sub(r"[^a-zA-Z0-9]", "", iface["id"][0].lower() + iface["id"][1:]),
        "responses": responses,
    }

    if method in ("post", "put", "patch"):
        operation["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": {"$ref": request_schema_ref}}},
        }

    return {method: operation}


def path_params_from_url(url):
    """Extract {param} segments from an endpoint URL into OpenAPI path
    parameters, e.g. '/orders/{orderId}' -> a required string path param."""
    params = []
    for m in re.finditer(r"\{(\w+)\}", url or ""):
        params.append({
            "name": m.group(1),
            "in": "path",
            "required": True,
            "description": f"Path parameter: {m.group(1)}",
            "schema": {"type": "string"},
        })
    return params


def url_path_only(url):
    """Strip scheme+host from a full URL, keeping just the path. Leaves a
    'TBD' host as-is in servers rather than guessing one."""
    m = re.match(r"^https?://[^/]+(/.*)$", url or "")
    return (m.group(1) if m else url or "/").strip()


def build_spec_for_interface(iface, fields_registry):
    request_fields = [f for f in iface.get("fields", []) if f.get("io", "request") == "request"]
    response_fields = [f for f in iface.get("fields", []) if f.get("io") == "response"]

    request_tree = build_tree(request_fields)
    request_schema = render_node(request_tree, fields_registry)
    schema_name = f"{iface['id']}Request"

    components_schemas = {schema_name: request_schema}
    response_ref = None
    if response_fields:
        response_tree = build_tree(response_fields)
        response_schema_name = f"{iface['id']}Response"
        components_schemas[response_schema_name] = render_node(response_tree, fields_registry)
        response_ref = f"#/components/schemas/{response_schema_name}"

    raw_url = iface.get("endpoint_url", "/")
    path_key = url_path_only(raw_url)
    path_item = build_path_item(iface, f"#/components/schemas/{schema_name}", response_ref)
    params = path_params_from_url(raw_url)
    if params:
        list(path_item.values())[0]["parameters"] = params

    host_known = raw_url and "TBD" not in raw_url.upper()
    servers = (
        [{"url": raw_url.split(path_key)[0] if path_key in raw_url else raw_url, "description": "Production"}]
        if host_known else
        [
            {"url": "https://TBD/api/v1", "description": "Production - endpoint not yet finalized by the vendor"},
            {"url": "https://TBD-test/api/v1", "description": "Test / UAT - endpoint not yet finalized by the vendor"},
        ]
    )

    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": iface.get("name", iface["id"]),
            "version": iface.get("spec_version", "1.0.0"),
            "description": iface.get("description", "") + (
                "\n\n(Generated from a vendor Word-template document via the Knowledge Hub "
                "pipeline - see spec_type/spec_version in interfaces.yaml. Not yet a vendor-"
                "supplied OpenAPI spec.)" if iface.get("spec_type") == "vendor-template" else ""
            ),
        },
        "servers": servers,
        "tags": [{"name": iface.get("source_system", iface["id"]), "description": f"Operations for {iface.get('name', iface['id'])}"}],
        "paths": {path_key: path_item},
        "components": {"schemas": components_schemas},
    }
    return spec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domains-dir", default="domains")
    ap.add_argument("--out-dir", default="output/openapi")
    ap.add_argument("--interface-id", help="Generate for only this interface id (default: all)")
    args = ap.parse_args()

    fields_registry = load_all_fields(args.domains_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    for d in sorted(glob.glob(f"{args.domains_dir}/*")):
        if not Path(d).is_dir():
            continue
        for iface in (load_yaml(f"{d}/interfaces.yaml").get("interfaces") or []):
            if args.interface_id and iface["id"] != args.interface_id:
                continue
            spec = build_spec_for_interface(iface, fields_registry)

            if HAVE_VALIDATOR:
                try:
                    validate_openapi(spec)
                except OpenAPIValidationError as e:
                    print(f"REFUSING to write spec for {iface['id']}: fails OpenAPI 3.0.3 validation:\n  {e}",
                          file=sys.stderr)
                    sys.exit(1)
            else:
                print("WARNING: openapi_spec_validator not installed - spec was NOT validated before writing.",
                      file=sys.stderr)

            yaml_path = out_dir / f"{iface['id']}.openapi.yaml"
            json_path = out_dir / f"{iface['id']}.openapi.json"
            with open(yaml_path, "w") as fh:
                yaml.safe_dump(spec, fh, sort_keys=False, allow_unicode=True, width=100)
            with open(json_path, "w") as fh:
                json.dump(spec, fh, indent=2)
            generated.append(iface["id"])
            print(f"Wrote {yaml_path} and {json_path} (validated: {HAVE_VALIDATOR})")

    if not generated:
        print("No interfaces found.", file=sys.stderr)
        sys.exit(1)
    print(f"\nGenerated {len(generated)} OpenAPI spec(s): {', '.join(generated)}")


if __name__ == "__main__":
    main()
