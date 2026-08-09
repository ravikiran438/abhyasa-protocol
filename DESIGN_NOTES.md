# Abhyasa — Design Notes

Design rationale and verification detail kept out of the specification paper to
keep its body lean. None of this changes the specification; each section
supports reproducibility or records a scoping decision. Section references
(§4.2, §5, etc.) are to the Abhyasa paper.

## 1. TLC model bounds and result

The TLA+ model (`specification/Abhyasa.tla`) is checked with **TLC version
2.19** at `Obligations` = 4 (three admissible), `MaxRetries` = 4, `Deadline`
= 6, with one retry modeled as one logical tick. TLC explores the complete
state space (**31,250 distinct states, search depth 20**) and reports no
violation of the six safety invariants (`TypeOK`, `AB2Persistence`,
`AB3EffectivelyOnce`, `AB4FailSafe`, `DeliverOrReport`, `BenignSideBestEffort`)
or of the liveness property `DeliverOrReportLive`, under weak fairness on the
custodian step. Because obligations are independent, the instance covers the
concurrent interleavings of several in-flight transfers, including the
acknowledgment-arrives-as-the-deadline-expires ordering. The injected fault
model is: nondeterministic loss of the obligation before application; loss of
the acknowledgment after the receiver has applied (which forces redelivery and
exercises AB-3 idempotency); and the resulting duplicate delivery. Node crashes
and durable storage are not in the model; they are normative requirements on
implementations (AB-1 to AB-3), exercised by the crash-recovery tests in the
conformance suite (§4.2), and a crash-extended model is future work. Loss is
unbounded per attempt but bounded in aggregate by the deadline/retry
terminator, so the search terminates; reordering across distinct obligations is
covered by their free interleaving.

We argue, informally, that these bounds suffice for the protocol logic:
obligations share no state, so a custody transfer's correctness is
per-obligation modulo the channel adversary, and the chosen bounds exhaust
every distinct single-obligation interleaving within the retry/deadline horizon
(all loss, redelivery, and ack-versus-deadline orderings), while additional
obligations or larger horizons add product structure and longer-but-similar
runs. This argument is not a parametric proof; the guarantees should be read as
verified within these bounds, with the parametric claim deferred to a TLAPS
proof (future work).

At the implementation level, the same properties are fuzzed against the
reference code over **100,000 transfers** in a deterministic simulation harness
(`tests/test_fuzz_deliver_or_report.py`): a fixed master seed drives the sweep
and derives a per-transfer channel seed, and time is a logical clock advanced
only by the backoff schedule, with no wall-clock dependency, so runs are
reproducible from the seed. For each transfer, message-drop, duplication, and
acknowledgment-drop rates are drawn independently and uniformly from [0, 1);
each delivery attempt (round trip) within that transfer then makes an
independent Bernoulli trial against each rate. Retries within a transfer
therefore face a correlated (shared-rate) channel, which stresses the backoff
schedule under persistently bad conditions, while attempts remain independent
trials. Each transfer uses backoff base 1, multiplier 2, cap 64, and deadline
600 in logical seconds, so the deadline rather than the retry count is the
binding terminator (15 attempts span it); the schedule's shape is preserved
while wall-clock latency and jitter are abstracted away. The uniform sweep is
an adversarial correctness stress that by construction spends half its mass on
severely degraded channels; it is not a model of typical operating conditions,
whose bursty loss and performance characteristics belong to the deferred
empirical study. The harness checks that the sweep exercises all three terminal
outcomes. The runnable demo (`examples/two_agent_custody.py`) is one
illustrative configuration of this same channel. No transfer terminates in
silent loss and application stays effectively-once. Of the 100,000 transfers,
52.6% terminated applied, 26.2% declined (the harness has receivers decline one
delivered obligation in three), and 21.2% escalated, at a mean of 6.3 delivery
attempts per transfer; under a sweep that spends half its mass on drop rates
above 50%, roughly one transfer in five exhausting its deadline and falling to
the fail-safe is the expected shape, not an operational projection.

