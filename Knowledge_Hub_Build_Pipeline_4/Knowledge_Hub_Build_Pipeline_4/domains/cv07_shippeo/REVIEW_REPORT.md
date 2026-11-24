# Extraction review report - CV07_01_TMS_SHIP_ORDERS

Source document: `CV07_01_TMS_SHIP_ORDERS.docx`

- Leaf fields extracted: **80** unique glossary fields from **99** payload occurrences
- Overview bullets found: 5
- Endpoint info found: yes
- Required headers table: 7 header(s) found
- Field-level validation rules table: 3 rule(s) found
- Business rules table: 6 rule(s) found

## Needs human review before promoting

- `meta-messagereference` (path `meta.messageReference`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `transportservicebuyer-identifier` (path `shipment.transportServiceBuyer[].identifier`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `transportmean-qualifier` (path `shipment.transportMean[].qualifier`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `transportmean-text` (path `shipment.transportMean[].text`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `transportmean-istrackable` (path `shipment.transportMean[].isTrackable`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `documentproperties-type` (path `shipment.orders[].consignmentNote.documentProperties.type`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `documentproperties-additionalconditions` (path `shipment.orders[].consignmentNote.documentProperties.additionalConditions`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `references-reference` (path `shipment.orders[].references[].reference`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `pickup-instructions` (path `shipment.orders[].pickUp.instructions`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `consignee-instructions` (path `shipment.orders[].consignee.instructions`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `clientidentification-agency` (path `shipment.orders[].clientIdentification.agency`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `attributes-value` (path `shipment.orders[].attributes[].value`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `tags-label` (path `shipment.orders[].tags[].label`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `items-reference` (path `shipment.orders[].items[].reference`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `items-ean` (path `shipment.orders[].items[].EAN`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.
- `handlingunits-trackingcode` (path `shipment.orders[].handlingUnits[].trackingCode`): AndSoft source column not supplied in the template (shown as '?' or TBD) - confirm with AndSoft before build.

## Defaults applied automatically (confirm or correct)

- Every field defaulted to `status: mandatory`, `sensitivity: internal`, `source_system: AndSoft TMS` - the template doesn't carry these, so a reviewer must set the real value per field.
- `data_type` defaults to `string` when the template used a type the schema doesn't recognise.
- Interface `source_system` / `target_system` came from the Overview bullets; confirm they parsed correctly.
