# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Crash-recovery conformance tests for the durability requirements of
AB-1/AB-2 (custodian write-ahead pending set) and AB-3 (receiver applied-id
ledger committed atomically with the effect). Paper §4, §4.2.

A "crash" is a CrashSignal raised mid-protocol; "restart" is rebuilding the
node from its durable store. Three scenarios:

  1. Custodian dies mid-retry  -> recovery resumes the transfer to APPLIED.
  2. Receiver dies between application and acknowledgment -> redelivery after
     restart re-acks applied WITHOUT reapplying (effectively-once across the
     crash).
  3. Custodian recovers into a still-dead channel -> the transfer terminates
     ESCALATED with the principal-side fail-safe applied (deliver-or-report
     holds across the crash).
"""

from __future__ import annotations

import pytest

from abhyasa.custody import Custodian, Hop, PrincipalState, ScriptedChannel, TerminalState
from abhyasa.custody.durable import (
    CrashSignal,
    CustodianStore,
    DurableCustodian,
    DurableReceiver,
    ReceiverStore,
)
from tests.conftest import corrective_phala

WEIGHT_KEY = "routing.agent_b.preference"


class CrashingChannel:
    """Wraps a channel; the process dies on the Nth round trip (1-based)."""

    def __init__(self, inner, crash_on_attempt: int) -> None:
        self._inner = inner
        self._crash_on = crash_on_attempt
        self._attempt = 0

    def round_trip(self, obligation, endpoint):
        self._attempt += 1
        if self._attempt == self._crash_on:
            raise CrashSignal("custodian process died mid-retry")
        return self._inner.round_trip(obligation, endpoint)


class CrashAfterApply:
    """Endpoint wrapper: the receiver applies (and durably commits), then the
    process dies before the acknowledgment is returned."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def deliver(self, obligation):
        self._inner.deliver(obligation)  # effect + ledger committed here
        raise CrashSignal("receiver process died before acking")


def _durable_custodian(registry, channel, store, principal_state=None):
    return DurableCustodian(
        custodian=Custodian(
            registry=registry,
            principal_state=principal_state or PrincipalState(),
            channel=channel,
        ),
        store=store,
    )


def test_custodian_crash_mid_retry_recovers_to_applied(registry, tmp_path):
    """AB-1/AB-2: a custodian killed mid-retry finds the obligation pending
    on restart and drives it to a terminal state."""
    store = CustodianStore(tmp_path / "custodian.json")
    rstore = ReceiverStore(tmp_path / "receiver.json")
    receiver = DurableReceiver("agent-b", store=rstore)
    obligation = corrective_phala("bu-crash-1")

    # First incarnation: two drops, then the process dies on attempt 3.
    channel = CrashingChannel(
        ScriptedChannel([Hop(delivered=False), Hop(delivered=False)]),
        crash_on_attempt=3,
    )
    with pytest.raises(CrashSignal):
        _durable_custodian(registry, channel, store).transfer(obligation, receiver)

    # The write-ahead record survived the crash.
    assert [o.obligation_id for o in store.pending()] == ["bu-crash-1"]

    # Restart: fresh custodian over a healed channel; recovery resumes.
    outcomes = _durable_custodian(
        registry, ScriptedChannel([Hop(delivered=True)]), store
    ).recover(receiver)

    assert [o.terminal for o in outcomes] == [TerminalState.APPLIED]
    assert store.pending() == []
    assert receiver.applied_count("bu-crash-1") == 1


def test_receiver_crash_between_apply_and_ack_does_not_reapply(registry, tmp_path):
    """AB-3: the effect and the applied-id ledger share one atomic commit, so
    a crash between application and acknowledgment cannot cause reapplication
    on redelivery."""
    store = CustodianStore(tmp_path / "custodian.json")
    rstore = ReceiverStore(tmp_path / "receiver.json")
    obligation = corrective_phala("bu-crash-2", delta=-0.4)

    # First incarnation: the receiver applies, commits, and dies pre-ack.
    receiver = DurableReceiver("agent-b", store=rstore)
    channel = ScriptedChannel([Hop(delivered=True)])
    with pytest.raises(CrashSignal):
        _durable_custodian(registry, channel, store).transfer(
            obligation, CrashAfterApply(receiver)
        )

    # Custody is undischarged (no ack reached the custodian).
    assert [o.obligation_id for o in store.pending()] == ["bu-crash-2"]

    # Restart both sides. The receiver recovers its ledger from the store.
    receiver2 = DurableReceiver("agent-b", store=rstore)
    assert receiver2.applied_count("bu-crash-2") == 1  # ledger survived

    outcomes = _durable_custodian(
        registry, ScriptedChannel([Hop(delivered=True)]), store
    ).recover(receiver2)

    # Redelivery re-acks applied without reapplying: effectively-once across
    # the crash, and the effect was not doubled.
    assert [o.terminal for o in outcomes] == [TerminalState.APPLIED]
    assert receiver2.applied_count("bu-crash-2") == 1
    assert receiver2.local_state[WEIGHT_KEY] == pytest.approx(-0.4)
    assert store.pending() == []


def test_recovery_into_dead_channel_escalates(registry, tmp_path):
    """Deliver-or-report across a crash: if the channel is still dead after
    restart, the recovered transfer terminates ESCALATED with the
    principal-side fail-safe applied (AB-4), not in silent loss."""
    store = CustodianStore(tmp_path / "custodian.json")
    rstore = ReceiverStore(tmp_path / "receiver.json")
    receiver = DurableReceiver("agent-b", store=rstore)
    obligation = corrective_phala("bu-crash-3")

    channel = CrashingChannel(ScriptedChannel([]), crash_on_attempt=1)
    with pytest.raises(CrashSignal):
        _durable_custodian(registry, channel, store).transfer(obligation, receiver)

    # Restart into a channel that drops everything (exhausted script).
    principal_state = PrincipalState()
    outcomes = _durable_custodian(
        registry, ScriptedChannel([]), store, principal_state
    ).recover(receiver)

    assert [o.terminal for o in outcomes] == [TerminalState.ESCALATED]
    assert len(principal_state.escalations) == 1
    assert principal_state.routing_weights[WEIGHT_KEY] < 0  # safe(O) applied
    assert receiver.applied_count("bu-crash-3") == 0
    assert store.pending() == []  # discharged by the fail-safe, not silent
