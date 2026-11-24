# Extraction review report - CV07_02_TMS_2_SHIP_EVENTS

Source document: `CV07_02_TMS_2_SHIP_EVENTS.docx`

- Leaf fields extracted: **32** unique glossary fields from **32** payload occurrences
- Overview bullets found: 0
- Endpoint info found: no - check manually
- Required headers table: 5 header(s) found
- Field-level validation rules table: 4 rule(s) found
- Business rules table: 6 rule(s) found

## Needs human review before promoting

- `events-technicalreference` (path `events[].technicalReference`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `items-reference` (path `events[].items[].reference`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.

## Defaults applied automatically (confirm or correct)

- Every field defaulted to `status: mandatory`, `sensitivity: internal`, `source_system: AndSoft TMS` - the template doesn't carry these, so a reviewer must set the real value per field.
- `data_type` defaults to `string` when the template used a type the schema doesn't recognise.
- Interface `source_system` / `target_system` / `frequency` (from the Overview's `Trigger:` bullet) came from the document; confirm they parsed correctly.
- `owner` defaults to the Overview's `Source system` bullet - this template has no explicit `Owner:` bullet, so confirm who is actually accountable.
- `protocol` defaults to `REST` - this template never states a protocol explicitly; confirm manually for any interface that isn't a REST call.
- `flow_owner` defaults to the same value as `owner` (`TBD`) - update it once RACI ownership is confirmed, if it differs.
- `message_format` derived from the endpoint table's Content-Type (`TBD`).

## New LLD fields - manual completion required

These are not present anywhere in AndSoft's document (confirmed by direct keyword search across every paragraph and table cell) and are left empty on purpose - get the real value from the owning team during review/promote rather than guessing one:

- `volume_profile` - expected volume, peak window, latency SLA.
- `deduplication_strategy` - this interface's own extracted `idempotent` flag is `True`, with retry policy: "". Check whether any field marked `fixed_value` in fields.yaml (constant per message) is being assumed as a dedup key before relying on one - a fixed value can't disambiguate messages.
- `monitoring` - key metrics, alert thresholds, dashboard/tool.
- `acceptance_criteria` - UAT sign-off criteria for this interface.
- `test_data_ref` - cross-reference to the Testing Hub's test-suite id, once assigned (Testing Hub scope itself is unchanged).
