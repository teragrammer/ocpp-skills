# API design — the layer between REST and OCPP

Your API is a **product contract**, not an OCPP proxy. Callers should never send an OCPP payload or
parse an OCPP status. They send domain commands (`start session`, `set tariff`, `invoice`) and read
domain resources.

## Resource model

A shape that survives all three versions:

```
Charger          id, station identity, ocpp_version, subprotocol, status, last_seen, capabilities
  └─ EVSE        evse_id, connector_count, status
       └─ Connector  connector_id, status, error_code, last_status_at
Session          id, charger_id, evse_id, connector_id, ocpp_transaction_id,
                 state, started_at, ended_at, energy_wh, cost, currency, cost_source,
                 seq_start, seq_end, missing_seq_count, estimated, flags
Reservation      id, charger_id, evse_id, id_token, expires_at, state
Tariff           id, version, currency, components, conditions, valid_from, state, content_hash
Invoice          id, session_id, line_items, tax, total, status, issued_at
Payment          id, session_id, psp_ref, amount, currency, status, settled_at
```

Version-specific fields stay internal or nullable. Do not leak `idTag` vs `idToken`, `connectorId`
vs `evseId`, or `seqNo` into every public response.

## The command contract

For every public command endpoint, write this down before coding:

| Question | Example (`POST /sessions`) |
|---|---|
| OCPP operation | `RequestStartTransaction` |
| Required OCPP fields | `idToken`, `remoteStartId` |
| Optional OCPP fields | `evseId`, `groupIdToken`, `chargingProfile` |
| Correlation key | `remoteStartId = session_id` |
| Success reply | `Accepted` |
| HTTP on success | **202** `{id, status: "starting"}` |
| Domain refusals | `Rejected` → 409 `{code: "charger_rejected"}` |
| Transport failures | offline → 409/503; timeout → 504 |
| Queueable? | **no** |
| Idempotency | required, keyed by `Idempotency-Key` |
| Capability gate | `supports_remote_start` |

If two versions differ only in the OCPP operation, keep one public endpoint and put the difference
in the adapter. If they differ in the **domain** (2.1 tariffs), expose a new endpoint and gate it.

## The event contract

For every inbound OCPP message you forward, specify:

| Question | Example (`TransactionEvent`) |
|---|---|
| Event name | `session.started`, `session.updated`, `session.ended` |
| Correlation | `transactionInfo.remoteStartId` → `session_id` |
| Identity | `transactionInfo.transactionId` (charger-owned) |
| Dedupe key | `(station_id, transaction_id, seq_no)` |
| Ordering | `seqNo` per EVSE; charger `timestamp` for billing windows |
| Required fields | `eventType`, `timestamp`, `triggerReason`, `seqNo`, `transactionInfo` |
| Optional fields | `meterValue`, `offline`, `idToken`, `costDetails` |
| Side effects | bind session, capture start register, snapshot rate, enqueue invoice |
| Consumer | your API's event handler — not a webhook to the driver app |

Define event handlers as **idempotent state machines**, not as "do X on message". A replayed
`Ended` must not create a second invoice.

## HTTP semantics

| Situation | HTTP | Body |
|---|---|---|
| Command accepted, outcome asynchronous | **202** | `{id, status: "starting"\|"stopping"\|"pending"}` |
| Synchronous read or cached state | **200** | resource |
| Created a durable resource (reservation, tariff) | **201** | resource + `Location` |
| Domain refusal (`Rejected`, `Occupied`, `NoProfile`, `NoTariff`) | **4xx** | `{code, message, details}` |
| Charger offline | **409** or **503** | `{code:"charger_offline", chargerOffline:true, lastSeen}` |
| Feature absent / not negotiated | **501** | `{code:"unsupported", requiredSubprotocol?}` |
| Capability is WriteOnly / forbidden | **403** | `{code:"forbidden"}` |
| Security error / not registered | **423** | `{code:"security_error"}` |
| Malformed OCPP payload (your bug) | **502** | `{code:"protocol_error"}` |
| No OCPP reply within the timeout | **504** | `{code:"ocpp_timeout", retryable:false}` |
| Duplicate `Idempotency-Key` with a different body | **409** | `{code:"idempotency_conflict"}` |

