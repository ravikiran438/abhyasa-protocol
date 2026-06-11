# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Anumati instantiation: binary consent, fail-closed (paper §5).

Anumati exercises the *binary* polarity axis. A consent obligation — a grant or
a revocation — is always Abhyasa-admissible: its fail-safe default is to
withhold the action (fail-closed). An unconfirmed grant must not be treated as
granted; an unconfirmed revocation must not be treated as still-authorized.
Both collapse to the same safe state: deny.
"""

from __future__ import annotations

from abhyasa.polarity import PolarityRule
from abhyasa.types.obligation import Obligation
from abhyasa.types.safe_action import SafeAction, SafeEffect

ANUMATI_KIND = "anumati.consent"


def _admissible(_obligation: Obligation) -> bool:
    # Every consent obligation declares a fail-safe polarity (deny). AC-1 holds.
    return True


def _safe(obligation: Obligation) -> SafeAction:
    scope = obligation.payload.get("scope", obligation.target)
    return SafeAction(
        obligation_id=obligation.obligation_id,
        target=obligation.target,
        effect=SafeEffect.FAIL_CLOSED,
        scope=str(scope),
        rationale=(
            "Anumati: an unconfirmed consent decision defaults fail-closed — "
            "withhold authority for the scope until the decision is confirmed."
        ),
    )


ANUMATI_RULE = PolarityRule(
    kind=ANUMATI_KIND, admissible=_admissible, safe=_safe
)
