# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Two-agent A2A custody demo over a simulated lossy channel (paper §4, §5).

An orchestrator must deliver a *corrective* Phala BeliefUpdate to a downstream
agent (agent-b) over an unreliable reverse channel. The demo walks four
scenarios and prints, for each, the terminal custody state and the resulting
principal-side state:

  1. Clean channel        -> applied (custody discharged on the wire).
  2. Lossy-but-reachable  -> applied after retries (AB-2), effect applied once.
  3. Total partition      -> escalated; principal-side down-weight runs (AB-4),
                             protecting the principal WITHOUT a reverse channel.
  4. Anumati consent lost -> escalated; authority fails closed.

It also shows the A2A discoverability surface: the AgentCard extension entry an
agent publishes so peers can find its custody endpoints.

Run (no extras required):

    python examples/two_agent_custody.py
    # or, without installing the package:
    PYTHONPATH=src python examples/two_agent_custody.py
"""

from __future__ import annotations

import json

from abhyasa.bindings.a2a import (
    A2AEndpoint,
    AbhyasaServiceRef,
    KindProfile,
    build_agent_card_extension,
)
from abhyasa.custody import Custodian, PrincipalState, Receiver
from abhyasa.custody.channel import ChannelConfig, LossyChannel
from abhyasa.instantiations import default_registry
from abhyasa.types import CustodyStatus, Obligation

LINE = "─" * 68


def corrective_update(obligation_id: str, delta: float = -0.4) -> Obligation:
    """A corrective Phala BeliefUpdate: the principal rejected this pathway."""
    return Obligation(
        obligation_id=obligation_id,
        kind="phala.belief_update",
        target="agent-b",
        payload={"weight_delta": delta, "weight_key": "routing.agent_b.preference"},
        deadline_seconds=86400,
        max_retries=6,
        created_at="2026-06-09T10:00:00+00:00",
    )


def consent_revocation(obligation_id: str) -> Obligation:
    """A binary Anumati consent revocation."""
    return Obligation(
        obligation_id=obligation_id,
        kind="anumati.consent",
        target="agent-c",
        payload={"decision": "revoke", "scope": "calendar.write"},
        deadline_seconds=3600,
        max_retries=4,
        created_at="2026-06-09T10:00:00+00:00",
    )


def run_scenario(
    title: str,
    obligation: Obligation,
    channel_config: ChannelConfig,
    decision: CustodyStatus = CustodyStatus.APPLIED,
) -> None:
    registry = default_registry()
    principal_state = PrincipalState()
    receiver = Receiver(obligation.target, lambda _o: decision)
    # The downstream agent is reached as an A2A endpoint (JSON wire round-trip).
    endpoint = A2AEndpoint(receiver)
    custodian = Custodian(
        registry=registry,
        principal_state=principal_state,
        channel=LossyChannel(channel_config),
    )

    outcome = custodian.transfer(obligation, endpoint)

    print(LINE)
    print(f"{title}")
    print(
        f"  obligation     {obligation.obligation_id}  "
        f"({obligation.kind}, target={obligation.target})"
    )
    print(
        f"  channel        drop={channel_config.drop_prob} "
        f"dup={channel_config.duplicate_prob} "
        f"ack_drop={channel_config.ack_drop_prob} seed={channel_config.seed}"
    )
    print(f"  terminal       {outcome.terminal.value.upper()}  "
          f"(attempts={outcome.attempts}, discharged={outcome.discharged})")
    print(f"  applied_once   {receiver.applied_count(obligation.obligation_id)} "
          f"(effectively-once: must be <= 1)")
    if principal_state.routing_weights:
        print(f"  routing_weights{'':1}{principal_state.routing_weights}")
    if principal_state.authorizations:
        print(f"  authorizations {principal_state.authorizations}")
    if principal_state.escalations:
        esc = principal_state.escalations[0]
        print(f"  escalation     {esc['type']} after {esc['attempts']} attempts")


def show_agent_card_extension() -> None:
    ref = AbhyasaServiceRef(
        version="1.0.0",
        custody_ack_endpoint="https://orchestrator.example.com/abhyasa/custody_ack",
        supported_kinds=[
            KindProfile(
                kind="phala.belief_update",
                obligation_endpoint="https://agent-b.example.com/phala/belief_updates",
                deadline_seconds=86400,
                backoff_cap_seconds=3600,
                max_retries=48,
            ),
            KindProfile(
                kind="anumati.consent",
                obligation_endpoint="https://agent-b.example.com/anumati/decisions",
                deadline_seconds=3600,
                backoff_cap_seconds=600,
                max_retries=16,
            ),
        ],
    )
    print(LINE)
    print("A2A discoverability — AgentCard.capabilities.extensions[] entry:")
    print(json.dumps(build_agent_card_extension(ref), indent=2))


def main() -> None:
    print("Abhyasa — two-agent custody transfer over a lossy channel\n")

    run_scenario(
        "1. Clean channel — corrective update applied on the wire",
        corrective_update("bu-clean"),
        ChannelConfig(seed=1),
    )
    run_scenario(
        "2. Lossy but reachable — applied after retries (AB-2), applied once (AB-3)",
        corrective_update("bu-lossy"),
        ChannelConfig(drop_prob=0.6, duplicate_prob=0.4, ack_drop_prob=0.4, seed=2),
    )
    run_scenario(
        "3. Total partition — escalated; principal-side down-weight runs (AB-4)",
        corrective_update("bu-partition"),
        ChannelConfig(drop_prob=1.0, seed=3),
    )
    run_scenario(
        "4. Anumati consent lost — authority fails closed (binary polarity)",
        consent_revocation("cn-partition"),
        ChannelConfig(drop_prob=1.0, seed=4),
    )
    show_agent_card_extension()
    print(LINE)
    print(
        "\nDeliver-or-report: every admissible obligation above ended applied, "
        "declined,\nor escalated — never silent loss — and the principal was "
        "protected locally\nwhenever the channel defeated delivery."
    )


if __name__ == "__main__":
    main()
