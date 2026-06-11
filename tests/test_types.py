# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Structural type tests for the Abhyasa primitives."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from abhyasa.types import (
    CustodyAck,
    CustodyStatus,
    Obligation,
    SafeAction,
    SafeEffect,
)


def test_obligation_round_trips():
    o = Obligation(
        obligation_id="o-1",
        kind="phala.belief_update",
        target="agent-b",
        payload={"weight_delta": -0.4},
        deadline_seconds=86400,
        max_retries=6,
        created_at="2026-06-09T10:00:00+00:00",
    )
    assert Obligation.model_validate_json(o.model_dump_json()) == o


def test_obligation_rejects_nonpositive_deadline():
    with pytest.raises(ValidationError):
        Obligation(
            obligation_id="o-1",
            kind="anumati.consent",
            target="agent-c",
            deadline_seconds=0,  # must be > 0
            max_retries=1,
            created_at="2026-06-09T10:00:00+00:00",
        )


def test_obligation_rejects_negative_retries():
    with pytest.raises(ValidationError):
        Obligation(
            obligation_id="o-1",
            kind="anumati.consent",
            target="agent-c",
            deadline_seconds=10,
            max_retries=-1,  # must be >= 0
            created_at="2026-06-09T10:00:00+00:00",
        )


def test_custody_ack_status_enum():
    ack = CustodyAck(
        obligation_id="o-1",
        target="agent-b",
        status="applied",
        acked_at="2026-06-09T10:00:01+00:00",
    )
    assert ack.status is CustodyStatus.APPLIED


def test_custody_ack_rejects_unknown_status():
    with pytest.raises(ValidationError):
        CustodyAck(
            obligation_id="o-1",
            target="agent-b",
            status="lost",  # not in applied|declined|deferred
            acked_at="2026-06-09T10:00:01+00:00",
        )


def test_safe_action_down_weight_shape():
    a = SafeAction(
        obligation_id="o-1",
        target="agent-b",
        effect=SafeEffect.DOWN_WEIGHT,
        magnitude=0.4,
        weight_key="routing.agent_b.preference",
        rationale="test",
    )
    assert a.effect is SafeEffect.DOWN_WEIGHT
    assert a.magnitude == 0.4


def test_safe_action_rejects_negative_magnitude():
    with pytest.raises(ValidationError):
        SafeAction(
            obligation_id="o-1",
            target="agent-b",
            effect=SafeEffect.DOWN_WEIGHT,
            magnitude=-0.1,  # must be >= 0
            rationale="test",
        )
