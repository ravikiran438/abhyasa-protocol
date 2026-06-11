------------------------------ MODULE Abhyasa ------------------------------
\* Copyright 2026 Ravi Kiran Kadaboina. Licensed under the Apache License, 2.0.
\*
\* TLA+ specification of the Abhyasa custody machine (paper §4), with an
\* abstract adversarial channel. TLC-checkable.
\*
\* Safety invariants (checked at every reachable state):
\*   TypeOK              well-typed state.
\*   AB2Persistence      retransmission is bounded: attempts <= MaxRetries+1.
\*   AB3EffectivelyOnce  the effect is applied at most once (keyed on the
\*                       obligation), under at-least-once delivery.
\*   AB4FailSafe         an escalated obligation has had safe(O) applied.
\*   DeliverOrReport     an admissible obligation is never in a terminal state
\*                       outside {applied, declined, escalated} (no silent loss).
\*   BenignSideBestEffort  inadmissible obligations are never placed under
\*                       custody nor escalated.
\*
\* Liveness (checked under weak fairness):
\*   DeliverOrReportLive every admissible obligation eventually reaches a
\*                       terminal discharge {applied, declined, escalated}.
\*
\* The channel is adversarial in that any delivery or acknowledgment may be
\* lost (LoseAndRetry) and an application's ack may be lost after the receiver
\* has applied (ApplyButAckLost, which exercises AB-3 idempotency); the
\* custodian's deadline and bounded retry (AB-1/AB-2) drive the fail-safe
\* (AB-4). Time is modeled as bounded logical ticks per obligation.

EXTENDS Naturals, FiniteSets, TLC

CONSTANTS
    Obligations,     \* Set of obligation identifiers
    Admissible,      \* Subset declaring a fail-safe polarity (AC-1)
    MaxRetries,      \* Per-obligation retransmission bound (AB-2)
    Deadline         \* Custody deadline in logical ticks (AB-1)

ASSUME Admissible \subseteq Obligations
ASSUME MaxRetries \in Nat
ASSUME Deadline \in Nat /\ Deadline > 0

States      == {"pending", "applied", "declined", "escalated", "best_effort"}
Terminal    == {"applied", "declined", "escalated", "best_effort"}
Discharged  == {"applied", "declined", "escalated"}

VARIABLES
    custody,        \* obligation -> state
    attempts,       \* obligation -> Nat (delivery attempts)
    applied_count,  \* obligation -> Nat (times the effect was applied)
    protected,      \* obligation -> BOOLEAN (safe(O) executed)
    clock           \* obligation -> Nat (elapsed ticks)

vars == <<custody, attempts, applied_count, protected, clock>>

TypeOK ==
    /\ custody       \in [Obligations -> States]
    /\ attempts      \in [Obligations -> 0..(MaxRetries + 1)]
    /\ applied_count \in [Obligations -> 0..1]
    /\ protected     \in [Obligations -> BOOLEAN]
    /\ clock         \in [Obligations -> 0..Deadline]

Init ==
    /\ custody       = [o \in Obligations |-> "pending"]
    /\ attempts      = [o \in Obligations |-> 0]
    /\ applied_count = [o \in Obligations |-> 0]
    /\ protected     = [o \in Obligations |-> FALSE]
    /\ clock         = [o \in Obligations |-> 0]

\* An admissible obligation still under custody.
Active(o) == o \in Admissible /\ custody[o] = "pending"

\* Successful delivery + idempotent application + ack returns (custody discharged).
Apply(o) ==
    /\ Active(o)
    /\ clock[o] < Deadline
    /\ applied_count' = [applied_count EXCEPT ![o] = IF @ = 0 THEN 1 ELSE @]
    /\ custody'       = [custody EXCEPT ![o] = "applied"]
    /\ UNCHANGED <<attempts, protected, clock>>

\* Receiver accountably refuses; a delivered outcome (custody discharged).
\* Only meaningful before any application has occurred (applied_count = 0).
Decline(o) ==
    /\ Active(o)
    /\ clock[o] < Deadline
    /\ applied_count[o] = 0
    /\ custody' = [custody EXCEPT ![o] = "declined"]
    /\ UNCHANGED <<attempts, applied_count, protected, clock>>

