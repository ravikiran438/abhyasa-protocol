# Copyright 2026 Ravi Kiran Kadaboina
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tool registrations for the Abhyasa MCP server.

Each tool wraps an Abhyasa primitive or framework operation. Structural
validators round-trip a JSON payload through the relevant Pydantic model.
Framework tools (check_admissibility, compute_safe_action, run_custody_transfer)
expose AC-1, safe(O), and the deliver-or-report guarantee to an MCP client. All
tools take and return JSON.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from abhyasa.bindings.a2a import A2AEndpoint, AbhyasaServiceRef
from abhyasa.custody.channel import ChannelConfig, LossyChannel
from abhyasa.custody.machine import Custodian
from abhyasa.custody.principal_state import PrincipalState
from abhyasa.custody.receiver import Receiver
from abhyasa.instantiations import default_registry
from abhyasa.types import CustodyAck, CustodyStatus, Obligation

# ─────────────────────────────────────────────────────────────────────────────
# Generic MCP glue — portable across sibling protocol repos.
# Keep these four symbols (ToolInvocationError, _parse, _ok, _fail) in sync
# by convention when copying to phala, acap, or sauvidya-pace.
# ─────────────────────────────────────────────────────────────────────────────


class ToolInvocationError(Exception):
    """Raised when a tool's handler rejects its input or runtime fails."""


def _parse(cls, payload: Any, label: str):
    try:
        return cls.model_validate(payload)
    except ValidationError as exc:
        raise ToolInvocationError(f"invalid {label}: {exc}") from exc


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps({"ok": True, **payload}, default=str, indent=2)


