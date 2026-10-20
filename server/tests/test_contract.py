"""Check the machine contract and existing HTTP error shapes without a database."""
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.database import get_db
from app.http_contract import ValidationErrorResponse
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

    def test_local_api_has_no_authentication_contract(self):
        schema = app.openapi()
        self.assertFalse(schema.get("security"))
        self.assertFalse(schema.get("components", {}).get("securitySchemes"))
        for methods in schema["paths"].values():
            for method, operation in methods.items():
                if method in codegen.METHODS:
                    self.assertFalse(operation.get("security"))
                    self.assertNotIn("403", operation["responses"])

    def test_local_setup_write_accepts_no_credentials(self):
        settings = {"database_configured": False,
                    "chat": {"configured": False, "model": None},
                    "embeddings": {"configured": False, "model": None}}
        with patch("app.setup.router.service.save_settings", return_value=settings) as save:
            status, body = asyncio.run(asgi_call("PUT", "/api/v1/setup", {}))
        self.assertEqual(status, 200)
        self.assertFalse(body["database_configured"])
        save.assert_called_once()

    def test_validation_response_matches_documented_model(self):
        app.dependency_overrides[get_db] = lambda: None
        try:
            status, body = asyncio.run(asgi_call("GET", "/api/v1/captures/not-a-uuid"))
            self.assertEqual(status, 422)
            ValidationErrorResponse.model_validate(body)
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_empty_response_contracts_do_not_advertise_json(self):
        for methods in app.openapi()["paths"].values():
            for method, operation in methods.items():
                if method in codegen.METHODS and "204" in operation["responses"]:
                    self.assertNotIn("content", operation["responses"]["204"])
