# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""A2A binding: AgentCard discoverability + in-process wire endpoint (paper §4, §5).

Discoverability. An agent advertises Abhyasa support by an entry in
``AgentCard.capabilities.extensions[]`` whose ``uri`` equals
``ABHYASA_EXTENSION_URI``. The body of that entry deserializes to
:class:`AbhyasaServiceRef`, which tells a caller where to POST obligations,
where custody acks are returned, and the custodian's deadline / retry profile.
This mirrors phala-protocol's ``PhalaServiceRef`` and the ``v1/manifest.json``
extension descriptor.

Wire. :class:`A2AEndpoint` is an in-process stand-in for a remote A2A peer
exposing ``POST /abhyasa/obligations``. It round-trips obligations and acks
through JSON so the documented wire contract is actually exercised, then
delegates application to a :class:`~abhyasa.custody.receiver.Receiver`. Because
it duck-types as a channel :class:`~abhyasa.custody.channel.Endpoint`, the same
:class:`~abhyasa.custody.machine.Custodian` drives it over a lossy channel
unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from abhyasa.custody.receiver import Receiver
from abhyasa.types.custody_ack import CustodyAck
from abhyasa.types.obligation import Obligation

# Stable identifier published on AgentCard.capabilities.extensions[].uri.
ABHYASA_EXTENSION_URI = "https://ravikiran438.github.io/abhyasa-protocol/v1"


class KindProfile(BaseModel):
    """Per-kind custody delivery profile inside an :class:`AbhyasaServiceRef`.

    Custody is a cross-cutting concern, so the delivery profile is declared once
    per governance *kind* an agent carries under custody — not duplicated into
    each domain protocol's own AgentCard block. Each kind tunes its own
    deadline (e.g. a Phala corrective update at 24 h, an Anumati consent at 1 h).
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    kind: str = Field(
        ..., min_length=1, description="Obligation kind, e.g. 'phala.belief_update'."
    )
    obligation_endpoint: str = Field(
        ...,
        description=(
            "HTTPS URL where obligations of this kind are POSTed under custody."
        ),
    )
    deadline_seconds: int = Field(
        ..., gt=0, description="AB-1 custody deadline for this kind."
    )
    max_retries: int = Field(
        ...,
        ge=0,
        description=(
            "AB-2 retransmission bound; MUST be large enough that the capped "
            "exponential backoff spans deadline_seconds (the deadline, not the "
            "retry count, is the binding terminator)."
        ),
    )
    backoff: str = Field(
        default="exponential",
        description="Retry backoff strategy. Only 'exponential' is defined in v1.",
    )
    backoff_base_seconds: float = Field(
        default=1.0, gt=0, description="Initial backoff interval."
    )
    backoff_cap_seconds: int = Field(
        ...,
        gt=0,
        description="Backoff cap; kept below the deadline so several attempts fall within it.",
    )

    @model_validator(mode="after")
    def _retries_span_deadline(self) -> "KindProfile":
        # AB-2 coherence: the capped exponential backoff must span the deadline,
        # so the deadline (not the retry count) terminates the transfer. This
        # rejects the classic incoherent profile (e.g. max_retries=6 with a
        # 24 h deadline, which would escalate ~2 minutes in).
        elapsed = 0.0
        needed = 0
        while elapsed < self.deadline_seconds and needed < 1_000_000:
            needed += 1
            elapsed += min(
                self.backoff_cap_seconds,
                self.backoff_base_seconds * (2 ** (needed - 1)),
            )
        if self.max_retries < needed:
            raise ValueError(
                f"max_retries={self.max_retries} too small for "
                f"deadline_seconds={self.deadline_seconds} at "
                f"backoff_cap_seconds={self.backoff_cap_seconds}: the capped "
                f"backoff needs ~{needed} attempts to span the deadline (AB-2); "
                f"set max_retries >= {needed}."
            )
        return self


class AbhyasaServiceRef(BaseModel):
    """Abhyasa-specific fields contributed to an A2A AgentCard.

    Validators detect Abhyasa support by the presence of an entry in
    ``capabilities.extensions[]`` whose ``uri`` equals ``ABHYASA_EXTENSION_URI``.
    The body of that entry SHOULD deserialize to this model. The custody layer is
    advertised once per agent: the agent-level ``custody_ack_endpoint`` plus one
    :class:`KindProfile` per governance kind carried under custody. Domain
    protocols (Phala, Anumati, OAuth, ...) carry no custody fields of their own.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    version: str = Field(
        ...,
        description="Abhyasa protocol semver this agent implements (e.g. '1.0.0').",
    )
    custody_ack_endpoint: str = Field(
        ...,
        description=(
            "Agent-level HTTPS URL where this agent (as custodian) receives "
            "asynchronous CustodyAcks for the deferred discharge path."
        ),
    )
    supported_kinds: List[KindProfile] = Field(
        ...,
        min_length=1,
        description=(
            "Per-kind custody delivery profiles; one entry per governance kind "
            "this agent carries under custody."
        ),
    )


def build_agent_card_extension(ref: AbhyasaServiceRef) -> Dict[str, Any]:
    """Build the ``capabilities.extensions[]`` entry advertising Abhyasa."""
    return {
        "uri": ABHYASA_EXTENSION_URI,
        "description": (
            "Abhyasa custody transfer of governance obligations "
            "(deliver-or-report)."
        ),
        "params": ref.model_dump(),
    }


def parse_agent_card_extension(
    extensions: List[Dict[str, Any]],
) -> Optional[AbhyasaServiceRef]:
    """Return the AbhyasaServiceRef from an AgentCard's extensions, or None."""
    for ext in extensions:
        if ext.get("uri") == ABHYASA_EXTENSION_URI:
            return AbhyasaServiceRef.model_validate(ext.get("params", {}))
    return None


class A2AEndpoint:
    """In-process A2A peer exposing the obligation POST path.

    JSON-serializes the obligation on the way in and the ack on the way out, so
    the wire contract is genuinely exercised, then delegates to ``receiver``.
    Duck-types as a custody-channel :class:`Endpoint`.
    """

    def __init__(self, receiver: Receiver) -> None:
        self.receiver = receiver

    def deliver(self, obligation: Obligation) -> CustodyAck:
        # Inbound: what the custodian POSTs to /abhyasa/obligations.
        wire_in = obligation.model_dump_json()
        received = Obligation.model_validate_json(wire_in)
        ack = self.receiver.deliver(received)
        # Outbound: 200 + CustodyAck (sync) or async POST to custody_ack_endpoint.
        wire_out = ack.model_dump_json()
        return CustodyAck.model_validate_json(wire_out)

    # Explicit HTTP-shaped alias for readers who want the POST framing.
    def post_obligation(self, obligation: Obligation) -> tuple[int, str]:
        ack = self.deliver(obligation)
        return 200, ack.model_dump_json()
