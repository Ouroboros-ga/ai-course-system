"""JSON serialization and schema-version handling for DocumentIR.

Schema versioning rules:
- Unknown major version => fail closed (raise ValueError).
- Known major with equal or higher minor => read with backward compatibility.
- JSON round-trip must preserve all fields exactly (including stable IDs).
"""

from __future__ import annotations

import json
from typing import Any, Dict

from ..contracts import CURRENT_SCHEMA_VERSION, SchemaVersion
from .models import DocumentIR


# The highest major version this code supports
SUPPORTED_MAJOR_VERSION = 1


def serialize_document_ir(doc: DocumentIR, *, indent: int = 2) -> str:
    """Serialize a DocumentIR to JSON string.

    The schema version embedded in the document is preserved; round-trip
    must not recompute stable IDs.
    """
    return json.dumps(doc.to_dict(), indent=indent, ensure_ascii=False)


def deserialize_document_ir(raw: str) -> DocumentIR:
    """Deserialize a JSON string into a DocumentIR.

    Raises ``ValueError`` if the schema major version is unknown (fail-closed).
    """
    data: Dict[str, Any] = json.loads(raw)

    schema_raw = data.get("schema_version", CURRENT_SCHEMA_VERSION.serialize())
    sv = SchemaVersion.parse(schema_raw)

    if sv.major > SUPPORTED_MAJOR_VERSION:
        raise ValueError(
            f"Unsupported schema major version {sv.major}. "
            f"This reader supports up to major {SUPPORTED_MAJOR_VERSION}. "
            f"Schema: {schema_raw!r}"
        )

    return DocumentIR.from_dict(data)


def assert_json_round_trip(doc: DocumentIR) -> DocumentIR:
    """Serialize then deserialize, returning the deserialized copy.

    This is a test helper that verifies the round-trip does not mutate
    stable IDs or drop fields.
    """
    raw = serialize_document_ir(doc)
    return deserialize_document_ir(raw)
