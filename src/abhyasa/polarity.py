# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Fail-safe polarity and AC-1 admissibility (paper §3).

A polarity rule supplies, for a given obligation ``kind``:
  - an admissibility predicate (AC-1: an obligation is Abhyasa-admissible iff
    it declares a fail-safe polarity), and
  - the pure ``safe(O)`` function returning the principal-side default.

Instantiations register a :class:`PolarityRule`. The framework stays
invariant-agnostic: it never inspects payload semantics directly, only through
the registered rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

from abhyasa.types.obligation import Obligation
from abhyasa.types.safe_action import SafeAction

AdmissibilityFn = Callable[[Obligation], bool]
SafeFn = Callable[[Obligation], SafeAction]


class PolarityError(ValueError):
    """Raised when safe(O) is requested for an obligation with no polarity rule."""


@dataclass(frozen=True)
class PolarityRule:
    """An instantiation's contribution: AC-1 predicate + safe(O) for one kind."""

    kind: str
    admissible: AdmissibilityFn
    safe: SafeFn


class PolarityRegistry:
    """Dispatches obligations to their registered polarity rule."""

    def __init__(self) -> None:
        self._rules: Dict[str, PolarityRule] = {}

    def register(self, rule: PolarityRule) -> "PolarityRegistry":
        self._rules[rule.kind] = rule
        return self

    def rule_for(self, obligation: Obligation) -> Optional[PolarityRule]:
        return self._rules.get(obligation.kind)

    def is_admissible(self, obligation: Obligation) -> bool:
        """AC-1: admissible iff a rule is registered AND it declares a polarity.

        An unregistered kind, or a registered rule whose predicate returns
        False for this instance (e.g. a reinforcing Phala update), is
        *inadmissible* and travels best-effort rather than under custody.
        """
        rule = self.rule_for(obligation)
        return rule is not None and rule.admissible(obligation)

    def safe(self, obligation: Obligation) -> SafeAction:
        """Return safe(O), the principal-side default. Requires a polarity rule."""
        rule = self.rule_for(obligation)
        if rule is None:
            raise PolarityError(
                f"no polarity rule registered for kind {obligation.kind!r}; "
                "obligation is not Abhyasa-admissible (AC-1)."
            )
        return rule.safe(obligation)
