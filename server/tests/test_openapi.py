"""The committed OpenAPI document (source of web/src/api/schema.d.ts) matches the service."""
from server import export_openapi


def test_committed_openapi_is_current():
    with open(export_openapi.TARGET, encoding="utf-8") as f:
        assert f.read() == export_openapi.document(), "run: python -m server.export_openapi, then npm run api:types in web/"


def test_every_operation_has_a_name_and_typed_responses():
    import json
    doc = json.loads(export_openapi.document())
    for path, ops in doc["paths"].items():
        for method, op in ops.items():
            assert op["operationId"] and "200" in op["responses"] or "202" in op["responses"], (method, path)