## 2. Lost acknowledgment: over-protection, not split brain

If an obligation is applied by the receiver but its `CustodyAck` is lost, the
custodian reaches the deadline and applies `safe(O)`. This is conservative
over-protection, not divergence, because the two effects act on *disjoint*
state: the receiver adjusts its own belief/behavior weight, while `safe(O)`
adjusts the custodian's principal-side routing preference. No single quantity
is decremented twice. The fail-safe can only over-protect (the principal routes
less to an agent that did self-correct), never under-protect, and the
over-correction self-heals through the ordinary reinforcement loop; the
escalation makes it explicit. For a single obligation the effects do not
compound (custody terminates at the first escalation and AB-3 caps application
at once). Across many sequential obligations whose acknowledgments are all lost
to a persistent partition, each contributes one principal-side adjustment, so
over-protection can accumulate. It remains bounded: for Phala by the declared
weight-clipping range, so the routing weight cannot fall below its floor, and
for Anumati because fail-closed is idempotent (re-withholding an
already-withheld authority is a no-op). The same reinforcement loop reconverges
it once the partition heals.

Recovery differs by invariant. Phala over-protection self-heals automatically:
subsequent successful interactions raise the routing weight through the
reinforcement loop with no operator action. Anumati has no such automatic loop.
A spurious fail-closed (an over-denial after a *grant* timed out during a
partition) is recovered by re-issuing the grant, which the custody machine
delivers once connectivity returns; the escalation is the trigger for that
re-issue, whether operator-driven or by an automated re-grant policy. A
revocation that timed out, by contrast, is not spurious, because fail-closed is
the intended state, so nothing need be undone.

## 3. Pure computation vs. stateful application

`safe(O)` is a pure function returning an action descriptor; the custodian then
applies that descriptor to its own principal-side store. The two are distinct
in the reference implementation (`safe(O)` returns a value; a separate step
mutates the store). The application is a single-writer local update ordered
after the durable escalation record, so it inherits the custodian's
crash-recovery: on restart an escalation whose application did not complete is
re-applied idempotently (set-to-safe, not increment). It introduces no remote
failure mode, and the local application is modeled in the TLA+ spec (the
`protected` flag set by the escalation transition, checked by the `AB4FailSafe`
invariant).

## 4. Overhead

Relative to best-effort delivery, custody adds, per *admissible* obligation,
two durable write-ahead records (one at the custodian per AB-1, one at the
receiver per AB-3), one `CustodyAck`, and retransmissions only as the channel
forces them, capped by the deadline. Inadmissible and reinforcing obligations
take the unchanged best-effort path. Steady-state cost is therefore two durable
writes (one per endpoint) and one acknowledgment per admissible obligation. The
custodian's pending set is bounded by admission-rate × `deadline` (each
obligation leaves the set at its deadline at the latest), so a prolonged
partition grows it to that bound and no further; an implementation under load
applies admission control once the bound is approached. A measured
latency/throughput comparison against a best-effort baseline is future work.

## 5. Threat-model limits

Honest-but-unreliable excludes Byzantine agents. A strategic agent that *drops*
an obligation gains nothing over honest loss (AB-4 fires). A *false*
acknowledgment (`applied` without honoring the obligation) is outside the
model, and we do not claim to detect it. The same limit applies whether the
false acknowledgment is adversarial or an artifact of agent-internal failure:
an LLM-based receiver subverted by prompt injection, or one that acknowledges
and then loses the obligation to hallucination or context eviction, presents
the protocol with an `applied` that does not reflect actual application, and
Abhyasa makes no claim to distinguish the cases. Closing the gap between
*reported* and *actual* application requires attestation or trusted execution,
which we leave to future work. A signed, attested `CustodyAck`, for example one
carrying a Pramana claim attestation or backed by a trusted execution
environment, would carry evidence of application rather than a bare assertion,
sliding the model from honest-but-unreliable toward verifiable and extending
the guarantee across adversarial trust boundaries. Abhyasa (reliable delivery
of the obligation) and an attestation layer (verifiable proof of its
application) are complementary and compose in a single agent; we sketch this as
the integration path, not a contribution here. (Where the unhonored obligation
keeps producing observable bad outcomes, Phala's ordinary feedback *may*
re-derive a correction, but the framework does not rely on this.)

