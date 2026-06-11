# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Custody state machine tests: AB-1, AB-2, AB-3, AB-4 (paper §4)."""

from __future__ import annotations

from abhyasa.custody import (
    Custodian,
    Hop,
    PrincipalState,
    Receiver,
    ScriptedChannel,
    TerminalState,
    exponential_backoff,
)
from abhyasa.custody.channel import LossyChannel, ChannelConfig
from abhyasa.types import CustodyStatus
from tests.conftest import corrective_phala, reinforcing_phala


def _custodian(registry, channel, principal_state=None):
    return Custodian(
        registry=registry,
        principal_state=principal_state or PrincipalState(),
        channel=channel,
    )


def test_ab1_clean_delivery_terminates_applied(registry):
    # AB-1: first round-trip succeeds -> applied, custody discharged.
    receiver = Receiver("agent-b")
    channel = ScriptedChannel([Hop(delivered=True)])
    out = _custodian(registry, channel).transfer(corrective_phala(), receiver)
    assert out.terminal is TerminalState.APPLIED
    assert out.attempts == 1
    assert out.ack.status is CustodyStatus.APPLIED


def test_ab2_retries_then_succeeds(registry):
    # AB-2: two drops, third hop delivers -> applied on attempt 3.
    receiver = Receiver("agent-b")
    channel = ScriptedChannel([Hop(delivered=False), Hop(delivered=False), Hop(delivered=True)])
    out = _custodian(registry, channel).transfer(corrective_phala(), receiver)
    assert out.terminal is TerminalState.APPLIED
    assert out.attempts == 3


def test_ab2_exponential_backoff_is_bounded():
    assert exponential_backoff(1, base=1.0, cap=3600.0) == 1.0
    assert exponential_backoff(2, base=1.0, cap=3600.0) == 2.0
    assert exponential_backoff(3, base=1.0, cap=3600.0) == 4.0
    assert exponential_backoff(40, base=1.0, cap=3600.0) == 3600.0  # capped


def test_ab3_duplicate_redelivery_applies_once(registry):
    # AB-3: duplicate hop calls receiver.deliver twice; effect applied once.
    receiver = Receiver("agent-b")
    channel = ScriptedChannel([Hop(delivered=True, duplicate=True)])
    out = _custodian(registry, channel).transfer(corrective_phala("bu-dup"), receiver)
    assert out.terminal is TerminalState.APPLIED
    assert receiver.applied_count("bu-dup") == 1  # effectively-once


def test_ab3_redelivery_after_ack_loss_applies_once(registry):
    # Apply succeeds but ack is lost; custodian retries; receiver re-acks
    # applied without reapplying.
    receiver = Receiver("agent-b")
    channel = ScriptedChannel([Hop(delivered=True, ack_lost=True), Hop(delivered=True)])
    out = _custodian(registry, channel).transfer(corrective_phala("bu-ackloss"), receiver)
    assert out.terminal is TerminalState.APPLIED
    assert out.attempts == 2
    assert receiver.applied_count("bu-ackloss") == 1


def test_ab4_total_loss_escalates_and_applies_safe_action(registry):
    # AB-4: channel always drops -> escalate; principal-side down-weight applied.
    principal_state = PrincipalState()
    receiver = Receiver("agent-b")
    channel = ScriptedChannel([])  # exhausted immediately -> every hop drops
    out = _custodian(registry, channel, principal_state).transfer(
        corrective_phala("bu-lost", delta=-0.4), receiver
    )
    assert out.terminal is TerminalState.ESCALATED
    assert out.escalation is not None
    assert out.escalation.type == "abhyasa.delivery_failed"
    # safe(O): principal-side routing weight decreased by |delta|.
    assert principal_state.routing_weights["routing.agent_b.preference"] == -0.4
    assert len(principal_state.escalations) == 1


def test_declined_is_a_delivered_outcome_not_escalation(registry):
    # A receiver that declines discharges custody; no escalation, no retry.
    principal_state = PrincipalState()
    receiver = Receiver("agent-b", lambda _o: CustodyStatus.DECLINED)
    channel = ScriptedChannel([Hop(delivered=True)])
    out = _custodian(registry, channel, principal_state).transfer(
        corrective_phala(), receiver
    )
    assert out.terminal is TerminalState.DECLINED
    assert principal_state.escalations == []


def test_persistent_defer_escalates(registry):
    # A receiver that always defers never discharges -> deadline -> escalate.
    principal_state = PrincipalState()
    receiver = Receiver("agent-b", lambda _o: CustodyStatus.DEFERRED)
    channel = LossyChannel(ChannelConfig())  # lossless, but receiver defers
    out = _custodian(registry, channel, principal_state).transfer(
        corrective_phala(), receiver
    )
    assert out.terminal is TerminalState.ESCALATED


def test_reinforcing_obligation_is_best_effort(registry):
    # DEL-5: inadmissible obligation -> best-effort, single attempt, no custody.
    principal_state = PrincipalState()
    receiver = Receiver("agent-b")
    channel = ScriptedChannel([Hop(delivered=False)])  # dropped, but no retry
    out = _custodian(registry, channel, principal_state).transfer(
        reinforcing_phala(), receiver
    )
    assert out.terminal is TerminalState.BEST_EFFORT
    assert out.attempts == 1
    assert principal_state.escalations == []  # no fail-safe on benign side
