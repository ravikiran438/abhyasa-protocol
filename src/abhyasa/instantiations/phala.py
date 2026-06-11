# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Phala instantiation: valence-signed, corrective-only custody (paper §5).

Phala exercises the *signed* polarity axis. The obligation payload is a
BeliefUpdate; the sign of ``weight_delta`` (inheriting valence) classifies it
(DEL-1):

  corrective  (weight_delta < 0)  — Abhyasa-admissible; carried under custody.
  reinforcing (weight_delta >= 0) — inadmissible; best-effort (DEL-5).

safe(O) for a corrective update is the principal-side routing down-weight
(DEL-4): the orchestrator reduces its own preference for routing to the target
it could not correct. This is principal-side state, so it holds without a
working reverse channel.

The custody mechanics are Abhyasa's AB-1–AB-4; the Phala-local DEL-1–DEL-5
labels (from the companion lossy-transport delivery note) are mnemonics for the
same invariants applied to corrective valence, and the AB invariants are
normative.
"""

from __future__ import annotations

from abhyasa.polarity import PolarityRule
from abhyasa.types.obligation import Obligation
from abhyasa.types.safe_action import SafeAction, SafeEffect

PHALA_KIND = "phala.belief_update"


def is_corrective(obligation: Obligation) -> bool:
    """DEL-1 classification: corrective iff weight_delta < 0."""
    delta = obligation.payload.get("weight_delta")
    if delta is None:
        raise ValueError(
            "phala.belief_update obligation payload must carry 'weight_delta'"
        )
    return float(delta) < 0.0


def _admissible(obligation: Obligation) -> bool:
    # DEL-1 / DEL-5: only corrective updates are custody-carried.
    return is_corrective(obligation)


def _safe(obligation: Obligation) -> SafeAction:
    delta = float(obligation.payload["weight_delta"])
    weight_key = obligation.payload.get(
        "weight_key", f"routing.{obligation.target}.preference"
    )
    return SafeAction(
        obligation_id=obligation.obligation_id,
        target=obligation.target,
        effect=SafeEffect.DOWN_WEIGHT,
        magnitude=abs(delta),
        weight_key=str(weight_key),
        rationale=(
            "Phala DEL-4: principal-side routing down-weight toward the target "
            "whose corrective update could not be confirmed applied."
        ),
    )


PHALA_RULE = PolarityRule(kind=PHALA_KIND, admissible=_admissible, safe=_safe)
