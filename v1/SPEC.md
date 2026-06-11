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
    "obligation_endpoint": "https://agent-b.example.com/abhyasa/obligations",
    "custody_ack_endpoint": "https://orchestrator.example.com/abhyasa/custody_ack",
    "deadline_seconds": 86400,
    "max_retries": 6,
    "backoff": "exponential",
    "supported_kinds": ["anumati.consent", "phala.belief_update"]
  }
}
```

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
discharge custody; `deferred` retains it. Idempotency is keyed on
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
