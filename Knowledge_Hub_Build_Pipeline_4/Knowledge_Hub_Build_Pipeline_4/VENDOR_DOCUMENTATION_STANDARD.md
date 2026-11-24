# Interface Documentation Standard — for Andsoft

This is what we need from each interface's Technical Analysis document so it can be built into the Integration Knowledge Hub without back-and-forth. It's derived directly from automated checks we now run against every document you send (not just read by eye), so the same rules apply consistently across all interfaces — and findings against this standard can be handed back to you per-document rather than discovered late, one email at a time.

## 1. Every field needs either a source mapping or a stated fixed value

Every row in the field-mapping table must have one of:

- a value in the "Field AndSoft" column (your own source attribute/column name), or
- an explicit "Fixed value: X" note in the Description, when the field is a constant rather than something that varies per record.

A blank or "?" in both places means we cannot build against that field — it becomes a blocking question back to you before development starts. In CV07_01, 16 fields currently fall into this category (full list in that interface's own review).

## 2. If you state a fixed value, make it match the source column

Where a Description says "Fixed value: X", the Field AndSoft column should show the same X — not a different value, and not a conditional expression that contradicts the stated constant. If the real rule is conditional (e.g. "only when a given field equals a certain code"), say so in the Description rather than in the source column alone, so both agree.

## 3. Naming: JSON field names should be camelCase

Per your own Section 2.2 convention, field names are camelCase (`createdAt`, `userId`). Please keep this consistent — acronyms used as a whole name (EAN, VIN, CMR, GPS) are fine as-is.

## 4. If an attribute name repeats with different meanings, consider naming it explicitly instead

Some fields in CV07_01 reuse one generic column name for several unrelated purposes — for example `tags.label` carries a traffic code in one row, a carrier's SAP code in another, and a flag about trip disruption in a third, with nothing in the data itself to tell them apart. Where this is intentional and necessary, that's fine — just make sure the Description for each occurrence is specific enough that a reader can tell them apart (as was the case here). Where it isn't necessary, a named field per purpose is easier for us to build and validate against.

## 5. Describe a repeatable array shape once, not once per example

Several fields in CV07_01 (`attributes.name`/`value`, `tags.label`, `references.reference`/`qualifier`) are genuinely repeatable — the same `{name, value}` or `{label, permission, active}` shape appears several times per payload, with different concrete values each time (e.g. `carrier_code`, `origin_location_code`, `destination_location_code`, `client`). Documenting this with one row per example (as CV07_01 does) works and nothing was lost on our side, but it's easier for everyone if the table describes the shape once and lists known values in a short table or bullet list underneath, rather than repeating the full row per example — especially as the number of known values grows.

## 6. Every field needs a real description

A blank or placeholder description means we have to come back and ask what the field actually means. A short, specific sentence is enough.

## 7. Finalize the endpoint URL before cutover

A "TBD" placeholder in the endpoint URL is fine for an early draft but needs to become a real, confirmed value before go-live — we'll flag it as an open item on every document until it's filled in.

## 8. Make sure the Type column (object vs. array) agrees with your own worked example

In CV07_01, the field-mapping table's Type column disagreed with the document's own JSON example for 9 of 25 nested fields — `consignor`/`customer`/`carrier`/`consignmentNote`/`documentProperties` are typed "array" in the table but shown as plain objects in the example, and `attributes`/`tags`/`items`/`handlingUnits` are typed "object" but shown as arrays. We treat the worked example as ground truth and corrected for this automatically, but it's exactly the kind of mismatch that would silently produce a broken integration if someone built against the table alone without checking the example.

## 9. Double-check the endpoint URL has no stray characters

CV07_01's endpoint URL currently contains a literal space (`.../api/v1/ tms-2-ship-orders/{orderId}`). A small thing, but it will break any client or server code generated directly from the document.

## 10. Keep the Rank column numerically consistent

The Rank column (0 = top-level object, 1/2/3/4 = nested depth) is how we reconstruct the full nested shape of the payload automatically. Please don't skip levels (e.g. jumping from Rank 1 straight to Rank 3) — if a new nesting level is needed, it should get its own Rank value one deeper than its parent.

## 11. Pick one authentication mechanism, not several marked "to be confirmed"

CV07_01's headers table lists `Authorization` twice — once marked flatly "Required," once marked "Optional / To be confirmed" — alongside a third candidate, `X-API-Key`, also "Optional / To be confirmed." That's a direct contradiction, not just an open question: we can't build a client or server against a document that simultaneously requires and doesn't require the same header. Please settle on one definitive authentication method before the headers table is considered final.

## 12. State your date/time format and timezone convention at least once

CV07_01 states its format ("ISO 8601 UTC, `YYYY-MM-DDThh:mm:ssZ`") only in a separate validation-rules table, not against each individual date/time field — which is fine, as long as it's stated somewhere. A document with date/time fields but no format or timezone convention stated anywhere leaves that detail to guesswork.

## 13. State the unit of measure for any numeric field representing a physical quantity

`grossWeight` (CV07_01) is described only as "Weight of the car" — the unit (kg) is inferable solely from the AndSoft source-column name `TMQTUNIT_KG`, not from anything a reader of the description itself can check. Any weight, volume, length, or similar numeric field should name its unit directly in the description.

## 14. Note directly against a field when a business rule makes it only conditionally required

BR-01 names nine specific fields that are "mandatory before the first PLN can be sent" — a genuinely conditional requirement, not a blanket one. When a business rule changes a field's cardinality like this, say so against the field's own row (not only in the separate business-rules table), so it isn't mistaken for a plain mandatory or optional field.

---

*This standard is generated from, and kept in sync with, the same automated checks (`scripts/lint_source_document.py`) run against every interface document on our side — so if the checks change, this document will be updated to match.*
