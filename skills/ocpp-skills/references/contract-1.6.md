# OCPP 1.6 — wire contract reference

Everything your API needs from the OCPP CSMS: the commands it issues for you, and the events it
must forward to you. The CSMS owns the transport; this file is the shared vocabulary.

## Envelope (for tracing — the CSMS owns it)

```jsonc
CALL        [2, "<uniqueId>", "<Action>",                    {<payload>}]
CALLRESULT  [3, "<uniqueId>",                                {<payload>}]
CALLERROR   [4, "<uniqueId>", "<errorCode>", "<errorDesc>",  {<errorDetails>}]
```

`MessageTypeId` 2/3/4 only. Empty payload is `{}`, never `null`. Optional fields are **omitted**.
The station identity is **not** in the envelope — it is the last non-empty path segment of the
WebSocket URL, percent-encoded. `CALLRESULT`/`CALLERROR` echo the `uniqueId` of their `CALL`.

### CALLERROR codes (1.6 spelling — do not "fix" the typos)

`NotImplemented` · `NotSupported` · `InternalError` · `ProtocolError` · `SecurityError` ·
`FormationViolation` · `PropertyConstraintViolation` · `OccurenceConstraintViolation` ·
`TypeConstraintViolation` · `GenericError`

`FormationViolation` and `OccurenceConstraintViolation` (one `r`) are 1.6's permanent spellings.
2.0.1 keeps both typos; 2.1 corrects them to `FormatViolation` and
`OccurrenceConstraintViolation`.

## Outbound operations (CSMS → charger) on your behalf

`*` = required. `[]` = optional.

| Operation | Request fields | Conf | Notable |
|---|---|---|---|
| `RemoteStartTransaction` | `idTag`*, `connectorId`, `chargingProfile` | `status`* | Conf has **status only** — no `idTagInfo`. `connectorId` must be > 0 |
| `RemoteStopTransaction` | `transactionId`* | `status`* | must match the id you were issued |
| `UnlockConnector` | `connectorId`* | `status`* | must be > 0; finish the tx first |
| `ChangeAvailability` | `connectorId`*, `type`* | `status`* | `0` = whole station; `Unavailable` persists across reboot |
| `ChangeConfiguration` | `key`*, `value`* | `status`* | `key` ≤ 50, `value` ≤ 500. Flat key/value — no component tree |
| `GetConfiguration` | `key`[] | `configurationKey`*, `unknownKey`* | **omit `key` for everything** |
| `SetChargingProfile` | `connectorId`*, `csChargingProfiles`* | `status`* | `NotSupported` CALLERROR when SmartCharging is absent |
| `ClearChargingProfile` | `chargingProfileId`, `chargingProfileCriteria` | `status`* | all absent = clear all; criteria must **match** |
| `GetCompositeSchedule` | `connectorId`*, `duration`* | `status`* `schedule` | indicative only |
| `Reset` | `type`* = `Soft`\|`Hard` | `status`* | **socket closes immediately after** |
| `TriggerMessage` | `requestedMessage`*, `connectorId` | `status`* | never trigger `BootNotification` |
| `ReserveNow` | `connectorId`*, `expiryDate`*, `idTag`*, `reservationId`*, `parentIdTag`, `connectorType` | `status`* | `connectorId = 0` needs `ReserveConnectorZeroSupported=true` |
| `CancelReservation` | `reservationId`* | `status`* | |
| `SendLocalList` | `listVersion`*, `updateType`*, `localAuthorizationList` | `status`* | **`Full` + empty list WIPES it** |
| `GetLocalListVersion` | — | `listVersion`* | `0` = empty, `-1` = unsupported |
| `ClearCache` | — | `status`* | `Rejected` is normal (nothing cached) |
| `GetDiagnostics` | `location`*, `retries`*, `retryInterval`*, `startTime`, `stopTime` | `fileName` | no `fileName` in conf = nothing available |
| `UpdateFirmware` | `location`*, `retrieveDate`*, `retries`*, `retryInterval`* | *(no fields)* | the receipt **is** the ack |
| `DataTransfer` | `vendorId`*, `messageId`, `data` | `status`* `data` | the only vendor escape hatch |

SecurityExtension adds `SignCertificate`, `CertificateSigned`, `GetLog`,
`GetInstalledCertificateIds`, `InstallCertificate`, `DeleteCertificate`,
`SignedUpdateFirmware`, `ExtendedTriggerMessage`, `LogStatusNotification`.

### Status enums you must map

| Enum | Values |
|---|---|
| `RemoteStart/StopTransaction.conf.status`, most `*Response.status` | `Accepted` `Rejected` |
| `ChangeAvailability` | `Accepted` `Scheduled` `Rejected` |
| `ChangeConfiguration` | `Accepted` `Rejected` `RebootRequired` `NotSupported` |
| `Reset` | `Accepted` `Rejected` |
| `TriggerMessage` | `Accepted` `Rejected` `NotImplemented` |
| `ReserveNow` | `Accepted` `Faulted` `Occupied` `Rejected` `Unavailable` |
| `UnlockConnector` | `Unlocked` `UnlockFailed` `NotSupported` |
| `ClearChargingProfile` | `Accepted` `Unknown` |
| `SendLocalList` | `Accepted` `Failed` `VersionMismatch` |

