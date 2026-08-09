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
from tests.conftest import anumati_consent, corrective_phala, reinforcing_phala


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


def test_declined_applies_safe_action_without_escalation(registry):
    # Paper v1.1: a decline discharges delivery, not protection. safe(O)
    # applies on the principal side, but no escalation is emitted -- the
    # decline itself is the accountable record.
    principal_state = PrincipalState()
    receiver = Receiver("agent-b", lambda _o: CustodyStatus.DECLINED)
    channel = ScriptedChannel([Hop(delivered=True)])
    out = _custodian(registry, channel, principal_state).transfer(
        corrective_phala("bu-declined", delta=-0.4), receiver
    )
    assert out.terminal is TerminalState.DECLINED
    # safe(O): principal-side routing weight decreased, as on AB-4.
    assert principal_state.routing_weights["routing.agent_b.preference"] == -0.4
    # But unlike AB-4, no escalation: the outcome is delivered and logged.
    assert principal_state.escalations == []


def test_receiver_declines_expired_obligation(registry):
    # Paper v1.1: deadlines bind both sides. A receiver holding a deferred
    # obligation past its deadline declines it (expiry as the reason) instead
    # of applying late, after the custodian has escalated and run safe(O).
    from abhyasa.custody import Clock

    clock = Clock()
    receiver = Receiver(
        "agent-b", lambda _o: CustodyStatus.DEFERRED, clock=clock
    )
    obligation = corrective_phala("bu-late")
    ack = receiver.deliver(obligation)
    assert ack.status is CustodyStatus.DEFERRED
    clock.advance(obligation.deadline_seconds + 1)
    late = receiver.deliver(obligation)
    assert late.status is CustodyStatus.DECLINED
    assert receiver.applied_count("bu-late") == 0  # never applied late


def test_persistent_defer_escalates(registry):
    # A receiver that always defers never discharges -> deadline -> escalate.
    principal_state = PrincipalState()
    receiver = Receiver("agent-b", lambda _o: CustodyStatus.DEFERRED)
    channel = LossyChannel(ChannelConfig())  # lossless, but receiver defers
    out = _custodian(registry, channel, principal_state).transfer(
        corrective_phala(), receiver
    )
    assert out.terminal is TerminalState.ESCALATED


def test_superseded_safe_action_does_not_regress_newer_decision(registry):
    # Paper v1.1 (supersession guard): a revocation issued at sequence 1
    # times out AFTER the principal has re-granted the same scope at
    # sequence 2. safe(O1) must apply nothing -- last-writer-wins per key --
    # while the escalation still reports the loss (deliver-or-report).
    principal_state = PrincipalState()
    scope = "calendar.write"
    revocation = anumati_consent("cn-old").model_copy(update={"sequence": 1})
    principal_state.apply_decision(scope, False, 1)  # withhold at issue time
    principal_state.apply_decision(scope, True, 2)   # later re-grant
    receiver = Receiver("agent-c")
    channel = ScriptedChannel([])  # total loss -> deadline -> AB-4
    out = _custodian(registry, channel, principal_state).transfer(
        revocation, receiver
    )
    assert out.terminal is TerminalState.ESCALATED
    assert len(principal_state.escalations) == 1  # loss still reported
    assert principal_state.authorizations[scope] is True  # no regression


def test_unsuperseded_safe_action_still_applies(registry):
    # Without a newer decision on the key, the guarded fail-safe applies
    # normally: the withhold lands and the escalation fires.
    principal_state = PrincipalState()
    scope = "calendar.write"
    revocation = anumati_consent("cn-cur").model_copy(update={"sequence": 3})
    channel = ScriptedChannel([])
    out = _custodian(registry, channel, principal_state).transfer(
        revocation, Receiver("agent-c")
    )
    assert out.terminal is TerminalState.ESCALATED
    assert principal_state.authorizations[scope] is False
    assert principal_state.applied_sequences[scope] == 3


def test_stale_decision_cannot_overwrite_newer_one():
    # The principal's own decision path passes through the same guard, so
    # ordering is total per key no matter which path applies first.
    principal_state = PrincipalState()
    principal_state.apply_decision("s", True, 5)
    principal_state.apply_decision("s", False, 4)  # stale; must not apply
    assert principal_state.authorizations["s"] is True


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
