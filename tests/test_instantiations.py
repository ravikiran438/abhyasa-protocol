# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Instantiation tests: Anumati (binary) and Phala (signed) (paper §5)."""

from __future__ import annotations

from abhyasa.custody import (
    Custodian,
    Hop,
    PrincipalState,
    Receiver,
    ScriptedChannel,
    TerminalState,
)
from abhyasa.instantiations import is_corrective
from tests.conftest import anumati_consent, corrective_phala, reinforcing_phala


def test_phala_classification_by_sign():
    assert is_corrective(corrective_phala(delta=-0.01)) is True
    assert is_corrective(reinforcing_phala(delta=0.0)) is False
    assert is_corrective(reinforcing_phala(delta=0.5)) is False


def test_anumati_unconfirmed_consent_fails_closed(registry):
    # Total loss of a consent obligation -> fail-closed (authority withheld).
    principal_state = PrincipalState()
    receiver = Receiver("agent-c")
    channel = ScriptedChannel([])  # everything drops
    out = Custodian(
        registry=registry, principal_state=principal_state, channel=channel
    ).transfer(anumati_consent(), receiver)
    assert out.terminal is TerminalState.ESCALATED
    assert principal_state.authorizations["calendar.write"] is False


def test_anumati_confirmed_consent_applies(registry):
    principal_state = PrincipalState()
    receiver = Receiver("agent-c")
    channel = ScriptedChannel([Hop(delivered=True)])
    out = Custodian(
        registry=registry, principal_state=principal_state, channel=channel
    ).transfer(anumati_consent(), receiver)
    assert out.terminal is TerminalState.APPLIED
    # No fail-safe fired, so no authorization was force-closed.
    assert principal_state.authorizations == {}


def test_phala_corrective_lost_downweights_principal_side(registry):
    principal_state = PrincipalState()
    receiver = Receiver("agent-b")
    channel = ScriptedChannel([])  # corrective update never lands
    out = Custodian(
        registry=registry, principal_state=principal_state, channel=channel
    ).transfer(corrective_phala(delta=-0.25), receiver)
    assert out.terminal is TerminalState.ESCALATED
    assert principal_state.routing_weights["routing.agent_b.preference"] == -0.25


def test_phala_reinforcing_is_never_under_custody(registry):
    # DEL-5: reinforcing update is best-effort; no escalation even if dropped.
    principal_state = PrincipalState()
    receiver = Receiver("agent-b")
    channel = ScriptedChannel([Hop(delivered=False)])
    out = Custodian(
        registry=registry, principal_state=principal_state, channel=channel
    ).transfer(reinforcing_phala(), receiver)
    assert out.terminal is TerminalState.BEST_EFFORT
    assert principal_state.routing_weights == {}
    assert principal_state.escalations == []
