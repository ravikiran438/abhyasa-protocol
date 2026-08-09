# Abhyasa v1 — A2A Extension Specification

`uri`: `https://ravikiran438.github.io/abhyasa-protocol/v1`

Abhyasa carries an *admissible governance obligation* under custody until it is
applied, explicitly declined, or escalated to the principal — never silently
lost. This document specifies the A2A discoverability surface; the framework
invariants are in the paper (§3–§4) and the reference implementation under
`src/abhyasa/`.

## Discoverability

A Abhyasa-capable agent publishes one entry in
`AgentCard.capabilities.extensions[]`:

```json
{
  "uri": "https://ravikiran438.github.io/abhyasa-protocol/v1",
  "description": "Abhyasa custody transfer of governance obligations (deliver-or-report).",
  "params": {
    "version": "1.0.0",
    "custody_ack_endpoint": "https://orchestrator.example.com/abhyasa/custody_ack",
    "supported_kinds": [
      {
        "kind": "anumati.consent",
        "obligation_endpoint": "https://agent-b.example.com/abhyasa/obligations",
        "deadline_seconds": 3600,
        "max_retries": 16,
        "backoff": "exponential",
        "backoff_base_seconds": 1.0,
        "backoff_cap_seconds": 600
      },
      {
        "kind": "phala.belief_update",
        "obligation_endpoint": "https://agent-b.example.com/abhyasa/obligations",
        "deadline_seconds": 86400,
        "max_retries": 48,
        "backoff": "exponential",
        "backoff_base_seconds": 1.0,
        "backoff_cap_seconds": 3600
      }
    ]
  }
}
```

Custody is advertised once per agent (the `custody_ack_endpoint`) with one
`KindProfile` per governance kind carried under custody; each kind tunes its
own deadline and retry budget, and `max_retries` MUST be large enough that the
capped backoff spans `deadline_seconds` (the deadline, not the retry count, is
the binding terminator — the schema validator rejects incoherent profiles).

The `params` object is an `AbhyasaServiceRef`; `manifest.json` carries its full
JSON Schema (`agent_card_payload_schema`).

## Wire

```
POST /abhyasa/obligations   Body: Obligation (admissible)
                              → 200 + CustodyAck            (sync application)
                              or 202, then async POST of CustodyAck
                                     to custody_ack_endpoint  (deferred)
POST /abhyasa/custody_ack    Body: CustodyAck               → 204
```

`CustodyAck.status ∈ {applied, declined, deferred}`. `applied` and `declined`
discharge custody; `deferred` retains it — the custodian continues retrying
under AB-2 (deferral extends neither the deadline nor the retry budget, and
the backoff schedule continues unchanged; resetting it for a reachable
receiver would invite a retry storm). A decline discharges delivery, not
protection: the custodian MUST NOT treat `declined` as equivalent to
`applied` — it MUST either apply `safe(O)` to principal-side state (the
default) or surface the decline, with the receiver's stated reason, for an
explicit principal decision; no escalation is emitted either way, since the
decline itself is the accountable record. Deadlines bind both sides: a
receiver MUST NOT apply an obligation whose deadline has passed — an expired
pending or deferred obligation is discarded and acknowledged `declined` with
expiry as the reason, and a late `applied` that arrives after escalation is
logged for principal-side reconciliation, never a reopened terminal state.
Idempotency is keyed on
`obligation_id` (AB-3): a redelivered obligation already applied is re-acked
`applied` without reapplication.

## Invariants

- **AC-1** an obligation is admissible iff it declares a fail-safe polarity `safe(O)`.
- **AB-1** an admissible obligation MUST be delivered under custody until applied/declined or deadline.
- **AB-2** on timeout, retry under bounded exponential backoff up to `max_retries`.
- **AB-3** apply at most once, keyed on `obligation_id`.
- **AB-4** on deadline without applied/declined, execute `safe(O)` on principal-side state and escalate.

Inadmissible obligations (unknown kind, or the benign-loss side of a signed
polarity such as a reinforcing Phala update) travel best-effort, not under
custody.
