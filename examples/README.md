# Examples

## `two_agent_custody.py`

A runnable two-agent A2A custody demo. An orchestrator delivers a corrective
Phala BeliefUpdate (and an Anumati consent revocation) to a downstream agent
over a simulated lossy channel, across four scenarios:

1. **Clean channel** — applied on the first round-trip.
2. **Lossy but reachable** — applied after bounded retries (AB-2), effect
   applied exactly once despite duplication (AB-3).
3. **Total partition** — escalated; the principal-side routing down-weight runs
   (AB-4), protecting the principal without a working reverse channel.
4. **Anumati consent lost** — authority fails closed (binary polarity).

It also prints the AgentCard `capabilities.extensions[]` entry an agent
publishes for A2A discoverability.

```bash
python examples/two_agent_custody.py
# or, without installing the package:
PYTHONPATH=src python examples/two_agent_custody.py
```

No optional dependencies are required — the example uses only the standard
library and `abhyasa`.
