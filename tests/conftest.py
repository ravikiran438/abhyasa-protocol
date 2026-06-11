# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Shared fixtures and obligation builders for the Abhyasa test suite."""

from __future__ import annotations

import pytest

from abhyasa.instantiations import default_registry
from abhyasa.types import Obligation


@pytest.fixture
def registry():
    return default_registry()


def corrective_phala(obligation_id: str = "bu-1", delta: float = -0.4) -> Obligation:
    """A corrective (admissible) Phala BeliefUpdate obligation.

    The retry budget is sized so the deadline, not the retry count, is the
    binding terminator: with exponential backoff capped at 3600 s, ~35 attempts
    are needed to span the 24 h deadline, so max_retries (48) exceeds that and
    the custodian keeps re-attempting roughly hourly across the full deadline —
    the delay-tolerant behavior custody transfer is for.
    """
    return Obligation(
        obligation_id=obligation_id,
        kind="phala.belief_update",
        target="agent-b",
        payload={
            "weight_delta": delta,
            "weight_key": "routing.agent_b.preference",
        },
        deadline_seconds=86400,
        max_retries=48,
        created_at="2026-06-09T10:00:00+00:00",
    )


def reinforcing_phala(obligation_id: str = "bu-2", delta: float = 0.3) -> Obligation:
    """A reinforcing (inadmissible / best-effort) Phala BeliefUpdate obligation."""
    return Obligation(
        obligation_id=obligation_id,
        kind="phala.belief_update",
        target="agent-b",
        payload={
            "weight_delta": delta,
            "weight_key": "routing.agent_b.preference",
        },
        deadline_seconds=86400,
        max_retries=48,
        created_at="2026-06-09T10:00:00+00:00",
    )


def anumati_consent(obligation_id: str = "cn-1") -> Obligation:
    """A binary Anumati consent obligation (always admissible).

    max_retries (16) likewise exceeds the ~12 attempts the capped backoff needs
    to span the 1 h deadline, so the deadline is the binding terminator.
    """
    return Obligation(
        obligation_id=obligation_id,
        kind="anumati.consent",
        target="agent-c",
        payload={"decision": "revoke", "scope": "calendar.write"},
        deadline_seconds=3600,
        max_retries=16,
        created_at="2026-06-09T10:00:00+00:00",
    )
