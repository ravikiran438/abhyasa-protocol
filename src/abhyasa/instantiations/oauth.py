# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""OAuth instantiation: token revocation, fail-closed (paper §5).

A third instantiation on a *standard, non-self-authored* protocol, included to
substantiate the invariant-agnostic claim. OAuth token lifecycle messages split
cleanly on the asymmetric-cost criterion:

  - A token *revocation* is admissible (AC-1): losing it leaves a live token
    honored — the unsafe direction. Its fail-safe is principal-mediated and
    local: the authorization server (or resource gateway) stops honoring the
    token. This is exactly the Anumati fail-closed shape.

  - Token *issue* / *refresh* is inadmissible: losing it is benign, the client
    simply retries. It travels best-effort and declares no fail-safe polarity.

For resource servers that validate from an autonomously cached copy, the
principal-side withhold degrades to the report branch (paper §4.1) — which is
why OAuth practice already pairs revocation with short token lifetimes (the
lease mitigation).
"""

from __future__ import annotations

from abhyasa.polarity import PolarityRule
from abhyasa.types.obligation import Obligation
from abhyasa.types.safe_action import SafeAction, SafeEffect

OAUTH_KIND = "oauth.token"


def is_revocation(obligation: Obligation) -> bool:
    """Admissibility split: only a revocation carries asymmetric loss cost."""
    return obligation.payload.get("action") == "revoke"


def _admissible(obligation: Obligation) -> bool:
    # Only revocation is custody-carried; issue/refresh is benign best-effort.
    return is_revocation(obligation)


def _safe(obligation: Obligation) -> SafeAction:
    # Scope the withhold to the token (preferred) or the client.
    scope = (
        obligation.payload.get("token_id")
        or obligation.payload.get("client_id")
        or obligation.target
    )
    return SafeAction(
        obligation_id=obligation.obligation_id,
        target=obligation.target,
        effect=SafeEffect.FAIL_CLOSED,
        scope=str(scope),
        rationale=(
            "OAuth: an unconfirmed token revocation defaults fail-closed — the "
            "authorization server / resource gateway stops honoring the token."
        ),
    )


OAUTH_RULE = PolarityRule(kind=OAUTH_KIND, admissible=_admissible, safe=_safe)
