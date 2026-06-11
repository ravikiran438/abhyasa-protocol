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

    def apply(self, action: SafeAction) -> None:
        """Apply a SafeAction. Pure-local; never touches the network."""
        if action.effect is SafeEffect.DOWN_WEIGHT:
            key = action.weight_key or action.target
            self.routing_weights[key] = (
                self.routing_weights.get(key, 0.0) - action.magnitude
            )
        elif action.effect is SafeEffect.FAIL_CLOSED:
            scope = action.scope or action.target
            self.authorizations[scope] = False
        else:  # pragma: no cover - exhaustive over SafeEffect
            raise ValueError(f"unknown safe effect {action.effect!r}")
