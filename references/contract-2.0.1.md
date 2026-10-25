# OCPP 2.0.1 — wire contract reference

What your API needs from the CSMS: the commands it issues for you, and the events it forwards. The
CSMS owns the transport; this file is the shared vocabulary.

## Envelope (for tracing — the CSMS owns it)

```jsonc
CALL        [2, "<uniqueId>", "<Action>",                   {<payload>}]
CALLRESULT  [3, "<uniqueId>",                               {<payload>}]
CALLERROR   [4, "<uniqueId>", "<errorCode>", "<errorDesc>", {<errorDetails>}]
```

`MessageTypeId` 2/3/4 only. Empty payload is `{}`. **Omit unset optional fields** — `null`, `{}` and
`[]` are invalid for an absent field. A corrupt message gets a `CALLERROR` with
`uniqueId = "-1"`. The `Action` is the message name **without** the `Request` suffix
(`GetConfiguration`, not `GetConfigurationRequest`).

### CALLERROR codes

`FormatViolation` · `GenericError` · `InternalError` · `MessageTypeNotSupported` ·
`NotImplemented` · `NotSupported` · `OccurenceConstraintViolation` ·
`PropertyConstraintViolation` · `ProtocolError` · `RpcFrameworkError` · `SecurityError` ·
`TypeConstraintViolation`

`OccurenceConstraintViolation` (one `r`) is 2.0.1's wire spelling — **keep it**. 2.1 corrects it.

Semantics, which are widely documented backwards:

| Code | Actual meaning | Your behaviour |
|---|---|---|
| `NotImplemented` | the receiver has no handler / does not know the action | degrade permanently, never blind-retry |
| `NotSupported` | action known, functionality absent (e.g. no SmartCharging) | degrade permanently, **501**, disable the feature |
| `MessageTypeNotSupported` | the receiver cannot handle that `MessageTypeId` | infrastructure bug — alert |
| `RpcFrameworkError` | malformed envelope, e.g. empty `Action` | **502**, your request was malformed |

`Rejected`, `Unknown`, `EmptyResultSet`, `NoProfiles` are **normal CALLRESULT statuses**, not
errors. Map them to 4xx, never 5xx.

## Outbound operations (CSMS → station) on your behalf

`*` required, `[]` optional.

| Operation | Request | Conf | Notable |
|---|---|---|---|
| `RequestStartTransaction` | `idToken`*, `remoteStartId`*, `evseId`, `groupIdToken`, `chargingProfile` | `transactionId`, `status`* | `evseId` optional; `remoteStartId` echo is **mandatory** and is your correlation key |
| `RequestStopTransaction` | `transactionId`* | `status`* | may produce only `Updated`, never `Ended` |
| `UnlockConnector` | `evseId`*, `connectorId`* | `status`* | `OngoingAuthorizedTransaction` when a tx is live |
| `SetVariables` | `setVariableData[1..*]`* | `setVariableResult[1..*]`* | **partial success is normal** — read every element |
| `GetVariables` | `getVariableData[1..*]`* | `getVariableResult[1..*]`* | **no wildcards**; `""` means unset |
| `SetChargingProfile` | `evseId`*, `chargingProfile`* | `status`* | `NotSupported` CALLERROR without SmartCharging |
| `ClearChargingProfile` | `chargingProfileId`, `chargingProfileCriteria` | `status`* | both absent ⇒ clear all |
| `GetCompositeSchedule` | `evseId`*, `duration`*, `chargingRateUnit` | `status`* `schedule` | `schedule` absent when `Rejected` |
| `GetChargingProfiles` | `requestId`*, `chargingProfile`*, `evseId` | `status`* | results arrive as a **follow-up** `ReportChargingProfiles` |
| `ChangeAvailability` | `operationalStatus`*, `evse` | `status`* | omit `evse` = whole station |
| `Reset` | `type`* = `Immediate`\|`OnIdle`, `evseId` | `status`* | **socket closes** |
| `TriggerMessage` | `requestedMessage`*, `evse` | `status`* | `evse.id` must be > 0 |
| `ReserveNow` | `id`* (**yours**), `expiryDateTime`*, `idToken`*, `evseId`, `connectorType`, `groupIdToken` | `status`* | **`connectorId` is gone** — address by `evseId` |
| `CancelReservation` | `reservationId`* | `status`* | |
| `SendLocalList` | `versionNumber`*, `updateType`*, `localAuthorizationList` | `status`* | **`Full` + empty = wipe** |
| `SetNetworkProfile` | `configurationSlot`*, `connectionData`* | `status`* | followed by `NetworkConfigurationPriority` |
| `SetDisplayMessage` | `message`* | `status`* | many `NotSupported*` reasons |
| `CostUpdated` | `totalCost`*, `transactionId`* | *(empty)* | **CSMS → station**: pushes your running cost to its display |
| `GetBaseReport` / `GetReport` | `requestId`*, (+ `reportBase` / criteria) | `status`* | **follow-up** `NotifyReport` streams the device model |
| `GetTransactionStatus` | `transactionId` | `messagesInQueue`* | your reconciliation primitive |
| `DataTransfer` | `vendorId`*, `messageId`, `data` | `status`* `data` | the only vendor channel in 2.0.1 |