A strategic agent might also *delay* acknowledging a revocation, but for
*principal-mediated* authority this gains nothing: that withhold is applied at
issuance (§5), independent of the ack, so delay only postpones the custodian's
escalation to the `deadline`. For authority a partitioned agent can exercise
autonomously, `safe(O)` reports rather than prevents; the mitigation is to
bound such capabilities with lifetimes shorter than `deadline` — time-bound
leases (Gray & Cheriton 1989) under the usual bounded-clock-skew assumption, so
authority lapses by timeout. Capability systems such as Macaroons (Birgisson et
al. 2014) face the same revocation-propagation problem, as do zero-trust
architectures, which address it by *continuous re-evaluation* (short-lived
tokens re-checked at a policy enforcement point) rather than by reliably
delivering the revocation. The two are complementary: re-evaluation bounds
exposure by expiry, while Abhyasa guarantees the revocation signal is
delivered-or-escalated rather than silently dropped.

## 6. Relation to application-level reliability patterns

AB-1's durable pending set is the *transactional-outbox* pattern (Richardson,
*Microservices Patterns*, 2018); AB-4's local protective action is a
*compensating transaction* in the sense of Sagas (Garcia-Molina & Salem, 1987),
differing in that it is triggered by non-confirmation over an unreliable channel
rather than by an aborted local step.


## Paper v1.1 alignment

These clarifications land in the paper's arXiv revision (v1.1); the reference
implementation aligns as follows.

**Supersession guard.** `safe(O)` is a pure function of the obligation, but
its application is not unconditional: a revocation can time out after the
principal has issued a later decision on the same governed key, and blindly
applying the older obligation's fail-safe would regress principal-side state
past the principal's own newer decision. Principal-side application is
therefore last-writer-wins per governed key: obligations over set-semantic
state carry an issuance `sequence` (optional on the wire; guard skipped when
absent), `PrincipalState` records the highest sequence applied per key, and
a lower-sequence action applies nothing while the escalation still fires —
deliver-or-report is about the loss being reported, not a stale action being
applied. The principal's own decisions (`apply_decision`) pass through the
same guard, so per-key ordering is total regardless of which path applies
first. Phala's additive weight deltas are commutative and unguarded by
design. Covered by `test_superseded_safe_action_does_not_regress_newer_decision`
and companions.