**Never return 200 for an accepted-but-not-completed command.** Use 202 and a pollable status
resource. The OCPP spec suggests a 30 s CALL timeout; an HTTP request should not wait for a
round-trip that may need a follow-up message.

### Status → HTTP mapping

| OCPP status | HTTP | Notes |
|---|---|---|
| `Accepted` | 200/201/202 | 202 if the real outcome arrives later |
| `Scheduled` | 202 | accepted for later |
| `Rejected` | 409 | normal refusal, not a server error |
| `Occupied` / `Unavailable` / `Faulted` | 409 | conflict with current physical state |
| `Unknown` / `NotFound` / `NoTariff` / `NoProfile` | 404 or 409 | 404 if the resource is gone; 409 if it is in use |
| `DuplicateTariffId` / `VersionMismatch` / `NoCurrencyChange` | 409 | caller must change the request |
| `NotSupported` | 501 | disable the feature for that station |
| `NotImplemented` | 501 | version/capability mismatch |
| `UnlockFailed` / `OngoingAuthorizedTransaction` | 409 | stop or finish the session first |
| `RebootRequired` | 200 + `{rebootRequired:true}` | the write succeeded |

### Error envelope

Use one shape everywhere:

```jsonc
{
  "error": {
    "code": "charger_offline",
    "message": "Charger is not connected",
    "details": { "chargerId": "CP-001", "lastSeen": "2026-10-25T10:00:00Z" },
    "requestId": "req_01J..."
  }
}
```

`code` is stable and machine-readable. `message` is for humans. `details` is free-form but never
contains secrets or raw OCPP payloads.

## Idempotency

Every mutating endpoint should accept `Idempotency-Key`.

```
1. Persist  key → (request_hash, state = "in_flight", ocpp_message_id)  BEFORE sending.
2. Send the OCPP call.
3. Persist the terminal result and response body.
4. On replay with the same key and same body: return the stored response.
5. On replay with the same key and a different body: 409 idempotency_conflict.
```

Without this, an HTTP retry after a timeout can start two sessions or stop the wrong one. OCPP
`CALLRESULT` timeouts are **ambiguous** — never auto-retry a non-idempotent operation.

## Correlation and dedupe

| Your key | Version | OCPP key |
|---|---|---|
| `session_id` | 1.6 | `StartTransaction.conf.transactionId` (store it) |
| `session_id` | 2.x | `RequestStartTransaction.remoteStartId` → `TransactionEvent.transactionInfo.remoteStartId` |
| `reservation_id` | 1.6 | `ReserveNow.reservationId` |
| `reservation_id` | 2.x | `ReserveNow.id` |
| `tariff_id` | 2.1 | `TariffType.tariffId` |
| `psp_ref` | 2.1 | `idToken.idToken` when `type = "DirectPayment"` |

- Inbound dedupe: 1.6 `(station, action, transactionId, timestamp)`; 2.x
  `(stationId, transactionId, seqNo)`.
- Outbound correlation: persist the OCPP `uniqueId`/`MessageId` before sending. A response with an
  unknown id is a bug, not a new event.
- A `Started` with no matching `remoteStartId` is **not** an orphan: it is plug-and-charge or a
  retry. Adopt it by `(station, evse, timestamp)`; never drop it.
- Two `Started` events for one `remoteStartId` are a duplicate. Create one session.

## Offline behaviour and the queue

Split operations into two classes at design time:

**Live-socket only (never queue):**

| Version | Operations |
|---|---|
| 1.6 | `RemoteStartTransaction`, `RemoteStopTransaction`, `UnlockConnector`, `Reset`, `TriggerMessage`, `UpdateFirmware`, certificate ops |
| 2.x | `RequestStartTransaction`, `RequestStopTransaction`, `UnlockConnector`, `Reset`, `TriggerMessage`, `CostUpdated`, `DataTransfer`, `NotifyWebPaymentStarted` |

Why: they go stale, retarget to a recycled transaction id, or depend on a live session. Return
**409/503** with `{chargerOffline:true, lastSeen}`. Let the caller decide whether to retry later.

**Safe to queue (station persists and applies on boot):**

