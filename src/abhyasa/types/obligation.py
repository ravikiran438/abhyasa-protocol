# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Obligation, the governance constraint carried under custody (paper §3, §4).

An Obligation is a message whose receiver is required to honor a constraint
it carries. Abhyasa is invariant-agnostic over its admissible class: the
``kind`` field selects which instantiation's polarity rule supplies the
fail-safe default ``safe(O)`` (paper §3, AC-1). The framework holds the
obligation under custody until it is applied, declined, or escalated.
"""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field


class Obligation(BaseModel):
    """A governance obligation delivered under the deliver-or-report guarantee.

    See paper §3 (asymmetric-cost criterion) and §4 (AB-1..AB-4). The
    ``obligation_id`` is the stable key on which idempotent application is
    performed (AB-3): a redelivered obligation whose id has already been
    applied MUST NOT be reapplied.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    obligation_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Stable identifier for this obligation. The idempotency key for "
            "AB-3: at-least-once delivery, effectively-once application."
        ),
    )
    kind: str = Field(
        ...,
        min_length=1,
        description=(
            "Invariant selector, e.g. 'anumati.consent' or "
            "'phala.belief_update'. Dispatches the polarity rule that supplies "
            "AC-1 admissibility and safe(O)."
        ),
    )
    target: str = Field(
        ...,
        min_length=1,
        description="Identifier of the agent required to honor the obligation.",
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Invariant-specific body. The registered polarity rule reads this "
            "to compute admissibility and the safe default (e.g. Phala reads "
            "'weight_delta'; Anumati reads 'decision' and 'scope')."
        ),
    )
    deadline_seconds: int = Field(
        ...,
        gt=0,
        description=(
            "AB-1 custody deadline. The custodian retains responsibility until "
            "an applied/declined ack, or until this window elapses."
        ),
    )
    max_retries: int = Field(
        ...,
        ge=0,
        description=(
            "AB-2 bound on retransmission attempts under bounded exponential "
            "backoff before the fail-safe (AB-4) fires."
        ),
    )
    created_at: str = Field(
        ...,
        description="ISO 8601 timestamp at which the obligation was issued.",
    )