def _fail(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# Tool schemas (repo-specific; everything below this line is Abhyasa-only).
# ─────────────────────────────────────────────────────────────────────────────


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "validate_obligation": {
        "description": (
            "Validate the structural integrity of an Obligation. Enforces the "
            "type-level field bounds from paper §3/§4 (positive deadline, "
            "non-negative max_retries, non-empty ids)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"obligation": {"type": "object"}},
            "required": ["obligation"],
        },
    },
    "validate_custody_ack": {
        "description": (
            "Validate the structural integrity of a CustodyAck. Verifies the "
            "status is one of applied|declined|deferred (paper §4)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"ack": {"type": "object"}},
            "required": ["ack"],
        },
    },
    "validate_abhyasa_service_ref": {
        "description": (
            "Validate an AbhyasaServiceRef payload (the body of the "
            "AgentCard.capabilities.extensions[] entry whose URI equals "
            "ABHYASA_EXTENSION_URI). Verifies version, both endpoints, the "
            "deadline/retry profile, and supported_kinds."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"ref": {"type": "object"}},
            "required": ["ref"],
        },
    },
    "check_admissibility": {
        "description": (
            "AC-1: report whether an Obligation is Abhyasa-admissible under the "
            "default registry (Anumati + Phala). Admissible obligations are "
            "carried under custody; inadmissible ones (unknown kind, or a "
            "reinforcing Phala update) travel best-effort."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"obligation": {"type": "object"}},
            "required": ["obligation"],
        },
    },
    "compute_safe_action": {
        "description": (
            "Return safe(O) for an admissible Obligation: the principal-side "
            "default AB-4 would execute (fail_closed for Anumati, down_weight "
            "for corrective Phala). Fails for inadmissible obligations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"obligation": {"type": "object"}},
            "required": ["obligation"],
        },
    },
    "run_custody_transfer": {
        "description": (
            "Simulate a custody transfer of an Obligation over a lossy channel "
            "and report the terminal state (applied | declined | escalated | "
            "best_effort). Demonstrates the deliver-or-report guarantee: an "
            "admissible obligation never terminates in silent loss. Optional "
            "'channel' (drop_prob, duplicate_prob, ack_drop_prob, seed) and "
            "'receiver_decision' (applied|declined|deferred) shape the run."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "obligation": {"type": "object"},
                "channel": {
                    "type": "object",
                    "description": (
                        "Optional ChannelConfig: drop_prob, duplicate_prob, "
                        "ack_drop_prob (floats in [0,1]), seed (int)."
                    ),
                },
                "receiver_decision": {
                    "type": "string",
                    "enum": ["applied", "declined", "deferred"],
                    "description": "How the simulated receiver responds. Default applied.",
                },
            },
            "required": ["obligation"],
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Tool handlers.
# ─────────────────────────────────────────────────────────────────────────────


def _validate_primitive(cls, argument_key: str, arguments: dict[str, Any]) -> str:
    payload = arguments.get(argument_key)
    if not isinstance(payload, dict):
        raise ToolInvocationError(f"expected object under key {argument_key!r}")
    _parse(cls, payload, argument_key)
    return _ok({argument_key: "valid"})


def handle_validate_obligation(arguments: dict[str, Any]) -> str:
    return _validate_primitive(Obligation, "obligation", arguments)


def handle_validate_custody_ack(arguments: dict[str, Any]) -> str:
    return _validate_primitive(CustodyAck, "ack", arguments)


def handle_validate_abhyasa_service_ref(arguments: dict[str, Any]) -> str:
    return _validate_primitive(AbhyasaServiceRef, "ref", arguments)


def handle_check_admissibility(arguments: dict[str, Any]) -> str:
    obligation = _parse(Obligation, arguments.get("obligation"), "obligation")
    registry = default_registry()
    admissible = registry.is_admissible(obligation)
    return _ok(
        {
            "obligation_id": obligation.obligation_id,
            "kind": obligation.kind,
            "admissible": admissible,
            "carried": "custody" if admissible else "best_effort",
        }
    )


def handle_compute_safe_action(arguments: dict[str, Any]) -> str:
    obligation = _parse(Obligation, arguments.get("obligation"), "obligation")
    registry = default_registry()
    if not registry.is_admissible(obligation):
        return _fail(
            f"obligation {obligation.obligation_id!r} is not admissible (AC-1); "
            "safe(O) is undefined for the best-effort side."
        )
    action = registry.safe(obligation)
    return _ok({"safe_action": action.model_dump()})


def handle_run_custody_transfer(arguments: dict[str, Any]) -> str:
    obligation = _parse(Obligation, arguments.get("obligation"), "obligation")

    channel_args = arguments.get("channel") or {}
    if not isinstance(channel_args, dict):
        raise ToolInvocationError("'channel' must be an object")
    try:
        config = ChannelConfig(
            drop_prob=float(channel_args.get("drop_prob", 0.0)),
            duplicate_prob=float(channel_args.get("duplicate_prob", 0.0)),
            ack_drop_prob=float(channel_args.get("ack_drop_prob", 0.0)),
            seed=channel_args.get("seed"),
        )
    except (TypeError, ValueError) as exc:
        raise ToolInvocationError(f"invalid channel config: {exc}") from exc

    decision_raw = arguments.get("receiver_decision", "applied")
    try:
        decision = CustodyStatus(decision_raw)
    except ValueError as exc:
        raise ToolInvocationError(
            f"receiver_decision must be applied|declined|deferred, got "
            f"{decision_raw!r}"
        ) from exc

    registry = default_registry()
    principal_state = PrincipalState()
    receiver = Receiver(obligation.target, lambda _o: decision)
    endpoint = A2AEndpoint(receiver)
    custodian = Custodian(
        registry=registry,
        principal_state=principal_state,
        channel=LossyChannel(config),
    )
    outcome = custodian.transfer(obligation, endpoint)
    return _ok(
        {
            "terminal": outcome.terminal.value,
            "attempts": outcome.attempts,
            "discharged": outcome.discharged,
            "escalations": principal_state.escalations,
            "routing_weights": principal_state.routing_weights,
            "authorizations": principal_state.authorizations,
        }
    )


HANDLERS: dict[str, Any] = {
    "validate_obligation": handle_validate_obligation,
    "validate_custody_ack": handle_validate_custody_ack,
    "validate_abhyasa_service_ref": handle_validate_abhyasa_service_ref,
    "check_admissibility": handle_check_admissibility,
    "compute_safe_action": handle_compute_safe_action,
    "run_custody_transfer": handle_run_custody_transfer,
}


def list_tool_names() -> list[str]:
    return list(TOOL_SCHEMAS.keys())
