#!/usr/bin/env python3
"""
promote_cv07_draft.py
----------------------
Step 2 of the pipeline for CV07_01: the human-review pass over the
auto-extracted draft. Rather than hand-editing 80 YAML entries one at a
time, the reviewer's judgement calls are expressed as a short list of
RULES below and applied programmatically - this is itself the reusable
part: the next interface's reviewer edits THIS list of rules (which stays
short - a dozen lines) instead of retyping fields.

Promotes domains/cv07_shippeo/{fields,interfaces}.draft.yaml ->
domains/cv07_shippeo/{fields,interfaces}.yaml (the files validate_all.py
and compile_knowledge_hub.py actually read).
"""
from pathlib import Path
import yaml

DOMAIN = Path("domains/cv07_shippeo")

# Reviewer call #1: these are protocol-level constants (fixed by the
# interface spec, not business data about a customer/shipment) - public,
# not internal.
PUBLIC_CONSTANT_FIELDS = {
    "meta-senderid", "meta-duplicatereceiverid", "meta-messagetype", "meta-messagefunction",
    "transportservicebuyer-qualifier", "carrier-qualifier", "transportmean-istrackable",
    "customattributes-name", "references-qualifier", "pickup-identifications-qualifier",
    "pickup-dates-qualifier", "orders-goodsdescription", "attributes-name", "tags-permission",
    "tags-active", "items-description", "handlingunits-custompackagingqualifier",
}

# Reviewer call #2: these carry fiscal/legal identifiers - confidential,
# not internal, regardless of the generic default.
CONFIDENTIAL_FIELDS = {
    "consignor-taxreference", "customer-taxreference", "carrier-taxreference",
}

# Reviewer call #3: genuine PII (person-identifying once Shippeo's driver
# app resolves a vehicle/trip to a named driver) - none in this payload at
# the field level we extracted, but the pattern is here for the next
# interface that does carry e.g. a driver name or phone number.
PII_FIELDS = set()

# Reviewer call #4: a few fields the auto-extraction correctly flagged as
# needing confirmation, where the correct status is actually "conditional"
# (not every payload carries them) rather than the "mandatory" default -
# per Business Rules BR-01 in the source doc, Driver-related data is
# optional for everyone except the AndSoft/2020 cluster.
CONDITIONAL_FIELDS = {
    "clientidentification-agency",   # "agency code in charge" - TBD/optional per doc
    "documentproperties-additionalconditions",
}


def main():
    fields = yaml.safe_load(open(DOMAIN / "fields.draft.yaml", encoding="utf-8"))["fields"]
    interfaces = yaml.safe_load(open(DOMAIN / "interfaces.draft.yaml", encoding="utf-8"))["interfaces"]

    for f in fields:
        fid = f["field_id"]
        if fid in PUBLIC_CONSTANT_FIELDS:
            f["sensitivity"] = "public"
        elif fid in CONFIDENTIAL_FIELDS:
            f["sensitivity"] = "confidential"
        elif fid in PII_FIELDS:
            f["sensitivity"] = "pii"
        if fid in CONDITIONAL_FIELDS:
            f["status"] = "conditional"

    with open(DOMAIN / "fields.yaml", "w", encoding="utf-8") as fh:
        fh.write("# Domain: CV07_01 TMS -> Shippeo transport orders (Create/Update/Cancel, PLN/APLN)\n")
        fh.write("# Promoted from fields.draft.yaml after human review (see promote_cv07_draft.py for the\n")
        fh.write("# review rules applied) - this is the file validate_all.py / compile_knowledge_hub.py read.\n\n")
        yaml.safe_dump({"fields": fields}, fh, sort_keys=False, allow_unicode=True, width=100)

    with open(DOMAIN / "interfaces.yaml", "w", encoding="utf-8") as fh:
        fh.write("# Domain: CV07_01 TMS -> Shippeo transport orders (Create/Update/Cancel, PLN/APLN)\n")
        fh.write("# Promoted from interfaces.draft.yaml after human review.\n\n")
        yaml.safe_dump({"interfaces": interfaces}, fh, sort_keys=False, allow_unicode=True, width=100)

    print(f"Promoted {len(fields)} fields and {len(interfaces)} interface(s) to domains/cv07_shippeo/*.yaml")


if __name__ == "__main__":
    main()
