# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Large-scale randomized loss-injection fuzz of the deliver-or-report property.

This complements the exhaustive TLC model-checking of the abstract machine
(specification/Abhyasa.tla) by stress-testing the *reference implementation*
across many thousands of randomized channel configurations. Both the drop and
the duplication probability are swept per transfer (the latter answering the
"why a fixed duplication rate" question), and acknowledgment loss is swept
independently.

Default is 100,000 transfers; override with ABHYASA_FUZZ_N (e.g. 500000) for a
heavier run. Each transfer uses a short but coherent retry schedule (backoff
capped at 64 s, deadline 600 s, so the deadline binds after 15 attempts) to
keep the sweep fast while still exercising the full retry/escalation path.
"""

from __future__ import annotations

import os
import random

from abhyasa.custody import Custodian, PrincipalState, Receiver, TerminalState
from abhyasa.custody.channel import ChannelConfig, LossyChannel
from abhyasa.instantiations import default_registry
from abhyasa.types import CustodyStatus, Obligation

TERMINAL_NON_SILENT = {
    TerminalState.APPLIED,
    TerminalState.DECLINED,
    TerminalState.ESCALATED,
}

FUZZ_N = int(os.environ.get("ABHYASA_FUZZ_N", "100000"))


def _fuzz_obligation(oid: str, delta: float = -0.4) -> Obligation:
    # Short coherent schedule: with cap 64 s, 15 attempts span the 600 s
    # deadline (1+2+...+32 = 63 s, then 64 s steps; the 15th attempt fires at
    # t = 575 s), so the deadline, not the retry count, binds.
    return Obligation(
        obligation_id=oid,
        kind="phala.belief_update",
        target="agent-b",
        payload={"weight_delta": delta, "weight_key": "routing.agent_b.preference"},
        deadline_seconds=600,
        max_retries=64,
        created_at="2026-06-09T10:00:00+00:00",
    )


def test_fuzz_deliver_or_report_over_many_configs():
    """Across FUZZ_N randomized (drop, duplication, ack-loss) configs: every
    admissible obligation reaches a non-silent terminal, and application is
    effectively-once."""
    rng = random.Random(20260609)
    registry = default_registry()

    escalated = applied = declined = 0
    total_attempts = 0

    for i in range(FUZZ_N):
        drop = rng.random()          # full sweep [0, 1)
        duplicate = rng.random()     # full sweep [0, 1) — duplication varied
        ack_drop = rng.random()      # independent ack loss
        decision = rng.choice(
            [CustodyStatus.APPLIED, CustodyStatus.APPLIED, CustodyStatus.DECLINED]
        )

        principal_state = PrincipalState()
        receiver = Receiver("agent-b", lambda _o, d=decision: d)
        channel = LossyChannel(
            ChannelConfig(
                drop_prob=drop,
                duplicate_prob=duplicate,
                ack_drop_prob=ack_drop,
                seed=rng.randint(0, 2**31 - 1),
            )
        )
        custodian = Custodian(
            registry=registry,
            principal_state=principal_state,
            channel=channel,
            backoff_cap=64.0,
        )
        oid = f"bu-{i}"
        out = custodian.transfer(_fuzz_obligation(oid), receiver)

        # Safety: never silent loss.
        assert out.terminal in TERMINAL_NON_SILENT, (drop, duplicate, ack_drop)
        total_attempts += out.attempts
        # AB-3: effectively-once application regardless of duplication.
        assert receiver.applied_count(oid) <= 1
        # AB-4: an escalation always carries the principal-side protective action.
        if out.terminal is TerminalState.ESCALATED:
            assert len(principal_state.escalations) == 1
            assert principal_state.routing_weights["routing.agent_b.preference"] < 0
            escalated += 1
        elif out.terminal is TerminalState.APPLIED:
            applied += 1
        else:
            declined += 1

    # Sanity: the sweep actually exercised all three terminal outcomes, so the
    # property was tested on real branches rather than a single trivial path.
    assert escalated > 0 and applied > 0 and declined > 0

    # Terminal-outcome distribution and mean attempts, for reporting (run with
    # pytest -s to see it; paper Appendix A.1 cites these figures).
    print(
        f"\n[fuzz summary] n={FUZZ_N} seed=20260609 "
        f"applied={applied} ({100 * applied / FUZZ_N:.1f}%) "
        f"declined={declined} ({100 * declined / FUZZ_N:.1f}%) "
        f"escalated={escalated} ({100 * escalated / FUZZ_N:.1f}%) "
        f"mean_attempts={total_attempts / FUZZ_N:.2f}"
    )
