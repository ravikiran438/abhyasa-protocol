# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""A2A binding tests: AgentCard discoverability + wire round-trip (paper §4, §5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from abhyasa.bindings.a2a import (
    ABHYASA_EXTENSION_URI,
    A2AEndpoint,
    AbhyasaServiceRef,
    KindProfile,
    build_agent_card_extension,
    parse_agent_card_extension,
)
from abhyasa.custody import (
    Custodian,
    PrincipalState,
    Receiver,
    TerminalState,
)
from abhyasa.custody.channel import ChannelConfig, LossyChannel
from tests.conftest import corrective_phala


def _service_ref() -> AbhyasaServiceRef:
    return AbhyasaServiceRef(
        version="1.0.0",
        custody_ack_endpoint="https://orch.example.com/abhyasa/custody_ack",
        supported_kinds=[
            KindProfile(
                kind="phala.belief_update",
                obligation_endpoint="https://agent-b.example.com/phala/belief_updates",
                deadline_seconds=86400,
                backoff_cap_seconds=3600,
                max_retries=48,
            ),
            KindProfile(
                kind="anumati.consent",
                obligation_endpoint="https://agent-b.example.com/anumati/decisions",
                deadline_seconds=3600,
                backoff_cap_seconds=600,
                max_retries=16,
            ),
        ],
    )


def test_agent_card_extension_round_trips():
    ref = _service_ref()
    ext = build_agent_card_extension(ref)
    assert ext["uri"] == ABHYASA_EXTENSION_URI
    parsed = parse_agent_card_extension([{"uri": "other"}, ext])
    assert parsed == ref


def test_parse_returns_none_when_absent():
    assert parse_agent_card_extension([{"uri": "https://example/other"}]) is None


def test_service_ref_requires_supported_kinds():
    with pytest.raises(ValidationError):
        AbhyasaServiceRef(
            version="1.0.0",
            custody_ack_endpoint="https://x/ack",
            supported_kinds=[],  # min_length=1
        )


def test_kind_profile_rejects_incoherent_retry_budget():
    # AB-2: max_retries must let the capped backoff span the deadline. The
    # classic bad profile (max_retries=6, 24 h deadline) must be rejected.
    with pytest.raises(ValidationError, match="span the deadline"):
        KindProfile(
            kind="phala.belief_update",
            obligation_endpoint="https://x/belief_updates",
            deadline_seconds=86400,
            backoff_cap_seconds=3600,
            max_retries=6,
        )


def test_kind_profile_accepts_coherent_retry_budget():
    p = KindProfile(
        kind="phala.belief_update",
        obligation_endpoint="https://x/belief_updates",
        deadline_seconds=86400,
        backoff_cap_seconds=3600,
        max_retries=48,
    )
    assert p.kind == "phala.belief_update"


def test_a2a_endpoint_drives_custody_over_lossy_channel(registry):
    # The same Custodian works against an A2A endpoint (JSON wire round-trip)
    # exactly as over an in-process Receiver.
    receiver = Receiver("agent-b")
    endpoint = A2AEndpoint(receiver)
    principal_state = PrincipalState()
    custodian = Custodian(
        registry=registry,
        principal_state=principal_state,
        channel=LossyChannel(ChannelConfig(duplicate_prob=0.5, seed=3)),
    )
    out = custodian.transfer(corrective_phala("bu-a2a"), endpoint)
    assert out.terminal is TerminalState.APPLIED
    assert receiver.applied_count("bu-a2a") == 1


def test_a2a_post_obligation_returns_200_and_ack_json():
    endpoint = A2AEndpoint(Receiver("agent-b"))
    status, ack_json = endpoint.post_obligation(corrective_phala("bu-post"))
    assert status == 200
    assert '"status":"applied"' in ack_json.replace(" ", "")
