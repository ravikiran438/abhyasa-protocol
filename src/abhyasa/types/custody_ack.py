# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""CustodyAck, the acknowledgment that attests application, not receipt (paper §4).

The Abhyasa custody acknowledgment confirms that an obligation was *applied*
(or accountably *declined*), not merely that its bytes arrived. This is the
single shared CustodyAck used by every Abhyasa instantiation; the Phala
instantiation (paper §5) binds its ``obligation_id`` to the BeliefUpdate
``update_id`` and ``target`` to ``target_agent_id``.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CustodyStatus(str, Enum):
    """Terminal disposition reported by the receiver (paper §4).

    APPLIED  — the receiver applied the obligation, or idempotently
               recognized it as already applied. Custody is discharged.
    DECLINED — the receiver accountably refused. A *delivered* outcome:
               custody is discharged, logged, and MUST NOT be retried.
    DEFERRED — received, not yet applied; custody remains undischarged and
               the custodian keeps responsibility until the deadline.
    """

    APPLIED = "applied"
    DECLINED = "declined"
    DEFERRED = "deferred"


class CustodyAck(BaseModel):
    """Confirms application (or accountable refusal) of an obligation."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    obligation_id: str = Field(
        ...,
        min_length=1,
        description="The Obligation.obligation_id this acknowledgment discharges.",
    )
    target: str = Field(
        ...,
        min_length=1,
        description="The agent that produced this acknowledgment.",
    )
    status: CustodyStatus = Field(
        ..., description="applied | declined | deferred (paper §4)."
    )
    acked_at: str = Field(
        ..., description="ISO 8601 timestamp at which the ack was emitted."
    )