The guard is two-sided. AB-3's idempotency is keyed on `obligation_id` and
orders nothing between distinct obligations, so out-of-order delivery (or a
stale obligation's late retry landing after its successor) could apply an
older decision over a newer one at the receiver. The receiver therefore
records the highest sequence applied per governed key and declines a
lower-sequence arrival as superseded; the custodian's default `safe(O)` on
that decline carries the stale sequence and is dropped by the principal-side
guard, so neither side regresses. Covered by
`test_receiver_declines_stale_out_of_order_obligation` and
`test_two_sided_guard_composes_without_regression`.

**Acknowledgments are not session state (MCP).** The deferred-ack push
notification is a latency optimization, not the delivery mechanism. The
receiver persists obligation status in the ledger AB-3 already requires, and
the custodian's AB-2 schedule recovers the ack on whatever session exists
next (redelivery or status query, both keyed on `obligation_id`). The
identifier that spans sessions is the `obligation_id`; no session
reassociation protocol exists or is needed.

**`safe(O)` on `declined`.** v1.0 discharged custody on a decline with no
principal-side protection: the receiver accountably kept the last authority
it saw, and the principal's exposure matched a lost delivery, only visibly
so. v1.1 makes this normative as a disjunction: the custodian MUST NOT treat
a decline as equivalent to `applied` — it MUST either apply `safe(O)` (the
default) or surface the decline, with the receiver's stated reason, for an
explicit principal decision. No AB-4 escalation either way; the decline
itself is the accountable record. The discretion exists because a receiver
may decline precisely when the obligation is moot (superseded, expired,
inapplicable), where an automatic state change would be wrong; ignoring the
decline is what is never permitted. Where `safe(O)` already stands (a
fail-closed withhold applied unconditionally at decision time, as in
Anumati), the default path is an idempotent re-assertion. Implemented in
`custody/machine.py`; `test_declined_applies_safe_action_without_escalation`
covers it.

**Deadlines bind both sides.** A receiver MUST NOT apply an obligation whose
deadline has passed: an expired pending or deferred obligation is declined
with expiry as the reason, which closes the race in which a slow receiver
applies after the custodian has escalated and run the fail-safe. A late
`applied` that arrives anyway (clock skew, an ack in flight at expiry) is
logged for reconciliation, and the combined state — fail-safe on the
principal side, obligation applied on the receiver side — errs on the
restrictive side by the polarity admissibility requires, so the race is
bounded to over-protection. `Receiver` takes an optional logical clock and
enforces expiry; `test_receiver_declines_expired_obligation` covers it.

**Deferred acknowledgments.** `deferred` extends neither the deadline nor the
retry budget; the custodian keeps retrying under AB-2, and a receiver crash
while deferring is handled by redelivery plus AB-3 idempotency. What
`deferred` changes is the custodian's knowledge: the escalation records a
responsive-but-stuck receiver ("receiver responsive but deferring") rather
than an unreachable one. The backoff schedule continues unchanged on
`deferred` — resetting it for a reachable receiver would invite a retry storm
that exhausts the retry budget prematurely and escalates while the receiver
is still processing.

**The dual-write boundary of AB-3.** The atomic-commit requirement is exact
where the effect is state the receiver owns. Where the effect is external and
non-transactional (a remote API call, a tool execution), the
`obligation_id` doubles as an idempotency key the receiver MUST propagate to
the external system. Most governance obligations are additionally idempotent
by content — a revocation, a policy replacement, or a weight clamp sets state
rather than incrementing it — and for obligations that are neither, the
receiver SHOULD record a durable intent before executing the effect, so a
redelivery resumes a known in-doubt effect rather than re-executing blindly.
An intent record narrows the doubt but does not resolve it: on recovery the
receiver settles it by querying the external system where queryable, and
otherwise MUST surface the in-doubt effect for reconciliation rather than
silently choosing a side. Effectively-once is therefore claimed only under
one of the three declared conditions (receiver-owned state, honored
idempotency key, set-semantic obligation); outside them custody still
guarantees delivery is never silently lost, and no more.
The reference `Receiver` models the receiver-owned case; the intent-record
pattern is deliberately left to integrations, which own the external systems.

**Consent grants are inadmissible (correction).** v1.0 classified Anumati as
admissible as a whole. Under AC-1 this was inconsistent with the treatment of
OAuth token issuance: a grant's loss is the benign default (the agent lacks
authority, cannot act, and re-requests), so grants travel best-effort while
revocations and other restrictive decisions remain under custody. Implemented
in `instantiations/anumati.py`; obligations that do not state a decision are
treated as restrictive, since custody of a restriction is the safe default.

**`max_retries` sizing.** The paper's AB-2 now states the sizing rule the
`KindProfile` validator has enforced all along: retries must span the
deadline, so the deadline — not the retry count — is the binding terminator.

**Envelope-before-request ordering (MCP).** A server that supports Abhyasa
MUST process the custody envelope in `params._meta` before executing the
request that carries it, so a tool call never runs under authority the
obligation it carries has just withdrawn. A server that does not support
Abhyasa ignores `_meta` and never acknowledges — which is safe rather than
silent: custody is discharged only by an explicit `CustodyAck`, so the
transfer runs its AB-2 schedule into the AB-4 fail-safe, and
deliver-or-report holds against a receiver that does not speak the protocol
at all. Binding-level; no change to the transport-agnostic core.
