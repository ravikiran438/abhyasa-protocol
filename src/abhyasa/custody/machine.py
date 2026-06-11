# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""The Abhyasa custody state machine: AB-1..AB-4 (paper §4).

The custodian (the sending agent) holds an admissible obligation and drives it
to exactly one terminal state:

  AB-1 (Custody)      retain responsibility until an applied/declined ack or
                      until the deadline elapses.
  AB-2 (Persistence)  on timeout, retry under bounded exponential backoff, up
                      to max_retries.
  AB-3 (Idempotency)  enforced on the receiver, keyed on obligation_id.
  AB-4 (Fail-safe)    on deadline without applied/declined, execute safe(O) on
                      principal-side state and emit a principal-visible
                      escalation.

Deliver-or-report (guarantee): every admissible obligation terminates as
APPLIED, DECLINED, or ESCALATED — never silent loss.

Inadmissible obligations (AC-1 false — e.g. a reinforcing Phala update) are
delivered best-effort: a single attempt, no custody, no fail-safe.

Time is modeled by a logical :class:`Clock` so the machine is fully
deterministic and testable without wall-clock waits.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from abhyasa.custody.channel import Channel, Endpoint
from abhyasa.custody.principal_state import PrincipalState
from abhyasa.polarity import PolarityRegistry
from abhyasa.types.custody_ack import CustodyAck, CustodyStatus
from abhyasa.types.obligation import Obligation


class TerminalState(str, Enum):
    """The exhaustive terminal states of a custody transfer."""

    APPLIED = "applied"
    DECLINED = "declined"
    ESCALATED = "escalated"
    BEST_EFFORT = "best_effort"  # inadmissible obligation; not under custody


class Escalation(BaseModel):
    """The principal-visible event emitted by AB-4."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(default="abhyasa.delivery_failed")
    obligation_id: str
    target: str
    attempts: int
    last_error: str
    escalated_at: str


class CustodyOutcome(BaseModel):
    """The result of a custody transfer."""

    model_config = ConfigDict(frozen=True)

    obligation_id: str
    target: str
    terminal: TerminalState
    attempts: int
    ack: Optional[CustodyAck] = None
    escalation: Optional[Escalation] = None

    @property
    def discharged(self) -> bool:
        """True iff the obligation reached a non-silent terminal state.

        For an admissible obligation this is always True after transfer() —
        that is the deliver-or-report guarantee.
        """
        return self.terminal in (
            TerminalState.APPLIED,
            TerminalState.DECLINED,
            TerminalState.ESCALATED,
        )


class Clock:
    """A logical clock measured in seconds. No wall-clock dependency."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    @property
    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def exponential_backoff(attempt: int, base: float, cap: float) -> float:
    """Bounded exponential backoff for AB-2. attempt is 1-based."""
    return min(cap, base * (2 ** (attempt - 1)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Custodian:
    """Holds an obligation and enforces AB-1..AB-4 against a channel.

    Durability note (paper §4, AB-1/AB-2): a production custodian MUST persist
    its pending custody set to durable storage (write-ahead) before accepting
    custody, and resume it on restart, so a custodian crash delays rather than
    abandons a transfer. This class runs a single transfer to completion in
    memory; :class:`abhyasa.custody.durable.DurableCustodian` wraps it with
    the write-ahead pending set and the recovery pass, and
    tests/test_crash_recovery.py exercises both crash sides.
    """

    def __init__(
        self,
        *,
        registry: PolarityRegistry,
        principal_state: PrincipalState,
        channel: Channel,
        clock: Optional[Clock] = None,
        backoff_base: float = 1.0,
        backoff_cap: float = 3600.0,
        clock_fn=_now_iso,
    ) -> None:
        self.registry = registry
        self.principal_state = principal_state
        self.channel = channel
        self.clock = clock or Clock()
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._clock_fn = clock_fn

    def transfer(self, obligation: Obligation, endpoint: Endpoint) -> CustodyOutcome:
        """Drive ``obligation`` to a terminal state. Never returns silent loss."""
        if not self.registry.is_admissible(obligation):
            # Benign-loss side (AC-1 false): best-effort, no custody, no retry.
            self.channel.round_trip(obligation, endpoint)
            return CustodyOutcome(
                obligation_id=obligation.obligation_id,
                target=obligation.target,
                terminal=TerminalState.BEST_EFFORT,
                attempts=1,
            )

        deadline = self.clock.now + obligation.deadline_seconds
        attempt = 0
        last_error = "no acknowledgment received within deadline"

        # AB-1 / AB-2: retain custody and retry until an applied/declined ack,
        # the retry bound, or the deadline.
        while self.clock.now < deadline and attempt <= obligation.max_retries:
            attempt += 1
            ack = self.channel.round_trip(obligation, endpoint)
            if ack is not None and ack.status in (
                CustodyStatus.APPLIED,
                CustodyStatus.DECLINED,
            ):
                return CustodyOutcome(
                    obligation_id=obligation.obligation_id,
                    target=obligation.target,
                    terminal=TerminalState(ack.status.value),
                    attempts=attempt,
                    ack=ack,
                )
            if ack is not None and ack.status is CustodyStatus.DEFERRED:
                last_error = "receiver deferred; custody retained"
            else:
                last_error = "delivery or acknowledgment lost on channel"
            self.clock.advance(
                exponential_backoff(attempt, self.backoff_base, self.backoff_cap)
            )

        # AB-4: fail-safe on principal-side state + principal-visible escalation.
        action = self.registry.safe(obligation)
        self.principal_state.apply(action)
        escalation = Escalation(
            obligation_id=obligation.obligation_id,
            target=obligation.target,
            attempts=attempt,
            last_error=last_error,
            escalated_at=self._clock_fn(),
        )
        self.principal_state.escalations.append(escalation.model_dump())
        return CustodyOutcome(
            obligation_id=obligation.obligation_id,
            target=obligation.target,
            terminal=TerminalState.ESCALATED,
            attempts=attempt,
            escalation=escalation,
        )
