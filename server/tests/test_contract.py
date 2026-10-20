"""Check the machine contract and existing HTTP error shapes without a database."""
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.database import get_db
from app.http_contract import ValidationErrorResponse, HTTPErrorResponse
from app.main import app
from test_ingestion import asgi_call

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("oracle_codegen", ROOT / "tools/codegen/generate.py")
codegen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codegen)


class ContractTests(unittest.TestCase):
    def test_export_does_not_access_database_and_matches_snapshot(self):
        with patch("app.database.db_engine", side_effect=AssertionError("No database during export")):
            schema = codegen.export_contract()
        self.assertEqual(schema, json.loads((ROOT / "contracts/openapi.json").read_text()))

    def test_audit_rejects_missing_success_shapes_duplicate_ids_and_bad_refs(self):
        schema = app.openapi()
        operations = [op for methods in schema["paths"].values() for method, op in methods.items() if method in codegen.METHODS]
        self.assertEqual(len(operations), len({op["operationId"] for op in operations}))
        bad = deepcopy(schema)
        bad["paths"]["/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"] = {}
        with self.assertRaises(ValueError):
            codegen.audit_contract(bad)
        bad = deepcopy(schema)
        bad["paths"]["/health"]["get"]["operationId"] = "create_capture"
        with self.assertRaises(ValueError):
            codegen.audit_contract(bad)
        bad = deepcopy(schema)
        bad["components"]["schemas"]["Broken"] = {"$ref": "#/components/schemas/Missing"}
        with self.assertRaises(KeyError):
            codegen.audit_contract(bad)

    def test_setup_token_is_security_requirement_only_for_admin_operations(self):
        schema = app.openapi()
        for path, method in [("/api/v1/setup", "put"), ("/api/v1/bank/export", "get"), ("/api/v1/resources/{resource_id}", "delete")]:
            op = schema["paths"][path][method]
            self.assertEqual(op["security"], [{"SetupToken": []}])
            self.assertFalse(any(p.get("name") == "x-oracle-setup-token" for p in op.get("parameters", [])))
        self.assertNotIn("security", schema["paths"]["/api/v1/captures/ingest"]["post"])
        self.assertEqual(schema["components"]["securitySchemes"]["SetupToken"]["in"], "header")

    def test_validation_and_forbidden_responses_match_documented_models(self):
        app.dependency_overrides[get_db] = lambda: None
        try:
            status, body = asyncio.run(asgi_call("GET", "/api/v1/captures/not-a-uuid"))
            self.assertEqual(status, 422)
            ValidationErrorResponse.model_validate(body)
            with patch.dict("os.environ", {"ORACLE_SETUP_TOKEN": "test-token"}):
                status, body = asyncio.run(asgi_call("PUT", "/api/v1/setup", {}))
            self.assertEqual(status, 403)
            HTTPErrorResponse.model_validate(body)
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_empty_response_contracts_do_not_advertise_json(self):
        for methods in app.openapi()["paths"].values():
            for method, operation in methods.items():
                if method in codegen.METHODS and "204" in operation["responses"]:
                    self.assertNotIn("content", operation["responses"]["204"])
