# Formal specification (TLA+)

`Abhyasa.tla` specifies the custody state machine of paper §4 with an abstract
adversarial channel, and `Abhyasa.cfg` configures TLC to check it.

## What is checked

**Safety invariants** (`INVARIANT Invariants`), at every reachable state:

- `TypeOK` — well-typed state.
- `AB2Persistence` — retransmission is bounded (`attempts <= MaxRetries + 1`).
- `AB3EffectivelyOnce` — the effect is applied at most once per obligation.
- `AB4FailSafe` — an `escalated` obligation has had `safe(O)` executed.
- `DeliverOrReport` — an admissible obligation is never in a terminal state
  outside {applied, declined, escalated} (no silent loss).
- `BenignSideBestEffort` — inadmissible obligations are never under custody.

**Liveness** (`PROPERTY DeliverOrReportLive`), under weak fairness on the
custodian step: every admissible obligation eventually reaches `applied`,
`declined`, or `escalated`.

The channel is adversarial: any delivery or acknowledgment may be lost
(`LoseAndRetry`), and an application's acknowledgment may be lost after the
receiver has applied (`ApplyButAckLost`, which exercises AB-3 idempotency). The
deadline and bounded retry drive the AB-4 fail-safe.

## Run

Requires Java and `tla2tools.jar` (TLA+ tools).

```bash
java -cp tla2tools.jar tlc2.TLC -config Abhyasa.cfg Abhyasa.tla
```

## Result

For the bounded instance in `Abhyasa.cfg` (`Obligations = {o1, o2, o3, o4}`,
`Admissible = {o1, o2, o3}`, `MaxRetries = 4`, `Deadline = 6`), TLC explores the
complete state space and reports no violation:

```
Model checking completed. No error has been found.
157120 states generated, 31250 distinct states found, 0 states left on queue.
The depth of the complete state graph search is 20.
```

(Note: in this sandbox, run TLC from a local directory such as `/tmp` — the
mounted filesystem can reject TLC's metadir cleanup, which is harmless but
prints a spurious rename error after checking completes.)

This exhaustively establishes the six safety invariants and the
deliver-or-report liveness property for the bounded model. A parametric proof
for unbounded `Obligations`/`MaxRetries`/`Deadline` (via TLAPS) is future work.