\* Obligation or ack dropped before the receiver applies: retry, advance time.
LoseAndRetry(o) ==
    /\ Active(o)
    /\ clock[o] < Deadline
    /\ attempts[o] <= MaxRetries
    /\ attempts' = [attempts EXCEPT ![o] = @ + 1]
    /\ clock'    = [clock EXCEPT ![o] = @ + 1]
    /\ UNCHANGED <<custody, applied_count, protected>>

\* Receiver APPLIED, but the ack was lost: custodian retries; a redelivery must
\* NOT reapply (AB-3). applied_count is capped at 1 across any number of these.
ApplyButAckLost(o) ==
    /\ Active(o)
    /\ clock[o] < Deadline
    /\ attempts[o] <= MaxRetries
    /\ applied_count' = [applied_count EXCEPT ![o] = IF @ = 0 THEN 1 ELSE @]
    /\ attempts'      = [attempts EXCEPT ![o] = @ + 1]
    /\ clock'         = [clock EXCEPT ![o] = @ + 1]
    /\ UNCHANGED <<custody, protected>>

\* Deadline reached or retries exhausted: execute safe(O), escalate (AB-4).
Escalate(o) ==
    /\ Active(o)
    /\ (clock[o] >= Deadline \/ attempts[o] > MaxRetries)
    /\ protected' = [protected EXCEPT ![o] = TRUE]
    /\ custody'   = [custody EXCEPT ![o] = "escalated"]
    /\ UNCHANGED <<attempts, applied_count, clock>>

\* Inadmissible obligation: delivered best-effort, never under custody.
BestEffort(o) ==
    /\ o \notin Admissible
    /\ custody[o] = "pending"
    /\ custody' = [custody EXCEPT ![o] = "best_effort"]
    /\ UNCHANGED <<attempts, applied_count, protected, clock>>

\* Once all obligations are terminal, the system stutters (prevents deadlock).
Terminating ==
    /\ \A o \in Obligations : custody[o] \in Terminal
    /\ UNCHANGED vars

Next ==
    \/ \E o \in Obligations :
         \/ Apply(o) \/ Decline(o) \/ LoseAndRetry(o)
         \/ ApplyButAckLost(o) \/ Escalate(o) \/ BestEffort(o)
    \/ Terminating

\* The custodian's step for one obligation: any of its custody actions. While an
\* obligation is pending, some custodian step is enabled (a delivery attempt
\* below the deadline, or escalation at it), so weak fairness on this step is
\* exactly the paper's assumption that "the custodian continues to execute." It
\* forces a pending obligation forward — retries advance bounded time/attempts
\* until escalation becomes enabled — so no admissible obligation stalls forever.
CustodianStep(o) ==
    Apply(o) \/ Decline(o) \/ LoseAndRetry(o) \/ ApplyButAckLost(o) \/ Escalate(o)

Fairness ==
    /\ \A o \in Obligations : WF_vars(CustodianStep(o))
    /\ \A o \in Obligations : WF_vars(BestEffort(o))

Spec == Init /\ [][Next]_vars /\ Fairness

\* --------------------------------------------------------------------------
\* Safety
\* --------------------------------------------------------------------------

AB2Persistence == \A o \in Obligations : attempts[o] <= MaxRetries + 1
AB3EffectivelyOnce == \A o \in Obligations : applied_count[o] <= 1
AB4FailSafe == \A o \in Obligations : (custody[o] = "escalated") => protected[o]
DeliverOrReport ==
    \A o \in Admissible : custody[o] \in ({"pending"} \cup Discharged)
BenignSideBestEffort ==
    \A o \in (Obligations \ Admissible) : custody[o] \in {"pending", "best_effort"}

Invariants ==
    /\ TypeOK
    /\ AB2Persistence
    /\ AB3EffectivelyOnce
    /\ AB4FailSafe
    /\ DeliverOrReport
    /\ BenignSideBestEffort

\* --------------------------------------------------------------------------
\* Liveness
\* --------------------------------------------------------------------------

DeliverOrReportLive ==
    \A o \in Admissible : <>(custody[o] \in Discharged)

=============================================================================
