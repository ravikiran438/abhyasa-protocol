# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Durable custody: the persistence that AB-1, AB-2, and AB-3 require.

The abstract machine (specification/Abhyasa.tla) verifies the protocol logic
under channel faults; durability is a normative obligation on implementations
(paper §4, §4.2). This module supplies the reference form of that obligation:

  Custodian side (AB-1/AB-2): a write-ahead pending set. The obligation is
  persisted *before* the first send and marked terminal only when custody is
  discharged, so a custodian that crashes mid-transfer finds the obligation
  pending on restart and re-enters the retry loop (a crash delays rather than
  abandons a transfer).

  Receiver side (AB-3): an applied-id ledger committed in the *same atomic
  write* as the obligation's effect, so a receiver that crashes between
  application and acknowledgment does not reapply on redelivery — the
  redelivered obligation hits the persisted ledger and is re-acked ``applied``
  without effect.

Storage is a single JSON file per store, written atomically (temp file +
``os.replace``), which is sufficient for the conformance suite and the demo;
a production deployment would substitute any transactional store with the
same two commit points.

Note on the recovered deadline: this reference custodian restarts the
``deadline_seconds`` window from recovery time. A production custodian would
persist the absolute deadline and resume the remaining window.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from abhyasa.custody.channel import Endpoint
from abhyasa.custody.machine import Custodian, CustodyOutcome
from abhyasa.custody.receiver import DecisionFn, Receiver
from abhyasa.types.obligation import Obligation

PENDING = "pending"


class CrashSignal(Exception):
    """Raised by test harnesses to simulate a process dying mid-protocol."""


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write ``data`` to ``path`` atomically (temp file + rename)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


class CustodianStore:
    """Write-ahead pending set for the custodian (AB-1/AB-2)."""

    def __init__(self, path: os.PathLike | str) -> None:
        self._path = Path(path)

    def record_pending(self, obligation: Obligation) -> None:
        """Persist the obligation as pending. MUST precede the first send."""
        data = _read_json(self._path, {})
        data[obligation.obligation_id] = {
            "status": PENDING,
            "obligation": obligation.model_dump(mode="json"),
        }
        _atomic_write_json(self._path, data)

    def mark_terminal(self, obligation_id: str, terminal: str) -> None:
        """Record that custody was discharged (applied/declined/escalated)."""
        data = _read_json(self._path, {})
        if obligation_id in data:
            data[obligation_id]["status"] = terminal
            _atomic_write_json(self._path, data)

    def pending(self) -> List[Obligation]:
        """The undischarged obligations, for the recovery pass."""
        data = _read_json(self._path, {})
        return [
            Obligation.model_validate(rec["obligation"])
            for rec in data.values()
            if rec["status"] == PENDING
        ]


class ReceiverStore:
    """Applied-id ledger plus receiver state, committed in one atomic write
    (AB-3: the ledger and the effect share the commit)."""

    def __init__(self, path: os.PathLike | str) -> None:
        self._path = Path(path)

    def load(self) -> Tuple[Set[str], Dict[str, int], Dict[str, float]]:
        data = _read_json(
            self._path, {"applied": [], "apply_count": {}, "local_state": {}}
        )
        return set(data["applied"]), dict(data["apply_count"]), dict(data["local_state"])

    def commit(
        self,
        applied: Set[str],
        apply_count: Dict[str, int],
        local_state: Dict[str, float],
    ) -> None:
        _atomic_write_json(
            self._path,
            {
                "applied": sorted(applied),
                "apply_count": apply_count,
                "local_state": local_state,
            },
        )


class DurableReceiver(Receiver):
    """A Receiver whose AB-3 ledger and effect commit atomically and survive
    a crash. On construction it recovers ledger and state from its store."""

    def __init__(
        self,
        agent_id: str,
        decide: Optional[DecisionFn] = None,
        *,
        store: ReceiverStore,
        clock_fn=None,
    ) -> None:
        kwargs = {"clock_fn": clock_fn} if clock_fn is not None else {}
        super().__init__(agent_id, decide, **kwargs)
        self._store = store
        self._applied, self.apply_count, self.local_state = store.load()

    def _apply_once(self, obligation: Obligation) -> None:
        # Effect, ledger entry, and counters land in one atomic write: a crash
        # either precedes the commit (nothing applied, redelivery applies) or
        # follows it (applied and remembered, redelivery is a no-op re-ack).
        super()._apply_once(obligation)
        self._applied.add(obligation.obligation_id)
        self._store.commit(self._applied, self.apply_count, self.local_state)


class DurableCustodian:
    """Wraps a :class:`Custodian` with the AB-1/AB-2 write-ahead pending set.

    ``transfer`` persists admissible obligations before the first send and
    marks them terminal on discharge; ``recover`` re-enters the retry loop for
    every obligation a crash left pending. Inadmissible obligations are
    best-effort (no custody) and are not persisted.
    """

    def __init__(self, *, custodian: Custodian, store: CustodianStore) -> None:
        self.custodian = custodian
        self.store = store

    def transfer(self, obligation: Obligation, endpoint: Endpoint) -> CustodyOutcome:
        if not self.custodian.registry.is_admissible(obligation):
            return self.custodian.transfer(obligation, endpoint)
        self.store.record_pending(obligation)  # WAL: before the first send
        outcome = self.custodian.transfer(obligation, endpoint)
        self.store.mark_terminal(obligation.obligation_id, outcome.terminal.value)
        return outcome

    def recover(self, endpoint: Endpoint) -> List[CustodyOutcome]:
        """Resume every pending transfer. Run on restart, before new work."""
        outcomes = []
        for obligation in self.store.pending():
            outcome = self.custodian.transfer(obligation, endpoint)
            self.store.mark_terminal(obligation.obligation_id, outcome.terminal.value)
            outcomes.append(outcome)
        return outcomes
