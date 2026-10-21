"""Export, audit, and regenerate SDKs from the FastAPI contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = "7.26.0"
TARGETS = {"python": "python", "swift": "swift6", "typescript": "typescript-fetch"}
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def export_contract() -> dict:
    """Import server definitions without starting a server or accessing a database."""
    sys.path.insert(0, str(ROOT / "server"))
    from app.main import app
    schema = app.openapi()
    audit_contract(schema)
    return schema


def audit_contract(schema: dict) -> None:
    """Reject ambiguous operation IDs and untyped success responses."""
    ids = set()
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method not in METHODS:
                continue
            name = operation.get("operationId")
            if not name or name in ids:
                raise ValueError(f"Missing or duplicate operation ID: {method} {path}")
            ids.add(name)
            for status, response in operation["responses"].items():
                if status.startswith("2") and status != "204":
                    body = response.get("content", {}).get("application/json", {}).get("schema")
                    if not body:
                        raise ValueError(f"Untyped success response: {method} {path} {status}")
    # Every local reference must resolve before any output is replaced.
    def walk(value):
        if isinstance(value, dict):
            ref = value.get("$ref", "")
            if ref.startswith("#/"):
                node = schema
                for part in ref[2:].split("/"):
                    node = node[part.replace("~1", "/").replace("~0", "~")]
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(schema)


def snapshot(directory: Path) -> dict[str, bytes]:
    """Read managed files for a deterministic comparison; omit local build caches."""
    ignored = {".build", "node_modules", "dist", "__pycache__", ".pytest_cache", ".venv", "build", ".swiftpm"}
    return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*")
            if p.is_file() and not ignored.intersection(p.relative_to(directory).parts)
            and not any(part.endswith(".egg-info") for part in p.relative_to(directory).parts)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "generate", "check"], nargs="?", default="generate",
                        help="export schema only; generate schema and SDKs; check without writing tracked output")
    parser.add_argument("--target", choices=["all", *TARGETS], default="all", help="SDK language to generate or check")
    parser.add_argument("--generator", help="Path to the pinned openapi-generator-cli executable")
    args = parser.parse_args()
    schema = export_contract()
    encoded = (json.dumps(schema, indent=2, sort_keys=True) + "\n").encode()
    contract = ROOT / "contracts/openapi.json"
    if args.action == "export":
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_bytes(encoded)
        print(f"Exported {contract}")
        return
    executable = args.generator or str(Path(sys.executable).parent / "openapi-generator-cli")
    if not Path(executable).is_file():
        executable = shutil.which(executable) or executable
    try:
        version = subprocess.check_output([executable, "version"], text=True).strip()
    except FileNotFoundError:
        parser.error("Generator not installed; install tools/codegen/requirements.txt or pass --generator PATH")
    if version != VERSION:
        raise SystemExit(f"Expected OpenAPI Generator {VERSION}; found {version}")
    targets = TARGETS if args.target == "all" else {args.target: TARGETS[args.target]}
    with tempfile.TemporaryDirectory(prefix="membrain-codegen-") as temporary:
        temp = Path(temporary)
        spec = temp / "openapi.json"
        spec.write_bytes(encoded)
        # Generate every selected SDK successfully before modifying tracked output.
        subprocess.run([executable, "validate", "-i", str(spec)], check=True)
        for name, generator in targets.items():
            log = temp / f"{name}.log"
            command = [executable, "generate", "-i", str(spec), "-g", generator,
                       "-c", str(ROOT / f"tools/codegen/{name}.json"), "-o", str(temp / name),
                       "--global-property", "apiTests=false,modelTests=false,apiDocs=false,modelDocs=false"]
            templates = ROOT / "tools/codegen/templates" / name
            if templates.exists():
                command.extend(["-t", str(templates)])
            with log.open("w") as stream:
                result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
            if result.returncode:
                raise SystemExit(log.read_text())
            # Normalize generator README line endings/whitespace for clean source diffs.
            readme = temp / name / "README.md"
            if readme.exists():
                readme.write_text("\n".join(line.rstrip() for line in readme.read_text().splitlines()) + "\n")
            # This generator manifest embeds temporary paths; it is not SDK source.
            manifest = temp / name / ".openapi-generator/FILES"
            if manifest.exists():
                manifest.unlink()
            (temp / name / ".membrain-generated").write_text(f"OpenAPI Generator {VERSION}\n")
            print(f"Generated {name}")
        if args.action == "check":
            failures = []
            if not contract.exists() or contract.read_bytes() != encoded:
                failures.append("contracts/openapi.json")
            for name in targets:
                expected = snapshot(temp / name)
                actual = snapshot(ROOT / "sdk" / name)
                changed = sorted(key for key in expected.keys() | actual.keys() if expected.get(key) != actual.get(key))
                if changed:
                    failures.append(f"sdk/{name}: " + ", ".join(changed[:10]))
            if failures:
                raise SystemExit("Generated output is stale:\n" + "\n".join(failures))
            print("Contract and selected SDKs are current.")
            return
        for name in targets:
            destination = ROOT / "sdk" / name
            if destination.exists() and not (destination / ".membrain-generated").exists():
                raise SystemExit(f"Refusing to replace unmanaged directory: {destination}")
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_bytes(encoded)
        for name in targets:
            destination = ROOT / "sdk" / name
            if destination.exists():
                shutil.rmtree(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(temp / name, destination)
        print("Updated contract and selected SDKs. Keep handwritten adapters outside sdk/.")


if __name__ == "__main__":
    main()
