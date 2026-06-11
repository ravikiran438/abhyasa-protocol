# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Simulated lossy channel for exercising the custody machine (paper §4, §5).

Exactly-once delivery is impossible over a channel that may drop or delay any
message (Two Generals; FLP). This module models such a channel so the
deliver-or-report guarantee can be checked under adversarial loss: messages may
be dropped (obligation lost or ack lost), duplicated (redelivery — exercises
AB-3 idempotency), or delayed past the deadline.

Two channels are provided: :class:`LossyChannel` (seeded random, for fuzzing)
and :class:`ScriptedChannel` (deterministic outcome list, for unit tests).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional, Protocol

from abhyasa.types.custody_ack import CustodyAck
from abhyasa.types.obligation import Obligation


class Endpoint(Protocol):
    """Anything that can apply an obligation and return a CustodyAck."""

    def deliver(self, obligation: Obligation) -> CustodyAck: ...


class Channel(Protocol):
    """Transports an obligation to an endpoint and returns the ack, or None.

    Returning ``None`` models *either* the obligation never arriving *or* the
    ack being lost on the return path — from the custodian's vantage the two
    are indistinguishable (Two Generals), and both leave custody undischarged.
    """

    def round_trip(
        self, obligation: Obligation, endpoint: Endpoint
    ) -> Optional[CustodyAck]: ...


@dataclass
class ChannelConfig:
    """Loss profile. Probabilities are per round-trip, in [0, 1]."""

    drop_prob: float = 0.0
    duplicate_prob: float = 0.0
    ack_drop_prob: float = 0.0
    seed: Optional[int] = None


class LossyChannel:
    """Seeded random channel. Deterministic for a fixed seed."""

    def __init__(self, config: Optional[ChannelConfig] = None) -> None:
        self.config = config or ChannelConfig()
        self._rng = random.Random(self.config.seed)

    def round_trip(
        self, obligation: Obligation, endpoint: Endpoint
    ) -> Optional[CustodyAck]:
        # The obligation itself is dropped before reaching the endpoint.
        if self._rng.random() < self.config.drop_prob:
            return None
        ack = endpoint.deliver(obligation)
        # Duplicate redelivery: the endpoint sees the obligation again. A
        # correct receiver (AB-3) applies at most once and re-acks applied.
        if self._rng.random() < self.config.duplicate_prob:
            ack = endpoint.deliver(obligation)
        # The acknowledgment is lost on the return path.
        if self._rng.random() < self.config.ack_drop_prob:
            return None
        return ack


@dataclass
class Hop:
    """One scripted round-trip outcome.

    delivered=False  -> obligation dropped (endpoint never sees it).
    duplicate=True   -> endpoint.deliver is called twice.
    ack_lost=True    -> endpoint applied, but the custodian gets no ack.
    """

    delivered: bool = True
    duplicate: bool = False
    ack_lost: bool = False


class ScriptedChannel:
    """Deterministic channel driven by a list of :class:`Hop` outcomes.

    Once the script is exhausted every further round-trip drops (returns None),
    so a custodian with retries left will run to its deadline and escalate.
    """

    def __init__(self, hops: List[Hop]) -> None:
        self._hops = list(hops)
        self._i = 0

    def round_trip(
        self, obligation: Obligation, endpoint: Endpoint
    ) -> Optional[CustodyAck]:
        if self._i >= len(self._hops):
            return None
        hop = self._hops[self._i]
        self._i += 1
        if not hop.delivered:
            return None
        ack = endpoint.deliver(obligation)
        if hop.duplicate:
            ack = endpoint.deliver(obligation)
        if hop.ack_lost:
            return None
        return ack
