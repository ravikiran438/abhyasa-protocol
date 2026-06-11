# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Governance-invariant instantiations and the default polarity registry."""

from abhyasa.instantiations.anumati import ANUMATI_KIND, ANUMATI_RULE
from abhyasa.instantiations.oauth import OAUTH_KIND, OAUTH_RULE, is_revocation
from abhyasa.instantiations.phala import PHALA_KIND, PHALA_RULE, is_corrective
from abhyasa.polarity import PolarityRegistry


def default_registry() -> PolarityRegistry:
    """A registry with the shipped instantiations registered.

    Anumati (consent) and Phala (welfare feedback) are the two governance
    invariants of the paper; OAuth (token revocation) is a third, standard
    instantiation demonstrating that the admissible class is not limited to
    self-authored protocols.
    """
    registry = PolarityRegistry()
    registry.register(ANUMATI_RULE)
    registry.register(PHALA_RULE)
    registry.register(OAUTH_RULE)
    return registry


__all__ = [
    "ANUMATI_KIND",
    "ANUMATI_RULE",
    "OAUTH_KIND",
    "OAUTH_RULE",
    "PHALA_KIND",
    "PHALA_RULE",
    "default_registry",
    "is_corrective",
    "is_revocation",
]
