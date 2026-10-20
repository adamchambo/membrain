# API contract and client generation

The source of truth is FastAPI's routes and Pydantic request/response models.
`contracts/openapi.json` is a checked-in snapshot, not a separately maintained API.
Generated Python, Swift 6, and TypeScript Fetch packages live under `sdk/`.
They include wire types, serialization, and HTTP operations. Keep connection
settings, user-facing errors, polling, navigation, and other client-specific
abstractions outside those directories.

## Install the generator

From the repository root, using the backend Python 3.12 virtual environment:

```sh
.venv/bin/python -m pip install -r tools/codegen/requirements.txt
```

OpenAPI Generator is pinned to 7.26.0 and its private Java runtime to
`jdk4py==25.0.2.1`. A system Java installation is not needed. Initial installation
requires internet access; generation itself runs locally. Server dependencies
must also be installed (`.venv/bin/python -m pip install -e server`).

## Regenerate or check

```sh
.venv/bin/python tools/codegen/generate.py
.venv/bin/python tools/codegen/generate.py check
.venv/bin/python tools/codegen/generate.py generate --target python
.venv/bin/python tools/codegen/generate.py export
```

- `generate` (default) exports and audits the contract, validates it with the
  generator, and regenerates all three SDKs. All selected SDKs must generate
  successfully before tracked output is replaced.
- `check` regenerates into a temporary directory and fails on schema or SDK drift;
  it does not update tracked output.
- `export` writes only the schema snapshot; it does not need the generator.
- `--target` selects `python`, `swift`, `typescript`, or `all` (default).
- `--generator PATH` selects an installed generator executable; its version is
  still checked against the pin.

Export imports the FastAPI application without starting an HTTP server, connecting
to PostgreSQL, reading bank data, or invoking AI. No running server is required.
Operation IDs are endpoint function names, checked for uniqueness: treat renaming
one as an SDK API change. Regeneration updates code; it does not make an older
installed client automatically compatible with a breaking server change.

The `sdk/<language>/` directories are fully managed. A marker prevents replacing
an unrelated folder, but don't put handwritten files there. Local build artifacts
are ignored by drift comparisons. Review generated diffs when changing the API.

## Verify generated clients

Python requires 3.10+ (the server environment uses 3.12). The live CLI also requires Python 3.10+ and uses this generated SDK;
its explicit stub mode shares that runtime.

```sh
.venv/bin/python -m pip install ./sdk/python
.venv/bin/python tools/codegen/smoke_python.py
npm ci --ignore-scripts --prefix tools/codegen
tools/codegen/node_modules/.bin/tsc -p sdk/typescript/tsconfig.json
tools/codegen/node_modules/.bin/tsc -p sdk/typescript/tsconfig.esm.json
node tools/codegen/smoke_typescript.cjs
swift run --package-path tools/codegen/swift-smoke
```

The TypeScript build emits JavaScript and declarations. Swift is a local SwiftPM
package with URLSession and async/await APIs; use a Swift 6+ toolchain. On this Mac,
select full Xcode using `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`
if Command Line Tools and SDK versions do not match.

Smoke checks exercise SDK imports/client construction, omitted versus explicit
null PATCH values, and both forms of validation errors (including mixed string /
integer locations). They do not contact the server. Backend HTTP regression tests
separately verify responses using disposable PostgreSQL databases.

`.github/workflows/sdk-contract.yml` runs drift, contract, and serialization checks
for relevant changes; the Swift smoke executable also compiles the entire SDK.
The workflow has been added locally; no hosted CI run is claimed.

## Generator compatibility fixes

Templates in `templates/` are derived from OpenAPI Generator 7.26.0 (Apache 2.0;
see `templates/LICENSE`). They are inputs to generation, not edits to SDK output:

- Python's model template preserves missing fields in `from_dict` so an omitted
  PATCH field doesn't become an explicit null.
- Python union templates recursively deserialize/serialize model-array alternatives.
- Swift's model template defaults explicit-null request wrappers to `.encodeNothing`.
  `ResourcePatch` marks its nullable title/note fields for these wrappers:
  `.encodeNothing` leaves unchanged, `.encodeNull` clears, and `.encodeValue(value)`
  sets the supplied value. These wrappers are intended for outgoing request bodies.

Validation's two disjoint unions use `oneOf`: strings versus integers in a location,
and strings versus arrays in error detail. This is semantically equivalent to
`anyOf` for these non-overlapping alternatives and generates real Swift/TS union
models rather than empty objects. Nullable fields retain their original semantics.
Rerun the smoke checks whenever upgrading the pinned generator/templates.
