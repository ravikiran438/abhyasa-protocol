# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""AC-1 admissibility and safe(O) tests (paper §3, §5)."""

from __future__ import annotations

import pytest

from abhyasa.polarity import PolarityError, PolarityRegistry
from abhyasa.types import Obligation, SafeEffect
from tests.conftest import anumati_consent, corrective_phala, reinforcing_phala


def test_corrective_phala_is_admissible(registry):
    # DEL-1: weight_delta < 0 -> custody-carried.
    assert registry.is_admissible(corrective_phala()) is True


def test_reinforcing_phala_is_inadmissible(registry):
    # DEL-1 / DEL-5: weight_delta >= 0 -> best-effort, not under custody.
    assert registry.is_admissible(reinforcing_phala()) is False


def test_anumati_consent_is_admissible(registry):
    assert registry.is_admissible(anumati_consent()) is True


def test_unknown_kind_is_inadmissible(registry):
    o = Obligation(
        obligation_id="x-1",
        kind="unknown.kind",
        target="agent-z",
        deadline_seconds=10,
        max_retries=1,
        created_at="2026-06-09T10:00:00+00:00",
    )
    assert registry.is_admissible(o) is False
    with pytest.raises(PolarityError):
        registry.safe(o)


def test_phala_safe_is_principal_side_down_weight(registry):
    action = registry.safe(corrective_phala(delta=-0.4))
    assert action.effect is SafeEffect.DOWN_WEIGHT
    assert action.magnitude == pytest.approx(0.4)
    assert action.weight_key == "routing.agent_b.preference"


def test_anumati_safe_is_fail_closed(registry):
    action = registry.safe(anumati_consent())
    assert action.effect is SafeEffect.FAIL_CLOSED
    assert action.scope == "calendar.write"


def test_empty_registry_admits_nothing():
    empty = PolarityRegistry()
    assert empty.is_admissible(corrective_phala()) is False
