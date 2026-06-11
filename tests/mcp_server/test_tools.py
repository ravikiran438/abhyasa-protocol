# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Tests for the Abhyasa MCP server tool handlers.

Handlers are called directly with JSON payloads to verify the contract exposed
to an MCP client.
"""

from __future__ import annotations

import json

import pytest

from abhyasa.mcp_server.tools import (
    HANDLERS,
    TOOL_SCHEMAS,
    ToolInvocationError,
    handle_check_admissibility,
    handle_compute_safe_action,
    handle_run_custody_transfer,
    handle_validate_abhyasa_service_ref,
    handle_validate_custody_ack,
    handle_validate_obligation,
    list_tool_names,
)


def _corrective_obligation() -> dict:
    return {
        "obligation_id": "bu-1",
        "kind": "phala.belief_update",
        "target": "agent-b",
        "payload": {"weight_delta": -0.4, "weight_key": "routing.agent_b.preference"},
        "deadline_seconds": 86400,
        "max_retries": 6,
        "created_at": "2026-06-09T10:00:00+00:00",
    }


def _reinforcing_obligation() -> dict:
    o = _corrective_obligation()
    o["obligation_id"] = "bu-2"
    o["payload"]["weight_delta"] = 0.3
    return o


# ── Registry ─────────────────────────────────────────────────────────────────


def test_schemas_and_handlers_are_consistent():
    assert set(TOOL_SCHEMAS.keys()) == set(HANDLERS.keys())
    assert set(list_tool_names()) == set(HANDLERS.keys())


def test_schemas_have_required_shape():
    for name, schema in TOOL_SCHEMAS.items():
        assert "description" in schema, f"{name} missing description"
        assert "inputSchema" in schema, f"{name} missing inputSchema"
        assert schema["inputSchema"]["type"] == "object"


# ── validate_obligation ──────────────────────────────────────────────────────


def test_validate_obligation_happy_path():
    result = json.loads(
        handle_validate_obligation({"obligation": _corrective_obligation()})
    )
    assert result["ok"] is True


def test_validate_obligation_rejects_bad_deadline():
    payload = _corrective_obligation()
    payload["deadline_seconds"] = 0
    with pytest.raises(ToolInvocationError, match="invalid obligation"):
        handle_validate_obligation({"obligation": payload})


def test_validate_obligation_rejects_non_object():
    with pytest.raises(ToolInvocationError, match="expected object"):
        handle_validate_obligation({"obligation": "nope"})


# ── validate_custody_ack ─────────────────────────────────────────────────────


def test_validate_custody_ack_happy_path():
    ack = {
        "obligation_id": "bu-1",
        "target": "agent-b",
        "status": "applied",
        "acked_at": "2026-06-09T10:00:01+00:00",
    }
    assert json.loads(handle_validate_custody_ack({"ack": ack}))["ok"] is True


def test_validate_custody_ack_rejects_bad_status():
    ack = {
        "obligation_id": "bu-1",
        "target": "agent-b",
        "status": "lost",
        "acked_at": "2026-06-09T10:00:01+00:00",
    }
    with pytest.raises(ToolInvocationError, match="invalid ack"):
        handle_validate_custody_ack({"ack": ack})


# ── validate_abhyasa_service_ref ─────────────────────────────────────────────


def test_validate_service_ref_happy_path():
    ref = {
        "version": "1.0.0",
        "custody_ack_endpoint": "https://o/ack",
        "supported_kinds": [
            {
                "kind": "phala.belief_update",
                "obligation_endpoint": "https://b/belief_updates",
                "deadline_seconds": 86400,
                "backoff_cap_seconds": 3600,
                "max_retries": 48,
            }
        ],
    }
    assert json.loads(handle_validate_abhyasa_service_ref({"ref": ref}))["ok"] is True


# ── check_admissibility (AC-1) ───────────────────────────────────────────────


def test_check_admissibility_corrective_is_custody():
    result = json.loads(
        handle_check_admissibility({"obligation": _corrective_obligation()})
    )
    assert result["admissible"] is True
    assert result["carried"] == "custody"


def test_check_admissibility_reinforcing_is_best_effort():
    result = json.loads(
        handle_check_admissibility({"obligation": _reinforcing_obligation()})
    )
    assert result["admissible"] is False
    assert result["carried"] == "best_effort"


# ── compute_safe_action ──────────────────────────────────────────────────────


def test_compute_safe_action_for_corrective():
    result = json.loads(
        handle_compute_safe_action({"obligation": _corrective_obligation()})
    )
    assert result["ok"] is True
    assert result["safe_action"]["effect"] == "down_weight"
    assert result["safe_action"]["magnitude"] == 0.4


def test_compute_safe_action_fails_for_reinforcing():
    result = json.loads(
        handle_compute_safe_action({"obligation": _reinforcing_obligation()})
    )
    assert result["ok"] is False
    assert "not admissible" in result["error"]


# ── run_custody_transfer (deliver-or-report) ─────────────────────────────────


def test_run_custody_transfer_clean_channel_applies():
    result = json.loads(
        handle_run_custody_transfer({"obligation": _corrective_obligation()})
    )
    assert result["ok"] is True
    assert result["terminal"] == "applied"
    assert result["discharged"] is True


def test_run_custody_transfer_total_loss_escalates():
    result = json.loads(
        handle_run_custody_transfer(
            {
                "obligation": _corrective_obligation(),
                "channel": {"drop_prob": 1.0, "seed": 1},
            }
        )
    )
    assert result["terminal"] == "escalated"
    assert result["discharged"] is True
    assert len(result["escalations"]) == 1
    assert result["routing_weights"]["routing.agent_b.preference"] == -0.4


def test_run_custody_transfer_reinforcing_is_best_effort():
    result = json.loads(
        handle_run_custody_transfer(
            {
                "obligation": _reinforcing_obligation(),
                "channel": {"drop_prob": 1.0, "seed": 1},
            }
        )
    )
    assert result["terminal"] == "best_effort"
    assert result["escalations"] == []


def test_run_custody_transfer_rejects_bad_decision():
    with pytest.raises(ToolInvocationError, match="receiver_decision"):
        handle_run_custody_transfer(
            {"obligation": _corrective_obligation(), "receiver_decision": "lost"}
        )
