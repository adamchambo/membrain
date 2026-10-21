"""Check generated Python serialization without calling the server."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk/python"))
from membrain_sdk import ApiClient, Configuration
from membrain_sdk.api.captures_api import CapturesApi
from membrain_sdk.models.resource_patch import ResourcePatch
from membrain_sdk.models.validation_error_response import ValidationErrorResponse
from membrain_sdk.models.capture_receipt import CaptureReceipt
from membrain_sdk.models.quick_capture import QuickCapture
from urllib3.response import HTTPResponse

for raw in ({}, {"title": None}, {"note": None}, {"title": "Updated"}):
    assert ResourcePatch.from_dict(raw).to_dict() == raw
for raw in ({"detail": "Invalid profile"}, {"detail": [{"loc": ["body", 0], "msg": "Invalid", "type": "value_error"}]}):
    assert ValidationErrorResponse.from_dict(raw).to_dict() == raw
with ApiClient(Configuration(host="http://127.0.0.1:8000")) as client:
    assert client.configuration.auth_settings() == {}
    receipt = {"capture_id": "00000000-0000-0000-0000-000000000001",
               "conversation_id": "00000000-0000-0000-0000-000000000002",
               "processing_job_id": "00000000-0000-0000-0000-000000000003",
               "resource_ids": [], "saved": True, "message": "Saved"}
    requests = []
    def request(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return HTTPResponse(body=json.dumps(receipt).encode(), status=201,
                            headers={"Content-Type": "application/json"}, preload_content=False)
    client.rest_client.request = request
    result = CapturesApi(client).ingest_capture(QuickCapture(raw_text="Synthetic SDK smoke input"))
    assert isinstance(result, CaptureReceipt)
    assert str(result.capture_id) == receipt["capture_id"]
    assert requests[0][0] == "POST" and requests[0][1].endswith("/api/v1/captures/ingest")
    assert requests[0][2]["body"]["raw_text"] == "Synthetic SDK smoke input"
    assert client.sanitize_for_serialization(ResourcePatch(title=None)) == {"title": None}
print("Python SDK: imports, client construction, omitted/null PATCH fields, validation unions passed.")
