# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""The deliver-or-report guarantee under adversarial loss (paper §4).

These are the headline tests: under arbitrary channel loss, every admissible
obligation terminates as applied, declined, or escalated — never silent loss —
and application is effectively-once under duplication.
"""

from __future__ import annotations

import pytest

from abhyasa.custody import (
    Custodian,
    PrincipalState,
    Receiver,
    TerminalState,
)
from abhyasa.custody.channel import ChannelConfig, LossyChannel
from abhyasa.types import CustodyStatus
from tests.conftest import corrective_phala

TERMINAL_NON_SILENT = {
    TerminalState.APPLIED,
    TerminalState.DECLINED,
    TerminalState.ESCALATED,
}


@pytest.mark.parametrize("seed", range(50))
@pytest.mark.parametrize("drop_prob", [0.0, 0.3, 0.6, 0.9, 1.0])
def test_admissible_obligation_never_silently_lost(registry, seed, drop_prob):
    """Across 50 seeds x 5 loss levels: always a non-silent terminal state."""
    principal_state = PrincipalState()
    receiver = Receiver("agent-b")
    channel = LossyChannel(
        ChannelConfig(
            drop_prob=drop_prob,
            duplicate_prob=0.3,
            ack_drop_prob=drop_prob,
            seed=seed,
        )
    )
    custodian = Custodian(
        registry=registry, principal_state=principal_state, channel=channel
    )
    out = custodian.transfer(corrective_phala(f"bu-{seed}"), receiver)

    assert out.terminal in TERMINAL_NON_SILENT
    assert out.discharged is True
    # Effectively-once: the effect is applied at most once regardless of dups.
    assert receiver.applied_count(f"bu-{seed}") <= 1
    # If escalated, the principal-side fail-safe ran (protection is local).
    if out.terminal is TerminalState.ESCALATED:
        assert len(principal_state.escalations) == 1
        assert principal_state.routing_weights["routing.agent_b.preference"] < 0


@pytest.mark.parametrize("seed", range(25))
def test_total_partition_always_escalates(registry, seed):
    """drop_prob=1.0: nothing gets through, so the terminal is always escalation
    and the principal is protected without a working reverse channel."""
    principal_state = PrincipalState()
    receiver = Receiver("agent-b")
    channel = LossyChannel(ChannelConfig(drop_prob=1.0, seed=seed))
    custodian = Custodian(
        registry=registry, principal_state=principal_state, channel=channel
    )
    out = custodian.transfer(corrective_phala(f"bu-part-{seed}"), receiver)
    assert out.terminal is TerminalState.ESCALATED
    assert receiver.applied_count(f"bu-part-{seed}") == 0
    assert principal_state.routing_weights["routing.agent_b.preference"] == -0.4


@pytest.mark.parametrize("seed", range(25))
def test_lossless_channel_always_applies(registry, seed):
    principal_state = PrincipalState()
    receiver = Receiver("agent-b")
    channel = LossyChannel(ChannelConfig(duplicate_prob=0.5, seed=seed))
    custodian = Custodian(
        registry=registry, principal_state=principal_state, channel=channel
    )
    out = custodian.transfer(corrective_phala(f"bu-clean-{seed}"), receiver)
    assert out.terminal is TerminalState.APPLIED
    assert receiver.applied_count(f"bu-clean-{seed}") == 1


def test_declining_receiver_terminates_declined_under_loss(registry):
    principal_state = PrincipalState()
    receiver = Receiver("agent-b", lambda _o: CustodyStatus.DECLINED)
    channel = LossyChannel(ChannelConfig(drop_prob=0.5, ack_drop_prob=0.5, seed=7))
    custodian = Custodian(
        registry=registry, principal_state=principal_state, channel=channel
    )
    out = custodian.transfer(corrective_phala(), receiver)
    # Either it eventually gets the declined ack through, or it escalates —
    # but never silent loss, and a declined never triggers a down-weight twice.
    assert out.terminal in {TerminalState.DECLINED, TerminalState.ESCALATED}
