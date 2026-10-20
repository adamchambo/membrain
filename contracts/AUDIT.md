# API contract audit — 2026-10-20

Scope: 63 operations across 51 paths. Routes and Pydantic models remain the source
of truth; `openapi.json` is exported from the app with no live database or AI calls.

## Findings and resolutions

- **11 untyped success responses:** added named response models for resource and
  conversation lists, relationship archiving, subject creation/listing/membership/
  resolved scope, review history/session detail, reflection, and concept maps.
  The existing bodies and HTTP status codes remain; map responses continue to omit
  absent positions rather than introducing null fields.
- **Undocumented business errors:** documented `{code, detail}` for 404, 409, and
  503 and both string/list 422 envelopes.
  Runtime error handlers have not been replaced.
- **Generated operation names tied to URLs:** use unique endpoint names for stable
  SDK methods. Names are now contract identifiers; changing one changes the SDK.
- **Local authentication scope:** client authentication is not part of the current
  local installation. Removed the setup-token checks, security scheme and token-only
  403 response. LLM provider keys remain separate in server application settings;
  deletion retains archive and reference checks.
- **Flexible payloads:** proposal payloads, job results, legacy review feedback,
  learning provenance inputs, and portable table records remain explicitly
  documented JSON envelopes. Generated SDKs type their enclosing structures but
  cannot infer every versioned key inside those envelopes. Portable imports retain
  the existing service's detailed validation and limits.
- **Generator serialization defects:** pinned template overrides preserve Python
  omitted/null fields and model arrays inside unions; Swift nullable PATCH fields
  use explicit omission/null/value wrappers. Disjoint validation alternatives use
  `oneOf` so Swift and TypeScript generate real union types. See the tooling README.

## Verification

- Schema validation and local reference/operation/success-response audit.
- Drift check regenerates all three SDKs and compares exact managed file contents.
- Contract tests verify snapshot equality, no database access during export, absence
  of client-authentication metadata, setup without credentials, actual 422 envelopes,
  and bodyless 204 responses.
- Backend regression suite runs only against disposable PostgreSQL databases.
- Generated SDK smoke checks cover construction, validation unions and PATCH null
  semantics; Python additionally sends a request through a fake HTTP transport and
  decodes the typed receipt. Swift smoke compilation includes the full SDK.

These checks validate contract/code-generation mechanics, not live model quality
or every endpoint through every generated transport. The CLI now has a live Python SDK adapter and a separate explicit stub mode.
CLI journeys are covered by unit tests and disposable database/worker tests.

Some proposed CLI interactions still need client orchestration: processing work is
currently retrieved by ID rather than a global job-list endpoint, and learning
suggestions require an explicit concept scope. Generation does not add those APIs.