`GetDisplayMessages`, `GetMonitoringReport`, `CustomerInformation`, `GetLog`, `UpdateFirmware`,
`PublishFirmware`, `SetVariableMonitoring`, `SetMonitoringBase` are CSMS infrastructure concerns —
keep them off your public API unless ops explicitly asks.

### The requestId/follow-up pattern

Eight operations answer immediately, then stream results as a **separate inbound CALL** carrying the
same `requestId`. Your API must expose long-running operations as **202 + a pollable status
resource**, never as a blocking request:

| You send | Results arrive as |
|---|---|
| `GetBaseReport`, `GetReport` | `NotifyReport` — assemble until `tbc == false` |
| `GetChargingProfiles` | `ReportChargingProfiles` |
| `GetDisplayMessages` | `NotifyDisplayMessages` |
| `GetMonitoringReport` | `NotifyMonitoringReport` |
| `CustomerInformation` | `NotifyCustomerInformation` |
| `GetLog`, `UpdateFirmware`, `PublishFirmware` | `LogStatusNotification`, `FirmwareStatusNotification`, `PublishFirmwareStatusNotification` |
| `TriggerMessage(<m>)` | `<m>` itself |

Always correlate on `requestId`, always persist your own id → `requestId` mapping before sending.

## Inbound events the CSMS must forward

### `TransactionEvent` — the billing record

| Field | Card | Notes |
|---|---|---|
| `eventType`* | 1..1 | `Started` first, `Ended` last, `Updated` between |
| `timestamp`* | 1..1 | charger clock |
| `triggerReason`* | 1..1 | see below |
| `seqNo`* | 1..1 | **per-EVSE monotonic** — your completeness proof |
| `transactionInfo`* | 1..1 | `transactionId`*, `chargingState`, `timeSpentCharging`, `stoppedReason`, `remoteStartId` |
| `meterValue` | 0..* | the energy. May be absent |
| `offline` | 0..1 | buffered by the station |
| `numberOfPhasesUsed`, `cableMaxCurrent` | 0..1 | optional |
| `reservationId`, `evse`, `idToken` | 0..1 | optional |

`TransactionEventResponse` (all optional): `totalCost` · `chargingPriority` (−9..9) ·
**`idTokenInfo`** (required when the request carried `idToken`) · `updatedPersonalMessage`.

**`idToken` timing:** it appears once when authorization starts and once when it ends — and is
**absent** when the session was ended by `RequestStopTransaction` or `Reset`. Persist the first one
you see and never require it on `Ended`.

