# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Anumati instantiation: binary consent, fail-closed (paper §5).

Anumati exercises the *binary* polarity axis, and admissibility is
per-instance (paper v1.1): a revocation is admissible because its loss leaves
an agent acting on withdrawn authority, while a consent *grant* is
inadmissible for the same reason as OAuth token issuance — its loss is the
benign default (the agent simply lacks the authority, cannot act, and its
next request surfaces the gap), so grants travel best-effort. For admissible
obligations the fail-safe default is to withhold the action (fail-closed): an
unconfirmed revocation must not be treated as still-authorized.
"""

from __future__ import annotations

from abhyasa.polarity import PolarityRule
from abhyasa.types.obligation import Obligation
from abhyasa.types.safe_action import SafeAction, SafeEffect

ANUMATI_KIND = "anumati.consent"


def _admissible(obligation: Obligation) -> bool:
    # Per-instance admissibility (paper v1.1, §5): revocations and other
    # restrictive decisions are admissible; a grant's loss is benign, so it
    # is inadmissible and travels best-effort. An obligation that does not
    # state its decision is treated as restrictive — custody of a
    # restriction is the safe default.
    return obligation.payload.get("decision", "revoke") != "grant"


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
