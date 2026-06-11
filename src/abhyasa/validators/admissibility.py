# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""AC-1 admissibility validator (paper §3).

The type system constructs an Obligation, but whether that obligation is
*Abhyasa-admissible* — whether it declares a fail-safe polarity — depends on the
registered instantiation. This validator answers that question for an obligation
received over the wire, where the construction-site guarantees no longer apply.
"""

from __future__ import annotations

from abhyasa.polarity import PolarityRegistry
from abhyasa.types.obligation import Obligation


class AdmissibilityError(ValueError):
    """Raised when an obligation that must be admissible is not (AC-1)."""


def require_admissible(
    obligation: Obligation, registry: PolarityRegistry
) -> None:
    """Raise :class:`AdmissibilityError` unless ``obligation`` is admissible.

    Use this before placing an obligation under custody. Inadmissible
    obligations (no registered polarity, or a rule that declines this instance,
    e.g. a reinforcing Phala update) must travel best-effort instead.
    """
    if not registry.is_admissible(obligation):
        rule = registry.rule_for(obligation)
        reason = (
            f"no polarity rule registered for kind {obligation.kind!r}"
            if rule is None
            else "registered rule declares this instance inadmissible "
            "(benign-loss side; deliver best-effort, not under custody)"
        )
        raise AdmissibilityError(
            f"obligation {obligation.obligation_id!r} is not Abhyasa-admissible "
            f"(AC-1): {reason}."
        )
