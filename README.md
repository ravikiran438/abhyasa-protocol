# Abhyasa Protocol

**Custody Transfer of Governance Obligations over Unreliable Agent Channels**

Reference implementation for the Abhyasa framework. Agent transport bindings
deliver *messages*; Abhyasa delivers the *governance obligation* a message
carries — a consent decision, a corrective welfare signal — under a
**deliver-or-report** guarantee: every admissible obligation is applied,
explicitly declined, or escalated to the principal, and is *never silently
lost*, even over a channel that may drop, delay, or duplicate any message.

Guaranteed delivery is impossible over an unreliable channel (Two Generals;
FLP), so Abhyasa does not attempt it. It lifts the custody-transfer mechanism of
delay-tolerant networking from opaque bundles to governance obligations, pairs
at-least-once delivery with idempotent application (effectively-once), and adds
a **principal-side fail-safe** that holds without a working reverse channel.

The implementation provides frozen Pydantic models with field-level bounds,
runtime validators, an MCP stdio server, an A2A AgentCard extension
(`v1/manifest.json`), and a pytest conformance suite.

## Layout

```
src/abhyasa/
  types/            Obligation, CustodyAck, SafeAction (frozen Pydantic models)
  polarity.py       safe(O) + AC-1 admissibility registry
  custody/          AB-1..AB-4 state machine, lossy channel, receiver, principal state
  instantiations/   anumati (binary, fail-closed), phala (valence-signed, corrective-only), oauth (token revocation)
  validators/       AC-1 admissibility check for obligations received over the wire
  bindings/a2a.py   AbhyasaServiceRef AgentCard extension + in-process A2A endpoint
  mcp_server/       stdio MCP server (validators + custody-transfer simulation)
v1/                 manifest.json (A2A discoverability), SPEC.md, README.md
examples/           runnable two-agent A2A custody demo over a lossy channel
specification/      Abhyasa.tla / .cfg — TLA+ invariants (proof deferred, see below)
tests/              conformance suite (see invariant mapping below)
```

## Framework

An **Obligation** carries a governance constraint and a `kind` selecting its
instantiation. The polarity registry answers two questions for each kind:

- **AC-1 (admissibility):** does the obligation declare a fail-safe polarity
  `safe(O)`? If not, it is inadmissible and travels best-effort.
- **safe(O):** the pure, principal-side default applied when the obligation is
  not confirmed delivered.

The **Custodian** drives an admissible obligation to a terminal state:

| Invariant | Behaviour |
|---|---|
| AB-1 Custody | Retain responsibility until an `applied`/`declined` ack or the deadline. |
| AB-2 Persistence | On timeout, retry under bounded exponential backoff up to `max_retries`. |
| AB-3 Idempotency | Receiver applies at most once, keyed on `obligation_id`. |
| AB-4 Fail-safe | On deadline without `applied`/`declined`, run `safe(O)` on principal-side state and emit an escalation. |

**Deliver-or-report:** every admissible obligation terminates as `applied`,
`declined`, or `escalated` — never silent loss.

### Instantiations

| Invariant | Polarity | `safe(O)` |
|---|---|---|
| Anumati (consent) | binary | withhold the action — fail-closed |
| Phala, corrective (`weight_delta < 0`) | signed | down-weight principal-side routing to the target |
| Phala, reinforcing (`weight_delta ≥ 0`) | signed | best-effort; not carried under custody |
| OAuth, token revocation | binary | authorization server stops honoring the token — fail-closed |
| OAuth, token issue/refresh | binary | best-effort; not carried under custody |

The Phala binding implements the Phala instantiation (paper §5): corrective
updates (valence < 0) are admissible and carried under custody (AB-1–AB-4);
reinforcing updates are best-effort. OAuth is a third, standard
(non-self-authored) instantiation included to show the admissible class is not
limited to the paper's own protocols: a token revocation is admissible and
fail-closed; issue/refresh is benign and best-effort.

## Install & run

Requires Python ≥ 3.12.

```bash
pip install -e '.[test,mcp]'      # editable install with test + MCP extras

pytest -q                         # run the conformance suite
python -m abhyasa.mcp_server --doctor   # structural self-check of the MCP server
python -m abhyasa.mcp_server            # launch the stdio MCP server
abhyasa-mcp                             # same, via the installed console script
```

(If your interpreter is older than 3.12, run the suite without installing the
package: `PYTHONPATH=src pytest -q`.)

### Try it

```bash
python examples/two_agent_custody.py   # two-agent custody demo over a lossy channel
```

It walks four scenarios — clean delivery, lossy-but-reachable (retries +
effectively-once), total partition (escalation + principal-side down-weight),
and a lost Anumati consent (fail-closed) — and prints the A2A AgentCard
extension entry.

### Formal model

`specification/Abhyasa.tla` specifies the custody state machine with an
adversarial channel and is **model-checked with TLC**: for a bounded instance
it exhaustively verifies the six safety invariants (including `DeliverOrReport`)
and the `DeliverOrReportLive` liveness property — 31,250 distinct states, no
violation. See `specification/README.md` for how to run it. The pytest suite
exercises the same properties empirically over a seeded lossy channel; a
parametric (unbounded) proof via TLAPS is future work.

