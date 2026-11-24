# Document quality report - CV07_02_TMS_2_SHIP_EVENTS.docx

Checks the vendor document's own internal consistency and completeness - distinct from REVIEW_REPORT.md, which only flags fields with no source-column mapping. Every rule here is also written up, in plain language, in VENDOR_DOCUMENTATION_STANDARD.md - the two are kept in lockstep on purpose.

**3 blocking · 7 advisory · 0 informational**

## Blocking - resolve before this interface is built against (3)

- **[completeness-source-mapping]** `events[].technicalReference` — 'technicalReference' has neither a Field-AndSoft source column value nor a 'Fixed value:' note - genuinely unmapped, needs an answer from Andsoft before this field can be built against.
- **[completeness-source-mapping]** `events[].items[].reference` — 'reference' has neither a Field-AndSoft source column value nor a 'Fixed value:' note - genuinely unmapped, needs an answer from Andsoft before this field can be built against.
- **[completeness-auth-method]** `(endpoint headers)` — The headers table lists more than one candidate authentication mechanism, with conflicting or unresolved requirement status: `Authorization` (required: Required. Token obtained from prior Shippeo OAuth2 token endpoint.); `X-API-Key` (optional: Optional / To be confirmed if required by gateway infrastructure alongside Bearer.). The actual authentication method for this interface isn't decided; confirm one, definitive method with Andsoft before cutover.

## Advisory - likely fine, worth a second look (7)

- **[naming-camelcase]** `events[].eventCode / eventName` — 'eventCode / eventName' doesn't follow the document's own stated camelCase convention (Section 2.2) for JSON field names.
- **[naming-camelcase]** `events[].eventDateTime / eventDate` — 'eventDateTime / eventDate' doesn't follow the document's own stated camelCase convention (Section 2.2) for JSON field names.
- **[naming-camelcase]** `events[].eventSource / triggerSource` — 'eventSource / triggerSource' doesn't follow the document's own stated camelCase convention (Section 2.2) for JSON field names.
- **[naming-camelcase]** `events[].location.identifier / externalId` — 'identifier / externalId' doesn't follow the document's own stated camelCase convention (Section 2.2) for JSON field names.
- **[naming-camelcase]** `events[].location.zip / zipCode` — 'zip / zipCode' doesn't follow the document's own stated camelCase convention (Section 2.2) for JSON field names.
- **[naming-camelcase]** `events[].location.latitude / longitude` — 'latitude / longitude' doesn't follow the document's own stated camelCase convention (Section 2.2) for JSON field names.
- **[completeness-no-json-example]** `(document)` — No parseable worked JSON example found in the document - container object/array typing could only be checked against the Type column, which is known to be unreliable on its own (see the next check when an example IS present). Ask Andsoft to include one.

## Informational - judgement calls to confirm, not necessarily problems (0)

None.

