# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Principal-side state, where the AB-4 fail-safe takes effect (paper §4).

The decisive property of Abhyasa: the fail-safe acts on state the custodian
*owns* — its own routing weights and authorization ledger — so it completes
without remote cooperation and cannot be defeated by the lossy channel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from abhyasa.types.safe_action import SafeAction, SafeEffect


@dataclass
class PrincipalState:
    """Mutable principal-side state acted on by safe(O) (AB-4)."""

    routing_weights: Dict[str, float] = field(default_factory=dict)
    authorizations: Dict[str, bool] = field(default_factory=dict)
    escalations: List[dict] = field(default_factory=list)
    # Supersession guard (paper v1.1 S4): highest issuance sequence applied
    # per governed key. Set-semantic application is last-writer-wins, so a
    # timed-out older obligation's safe(O) cannot regress a newer decision.
    applied_sequences: Dict[str, int] = field(default_factory=dict)

    def apply(self, action: SafeAction) -> None:
        """Apply a SafeAction. Pure-local; never touches the network.

        Set-semantic effects (FAIL_CLOSED) honor the supersession guard:
        an action carrying a sequence lower than the newest decision already
        applied on the same key applies nothing. Additive, commutative
        effects (DOWN_WEIGHT) are order-independent and are not guarded.
        """
        if action.effect is SafeEffect.DOWN_WEIGHT:
            key = action.weight_key or action.target
            self.routing_weights[key] = (
                self.routing_weights.get(key, 0.0) - action.magnitude
            )
        elif action.effect is SafeEffect.FAIL_CLOSED:
            scope = action.scope or action.target
            if self._superseded(scope, action.sequence):
                return  # a newer decision on this key stands; apply nothing
            self.authorizations[scope] = False
            if action.sequence is not None:
                self.applied_sequences[scope] = action.sequence
        else:  # pragma: no cover - exhaustive over SafeEffect
            raise ValueError(f"unknown safe effect {action.effect!r}")

    def apply_decision(self, scope: str, allowed: bool, sequence: int) -> None:
        """Record the principal's own decision on a governed key.

        The principal's decisions and the fail-safe pass through the same
        last-writer-wins guard, so ordering is total per key regardless of
        which path applies first.
        """
        if self._superseded(scope, sequence):
            return
        self.authorizations[scope] = allowed
        self.applied_sequences[scope] = sequence

    def _superseded(self, scope: str, sequence) -> bool:
        return (
            sequence is not None
            and self.applied_sequences.get(scope, -1) >= sequence
        )
