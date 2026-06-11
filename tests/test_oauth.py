# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""OAuth instantiation tests (paper §5): a standard, non-self-authored protocol.

Demonstrates that the framework is invariant-agnostic — a token revocation is
admissible and fail-closed (the Anumati shape), while token issue/refresh is
inadmissible and best-effort — using the same custody machine as Anumati/Phala.
"""

from __future__ import annotations

from abhyasa.custody import (
    Custodian,
    Hop,
    PrincipalState,
    Receiver,
    ScriptedChannel,
    TerminalState,
)
from abhyasa.instantiations import OAUTH_KIND, is_revocation
from abhyasa.types import Obligation, SafeEffect


def _revocation(obligation_id: str = "rev-1") -> Obligation:
    return Obligation(
        obligation_id=obligation_id,
        kind=OAUTH_KIND,
        target="resource-server",
        payload={"action": "revoke", "token_id": "tok-abc", "client_id": "cli-1"},
        deadline_seconds=3600,
        max_retries=16,
        created_at="2026-06-09T10:00:00+00:00",
    )


def _issue(obligation_id: str = "iss-1") -> Obligation:
    return Obligation(
        obligation_id=obligation_id,
        kind=OAUTH_KIND,
        target="resource-server",
        payload={"action": "issue", "token_id": "tok-xyz", "client_id": "cli-1"},
        deadline_seconds=3600,
        max_retries=16,
        created_at="2026-06-09T10:00:00+00:00",
    )


def _custodian(registry, channel, principal_state=None):
    return Custodian(
        registry=registry,
        principal_state=principal_state or PrincipalState(),
        channel=channel,
    )


# ── Admissibility (AC-1) ─────────────────────────────────────────────────────


def test_revocation_is_admissible(registry):
    assert registry.is_admissible(_revocation()) is True
    assert is_revocation(_revocation()) is True


def test_issue_and_refresh_are_inadmissible(registry):
    assert registry.is_admissible(_issue()) is False
    assert is_revocation(_issue()) is False


# ── safe(O) ──────────────────────────────────────────────────────────────────


def test_safe_action_is_fail_closed_on_token(registry):
    action = registry.safe(_revocation())
    assert action.effect is SafeEffect.FAIL_CLOSED
    assert action.scope == "tok-abc"


# ── Custody behavior over loss ───────────────────────────────────────────────


def test_unconfirmed_revocation_fails_closed(registry):
    principal_state = PrincipalState()
    receiver = Receiver("resource-server")
    channel = ScriptedChannel([])  # total loss
    out = _custodian(registry, channel, principal_state).transfer(
        _revocation(), receiver
    )
    assert out.terminal is TerminalState.ESCALATED
    assert principal_state.authorizations["tok-abc"] is False


def test_confirmed_revocation_applies(registry):
    principal_state = PrincipalState()
    receiver = Receiver("resource-server")
    channel = ScriptedChannel([Hop(delivered=True)])
    out = _custodian(registry, channel, principal_state).transfer(
        _revocation(), receiver
    )
    assert out.terminal is TerminalState.APPLIED
    # No fail-safe fired, so no forced withhold.
    assert principal_state.authorizations == {}


def test_issue_is_best_effort_not_under_custody(registry):
    principal_state = PrincipalState()
    receiver = Receiver("resource-server")
    channel = ScriptedChannel([Hop(delivered=False)])  # dropped, but no retry
    out = _custodian(registry, channel, principal_state).transfer(
        _issue(), receiver
    )
    assert out.terminal is TerminalState.BEST_EFFORT
    assert principal_state.escalations == []
    assert principal_state.authorizations == {}