`triggerReason` includes: `Authorized` `CablePluggedIn` `ChargingRateChanged` `ChargingStateChanged`
`Deauthorized` `EnergyLimitReached` `EVCommunicationLost` `EVConnectTimeout` `MeterValueClock`
`MeterValuePeriodic` `TimeLimitReached` `Trigger` `UnlockCommand` `StopAuthorized` `EVDeparted`
`RemoteStop` `RemoteStart` `Aborted` `Ended` `Reset` `Scheduled` `Unblocked` `SideCablePluggedIn`
`SignedDataReceived`.

`chargingState`: `Charging` `EVConnected` `SuspendedEV` `SuspendedEVSE` `Idle`. Only `Ended` ends a
session — `Idle`, `SuspendedEV` and `SuspendedEVSE` all still accrue energy and idle time.

`stoppedReason` (`ReasonEnumType`): `DeAuthorized` `EmergencyStop` `EVDisconnected` `HardReset`
`Local` `Other` `PowerLoss` `Reboot` `Remote` `SoftReset` `UnlockCommand` `ImmediateReset`. Absent ⇒
`Local`.

### Other inbound events

| Message | Extract | Response |
|---|---|---|
| `Authorize` | `idToken`*, `certificate`? | `idTokenInfo`*: `status`*, `expiryDate`?, `parentIdToken`?, `statusInfo`? |
| `StatusNotification` | `timestamp` `connectorStatus` `evseId` `connectorId` | *(empty)* |
| `MeterValues` | `evseId` `meterValue[]` | *(empty)* — **not transaction-linked**, do not bill from it |
| `Heartbeat` | liveness + clock sample | *(CSMS business)* |
| `BootNotification` | `reason`, `chargingStation{...}` | *(CSMS business — but see capability discovery)* |

`IdTokenInfoStatusEnumType`: `Accepted` `Blocked` `Expired` `Invalid` `ConcurrentTx` `NoCredit`.
`NoCredit` is 2.0.1-only and is the right hook for a prepaid balance check — return it when the
driver's wallet or credit is empty.

## Correlation and idempotency

| Your identifier | Maps to |
|---|---|
| `session_id` | `RequestStartTransaction.remoteStartId` → `TransactionEvent.transactionInfo.remoteStartId` |
| OCPP `transactionId` | **allocated by the station**; join on it at `Started` |
| `reservation_id` | `ReserveNow.id` |
| `profile_op_id` | `GetChargingProfiles.requestId`, `SetDisplayMessage.message.id` |
| `config_op_id` | `GetBaseReport`/`GetReport.requestId` |

- **Inbound dedupe** on `(stationId, transactionId, seqNo)` — and on `(stationId, uniqueId)` for
  retries of the same message.
- **`uniqueId` must never repeat** for a station, **including across reconnects** (2023-12 errata
  §4.2).
- **Outbound idempotency:** `Idempotency-Key` → persist `key → (uniqueId, status)` before issuing.
- **Never re-send `RequestStartTransaction`** on reconnect — the station owns the lifecycle. Send
  `GetTransactionStatus` instead and reconcile.

### Reconnect reconciliation

```
socket dropped while a session is open
  → mark session orphaned
  → on reconnect: GetTransactionStatus(transactionId) for every open session of that station
      messagesInQueue == true  → wait, do not close
      messagesInQueue == false → close as estimated: true, record gaps, alert
```

A session open for more than ~72 h almost always means `TxCtrlr.TxStartPoint` /
`TxStopPoint` is misconfigured. Alarm on it.

## What the CSMS should reject on your behalf

| Condition | Reply to you |
|---|---|
| station not connected | **409/503** `{chargerOffline: true, lastSeen}` |
| `BootNotification` status `Pending` or `Rejected` | **503** — the station must answer every other CALL with CALLERROR `SecurityError`, and `RequestStart*` must be `Rejected` |
| CALLERROR `NotSupported` | **501** + disable permanently |
| CALLERROR `SecurityError` | **423** |
| `interval` of `0` from `BootNotificationResponse` | must be > 0 when status is `Accepted` (errata §5.1) — reject as **502** |
| no CALLRESULT in ~30 s | **504** — ambiguous, do not auto-retry non-idempotent ops |