**Status ≠ error.** `Rejected`, `Occupied`, `Unknown` are normal `CALLRESULT`s, not `CALLERROR`s.
Map them to 4xx, never 5xx.

## Inbound events the CSMS must forward

| Message | Request fields | Conf |
|---|---|---|
| `Authorize` | `idTag`* | `idTagInfo`*: `status`* `parentIdTag` `expiryDate` |
| `StartTransaction` | `connectorId`*, `idTag`*, `meterStart`*, `timestamp`*, `reservationId` | **`transactionId`*, `idTagInfo`*** |
| `StopTransaction` | `transactionId`*, `meterStop`*, `timestamp`*, `reason`, `idTag`, `transactionData` | `idTagInfo` |
| `MeterValues` | `connectorId`*, `meterValue`*, `transactionId` | *(empty)* |
| `StatusNotification` | `connectorId`*, `status`*, `timestamp`, `errorCode`, `info`, `vendorId`, `vendorErrorCode` | *(empty)* |

### `IdTagInfo.status` — the authorization gate

| Value | Meaning | API behaviour |
|---|---|---|
| `Accepted` | may charge | allow |
| `Blocked` | explicitly denied | **403** to the driver |
| `Expired` | token past `expiryDate` | **401** — require re-auth |
| `Invalid` | unknown token | **401** |
| `ConcurrentTx` | already charging elsewhere | **409** — offer the existing session |

`StartTransaction.conf.idTagInfo` is the **last** gate: the charger may hold a stale authorization
cache from an earlier `Authorize`. Honour it over any local decision.

`parentIdTag` groups tokens — two ids are in the same group when their `parentIdTag` match. Use it
for "one car, many tags" fleet billing. Absent `parentIdTag` never groups with anything.

### `MeterValue` / `SampledValue`

| Field | Notes |
|---|---|
| `timestamp` | charger clock — unreliable; keep your `received_at` too |
| `sampledValue[]` | `value` (**string** — parse as decimal, never float), `context`, `format`, `measurand`, `phase`, `location`, `unit` |
| `context` | `Sample.Periodic`, `Transaction.Begin`, `Transaction.End`, `Sample.ClockAligned`, `Transaction.Update`, `Sample.PeriodicClockAligned` |
| `format` | `Raw` or `SignedData` — **SignedData is unusable for billing** |
| `location` | `Inlet` \| `Outlet` — `Outlet` is the EV side and is what you bill |
| `phase` | `L1` `L2` `L3` `N` `L1-N` `L2-N` `L3-N` `L1-L2` `L2-L3` `L3-L1` |
| `unit` | defaults to `Wh` |

`Transaction.Begin` / `Transaction.End` contexts are the reliable start/stop register points —
prefer them over `StartTransaction.meterStart` when both are present and agree, and record when they
disagree.

### `StopTransaction.reason`

`EmergencyStop` · `EVDisconnected` · `HardReset` · `Local` · `Other` · `PowerLoss` ·
`Reboot` · `Remote` · `SoftReset` · `UnlockCommand` · `DeAuthorized`

Absent → `Local`. `EmergencyStop`/`PowerLoss`/`HardReset` ⇒ expect a meter gap; mark the session
`estimated` if you have to close it yourself.

## Correlation and idempotency

| Your identifier | Maps to |
|---|---|
| `session_id` | allocated by the CSMS as `transactionId` (int) — persist on `StartTransaction.conf` |
| `reservation_id` | `ReserveNow.reservationId` |
| `local_list_version` | `SendLocalList.listVersion` (monotonic int) |
| request correlation | the OCPP `uniqueId` — have the CSMS log it |

- **Inbound dedupe** on `(station, action, transactionId, timestamp)`.
- **Outbound idempotency:** accept an `Idempotency-Key` header, persist `key → (ocpp uniqueId,
  status)` before issuing, and return the stored response on replay.
- **Reuse detection:** if a new session arrives with a `transactionId` you have already closed,
  treat it as a **recycled id** — the previous session was never closed. Alert, never silently
  overwrite.

## What the CSMS should reject on your behalf

| Condition | Reply to you |
|---|---|
| station not connected | **409/503** `{chargerOffline: true, lastSeen}` |
| CALLERROR `NotSupported` on `SetChargingProfile` | **501** + disable the feature permanently |
| CALLERROR `SecurityError` | **423** — admin action required |
| CALLERROR `FormationViolation` | **502** — your payload is wrong, this is a bug in the CSMS |
| no `CALLRESULT` within ~30 s | **504** — ambiguous outcome, do **not** auto-retry non-idempotent ops |

Degrade permanently on `NotSupported`/`NotImplemented`. Never blind-retry them.
