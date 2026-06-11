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