### A2A discoverability

`v1/manifest.json` publishes the extension URI and the exact
`AbhyasaServiceRef` JSON Schema. Build and parse the AgentCard entry with
`abhyasa.bindings.a2a.build_agent_card_extension` /
`parse_agent_card_extension`. The manifest schema is asserted to match the live
model in `tests/test_extension_uris.py`.

### MCP tools

`validate_obligation`, `validate_custody_ack`, `validate_abhyasa_service_ref`,
`check_admissibility` (AC-1), `compute_safe_action` (safe(O)), and
`run_custody_transfer` — which simulates a transfer over a configurable lossy
channel and returns the terminal state, demonstrating deliver-or-report.

## Test → invariant map

Each test asserts a specific spec invariant. This mapping is the repository's
share of the paper's validation work (the mechanized TLA+/TLC proof is deferred
to companion work).

| Test | Asserts |
|---|---|
| `test_types.py::test_obligation_*` | Obligation field bounds (positive deadline, non-negative retries) |
| `test_types.py::test_custody_ack_*` | CustodyAck status ∈ {applied, declined, deferred} (§4) |
| `test_types.py::test_safe_action_*` | SafeAction shape; non-negative down-weight magnitude |
| `test_polarity.py::test_corrective_phala_is_admissible` | AC-1 / DEL-1: corrective update is custody-carried |
| `test_polarity.py::test_reinforcing_phala_is_inadmissible` | DEL-1 / DEL-5: reinforcing update is best-effort |
| `test_polarity.py::test_anumati_consent_is_admissible` | AC-1: consent always declares a polarity |
| `test_polarity.py::test_unknown_kind_is_inadmissible` | AC-1: undeclared polarity ⇒ not admissible |
| `test_polarity.py::test_phala_safe_is_principal_side_down_weight` | safe(O) for corrective Phala = DEL-4 down-weight |
| `test_polarity.py::test_anumati_safe_is_fail_closed` | safe(O) for Anumati = fail-closed |
| `test_custody_machine.py::test_ab1_clean_delivery_terminates_applied` | AB-1: clean delivery discharges custody |
| `test_custody_machine.py::test_ab2_retries_then_succeeds` | AB-2: retransmission after loss |
| `test_custody_machine.py::test_ab2_exponential_backoff_is_bounded` | AB-2: bounded exponential backoff |
| `test_custody_machine.py::test_ab3_duplicate_redelivery_applies_once` | AB-3: effectively-once under duplication |
| `test_custody_machine.py::test_ab3_redelivery_after_ack_loss_applies_once` | AB-3: re-ack applied without reapplication |
| `test_custody_machine.py::test_ab4_total_loss_escalates_and_applies_safe_action` | AB-4: fail-safe + escalation on total loss |
| `test_custody_machine.py::test_declined_is_a_delivered_outcome_not_escalation` | §4: declined discharges custody, no retry |
| `test_custody_machine.py::test_persistent_defer_escalates` | AB-1/AB-4: undischarged defer ⇒ escalation |
| `test_custody_machine.py::test_reinforcing_obligation_is_best_effort` | DEL-5: benign side not under custody |
| `test_deliver_or_report.py::test_admissible_obligation_never_silently_lost` | **Deliver-or-report** across 50 seeds × 5 loss levels |
| `test_deliver_or_report.py::test_total_partition_always_escalates` | AB-4: protection holds without a reverse channel |
| `test_deliver_or_report.py::test_lossless_channel_always_applies` | effectively-once under duplication, no loss |
| `test_deliver_or_report.py::test_declining_receiver_terminates_declined_under_loss` | non-silent terminal under loss for a declining receiver |
| `test_instantiations.py::test_phala_classification_by_sign` | DEL-1: classification by sign of weight_delta |
| `test_instantiations.py::test_anumati_unconfirmed_consent_fails_closed` | Anumati: unconfirmed consent ⇒ fail-closed |
| `test_instantiations.py::test_phala_corrective_lost_downweights_principal_side` | DEL-4: principal-side down-weight on loss |
| `test_instantiations.py::test_phala_reinforcing_is_never_under_custody` | DEL-5: reinforcing best-effort, no escalation |
| `test_oauth.py::test_revocation_is_admissible` | AC-1 on a standard protocol: token revocation is admissible |
| `test_oauth.py::test_unconfirmed_revocation_fails_closed` | OAuth: unconfirmed revocation ⇒ fail-closed (auth server stops honoring token) |
| `test_oauth.py::test_issue_is_best_effort_not_under_custody` | OAuth issue/refresh is benign ⇒ best-effort |
| `test_a2a_binding.py::test_agent_card_extension_round_trips` | A2A discoverability: build/parse the extension entry |
| `test_a2a_binding.py::test_a2a_endpoint_drives_custody_over_lossy_channel` | A2A wire: custody works over the JSON POST path |
| `test_extension_uris.py::test_manifest_payload_schema_matches_service_ref` | manifest schema == live AbhyasaServiceRef schema |
| `tests/mcp_server/test_tools.py::*` | MCP tool contract: validators, AC-1, safe(O), deliver-or-report |

## License

Apache-2.0. © 2026 Ravi Kiran Kadaboina.
