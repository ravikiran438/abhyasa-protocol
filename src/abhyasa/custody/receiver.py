# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Receiving agent: idempotent application keyed on obligation_id (AB-3).

The receiver decides applied/declined/deferred for each obligation and applies
the effect *at most once*, keyed on ``obligation_id``. A redelivered obligation
whose id is already in the ledger is acknowledged ``applied`` WITHOUT
reapplying its effect — this is what makes at-least-once delivery safe:
delivery is at-least-once, application is effectively-once.

Durability note (paper §4, AB-3): a production receiver MUST persist the
applied-id ledger durably, in the same atomic commit as the effect, so the
at-most-once property survives a receiver crash; a crash between application
and acknowledgment would otherwise let a redelivery reapply. This class keeps
the ledger in memory; :class:`abhyasa.custody.durable.DurableReceiver` adds
the atomic ledger-plus-effect commit, and tests/test_crash_recovery.py
exercises the crash-between-apply-and-ack case.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional, Set

from abhyasa.types.custody_ack import CustodyAck, CustodyStatus
from abhyasa.types.obligation import Obligation

DecisionFn = Callable[[Obligation], CustodyStatus]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class Receiver:
    """A target agent endpoint with an idempotency ledger (AB-3)."""

    def __init__(
        self,
        agent_id: str,
        decide: Optional[DecisionFn] = None,
        *,
        clock_fn: Callable[[], str] = _now_iso,
    ) -> None:
        self.agent_id = agent_id
        self._decide: DecisionFn = decide or (lambda _o: CustodyStatus.APPLIED)
        self._clock_fn = clock_fn
        # AB-3 ledger of obligation_ids whose effect has been applied.
        self._applied: Set[str] = set()
        # Diagnostic counters for effectively-once assertions.
        self.apply_count: Dict[str, int] = {}
        # Receiver-side state the obligation mutates when applied.
        self.local_state: Dict[str, float] = {}

    def deliver(self, obligation: Obligation) -> CustodyAck:
        """Apply (idempotently), decline, or defer; return a CustodyAck."""
        oid = obligation.obligation_id
        if oid in self._applied:
            # AB-3: already applied — ack applied, do NOT reapply the effect.
            return self._ack(obligation, CustodyStatus.APPLIED)

        decision = self._decide(obligation)
        if decision is CustodyStatus.APPLIED:
            self._apply_once(obligation)
            self._applied.add(oid)
            return self._ack(obligation, CustodyStatus.APPLIED)
        if decision is CustodyStatus.DECLINED:
            return self._ack(obligation, CustodyStatus.DECLINED)
        return self._ack(obligation, CustodyStatus.DEFERRED)

    def applied_count(self, obligation_id: str) -> int:
        """How many times the effect was actually applied (must be <= 1)."""
        return self.apply_count.get(obligation_id, 0)

    def _apply_once(self, obligation: Obligation) -> None:
        oid = obligation.obligation_id
        self.apply_count[oid] = self.apply_count.get(oid, 0) + 1
        delta = obligation.payload.get("weight_delta")
        if delta is not None:
            key = obligation.payload.get("weight_key", obligation.target)
            self.local_state[key] = self.local_state.get(key, 0.0) + float(delta)

    def _ack(self, obligation: Obligation, status: CustodyStatus) -> CustodyAck:
        return CustodyAck(
            obligation_id=obligation.obligation_id,
            target=self.agent_id,
            status=status,
            acked_at=self._clock_fn(),
        )
