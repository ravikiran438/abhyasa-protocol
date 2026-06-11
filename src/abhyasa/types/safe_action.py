# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""SafeAction, the principal-side default the fail-safe executes (paper §3, §4).

``safe(O)`` is the pure function of an obligation's payload that returns the
action the principal must default to when the obligation is not confirmed
delivered (paper §3, Definition: fail-safe polarity). AB-4 executes the
returned SafeAction on principal-side state, which requires no remote
cooperation — so the guarantee holds without a working reverse channel.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SafeEffect(str, Enum):
    """The concrete principal-side effect a SafeAction applies.

    FAIL_CLOSED — withhold the action / revoke authority (Anumati, binary).
    DOWN_WEIGHT — reduce principal-side routing preference toward the target
                  (Phala corrective, signed).
    """

    FAIL_CLOSED = "fail_closed"
    DOWN_WEIGHT = "down_weight"


class SafeAction(BaseModel):
    """The default action AB-4 applies to principal-side state."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    obligation_id: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    effect: SafeEffect = Field(
        ..., description="fail_closed (Anumati) or down_weight (Phala)."
    )
    magnitude: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Down-weight magnitude for DOWN_WEIGHT; ignored for FAIL_CLOSED."
        ),
    )
    weight_key: Optional[str] = Field(
        default=None,
        description="Principal-side routing key adjusted by a DOWN_WEIGHT effect.",
    )
    scope: Optional[str] = Field(
        default=None,
        description="Authorization scope withheld by a FAIL_CLOSED effect.",
    )
    rationale: str = Field(
        ...,
        description="Human-readable justification recorded with the escalation.",
    )