| Version | Operations |
|---|---|
| 1.6 | `ChangeConfiguration`, `ChangeAvailability`, `SetChargingProfile`, `ClearChargingProfile`, `SendLocalList`, `GetConfiguration`, `ClearCache` |
| 2.x | `SetChargingProfile`, `ClearChargingProfile`, `SendLocalList`, `SetNetworkProfile`, `SetMonitoringBase`, `SetMonitoringLevel`, `SetDisplayMessage`, `ChangeAvailability` |

Even safe operations must expire: attach a `not_after` and drop the queue entry if the charger has
not reconnected within the product's tolerance.

## Long-running operations

Some OCPP actions answer immediately and stream the result in a follow-up CALL with the same
`requestId`: `GetBaseReport`, `GetReport`, `GetChargingProfiles`, `GetDisplayMessages`,
`GetMonitoringReport`, `CustomerInformation`, `GetLog`, `UpdateFirmware`, `PublishFirmware`.

Expose them as:

```
POST /chargers/{id}/reports           → 202 {operationId, status:"pending"}
GET  /operations/{operationId}        → 200 {status:"pending"|"complete"|"failed", result?}
```

Assemble `NotifyReport` fragments until `tbc == false`; do not return a partial device model as if
it were complete.

## Capability flags

Store per station, derived from the negotiated subprotocol plus a device-model probe:

```
ocpp_version, supports_smart_charging, supports_reservations, supports_local_auth_list,
supports_display_message, supports_tariffs, supports_settlement, supports_web_payments,
supports_priority_charging, supports_battery_swap, supports_der, register_values_without_phases
```

Rules:

- A flag is **tri-state**: unknown / supported / unsupported. Unknown means "hide the endpoint" or
  "probe first", not "try it".
- Invalidate on `BootNotification` and after firmware reaches `Installed`.
- `NotSupported` / `NotImplemented` flips the flag to unsupported **permanently** for that station
  (until the next firmware change). Never blind-retry.
- A 2.0.1 station receiving a 2.1-only action returns `NotImplemented` without dropping the
  session — your feature fails silently unless you gate it.

## Cached state

Serve `GET /chargers/{id}` and connector status from your cache, not with a synchronous OCPP call.

- Cache `StatusNotification` per connector; never derive station availability from
  `connectorId = 0` / `evseId = 0`.
- Expose `lastStatusAt` and `stale: true` when older than `MinimumStatusDuration`.
- Do not call `GetVariables` on every read. Cache the device model and refresh on boot / explicit
  request.
- A charger's `Available` status is not a promise that a connector is physically free.

## Security

- Never expose lowering `SecurityCtrlr.SecurityProfile` through a public API. Profile 1 is
  plaintext Basic auth.
- `SecurityCtrlr.BasicAuthPassword` is WriteOnly: return `{writeOnly: true}`, never a value, and map
  `Rejected` on read to **403**, not 404.
- Do not proxy raw OCPP frames to tenants. Validate and translate.
- For payments, only accept `pspRef` and display-safe card metadata (`CardBin`, `CardLast4Digits`,
  `CardBrand`). Never send raw card data in `additionalInfo` — that is a PCI problem.
- Treat `DataTransfer.data` and `customData` as untrusted, untyped input: cap size, validate, and
  never let them mutate your authoritative rate table.
- Authenticate the **CSMS → your API** webhook path separately from your public API. Inbound OCPP
  events and settlement reports are not user requests.

## Testing checklist

- [ ] Accepted command returns 202, not 200.
- [ ] Duplicate `Idempotency-Key` returns the stored response, not a second session.
- [ ] Offline live-socket command returns 409/503, not a queued job.
- [ ] A replayed `Ended` does not create a second invoice.
- [ ] A `seqNo` gap defers billing; `messagesInQueue:false` closes as estimated.
- [ ] A 2.1-only endpoint on a 2.0.1 station returns 501 and stays hidden.
- [ ] `SetVariables` partial failure returns 200 with per-item statuses.
- [ ] `meterStop < meterStart` quarantines the session.
- [ ] `TariffNotAccepted` refunds and does not invoice.
- [ ] `NotifySettlement` is correlated on `(pspRef, transactionId)`.
- [ ] A 30 s OCPP timeout returns 504 and does not auto-retry a stop.
