# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Lock-in tests for Abhyasa's published extension URI and manifest."""

from __future__ import annotations

import json
from pathlib import Path

from abhyasa.bindings.a2a import ABHYASA_EXTENSION_URI, AbhyasaServiceRef

MANIFEST = Path(__file__).resolve().parents[1] / "v1" / "manifest.json"


def test_abhyasa_extension_uri():
    assert ABHYASA_EXTENSION_URI == (
        "https://ravikiran438.github.io/abhyasa-protocol/v1"
    )


def test_manifest_uri_matches_constant():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["extension"]["uri"] == ABHYASA_EXTENSION_URI


def test_manifest_payload_schema_matches_service_ref():
    # The discoverability manifest must publish exactly the AbhyasaServiceRef
    # schema callers will validate against.
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["agent_card_payload_schema"] == AbhyasaServiceRef.model_json_schema()
