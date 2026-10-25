# OCPP 2.1 — wire contract reference

What your API needs from the CSMS: the commands it issues for you, and the events it forwards. The
CSMS owns the transport; this file is the shared vocabulary.

## Contents

- [Envelope](#envelope)
- [Error codes](#error-codes)
- [Outbound operations](#outbound-operations-csms--station-on-your-behalf)
- [Status enums for the new operations](#status-enums-for-the-new-operations--exact-names-and-values)
- [GetTariffs response shape](#gettariffs-response-shape)
- [TotalCostType](#totalcosttype--the-itemised-cost)
- [The requestId/follow-up pattern](#the-requestidfollow-up-pattern)
- [Inbound events](#inbound-events-the-csms-must-forward)
- [Functional blocks](#functional-blocks-21s-replacement-for-feature-profiles)
- [Capability discovery](#capability-discovery)
- [Correlation and idempotency](#correlation-and-idempotency)
- [What the CSMS should reject](#what-the-csms-should-reject-on-your-behalf)

## Envelope

```jsonc
CALL            [2, "<MessageId>", "<Action>",                   {<payload>}]
CALLRESULT      [3, "<MessageId>",                               {<payload>}]
CALLERROR       [4, "<MessageId>", "<ErrorCode>", "<ErrorDesc>", {<ErrorDetails>}]
CALLRESULTERROR [5, "<MessageId>", "<ErrorCode>", "<ErrorDesc>", {<ErrorDetails>}]   ← NEW in 2.1
SEND            [6, "<MessageId>", "<Action>",                   {<payload>}]          ← NEW in 2.1
```

`MessageId` (was `uniqueId` in 2.0.1) is a `string[36]`, unique **per sender across all
connections**. A `CALLRESULTERROR`'s `MessageId` **must equal** the `CALLRESULT`'s that caused it.

| New type | Purpose | API consequence |
|---|---|---|
| `CALLRESULTERROR` (5) | reject a *response* that cannot be processed | your CSMS may need to answer your `requestId`-correlation logic differently |
| `SEND` (6) | fire-and-forget, **never answered** | **no delivery guarantee and no confirmation.** Do not build billing-critical flows on it |

`SEND` powers periodic event streams (`OpenPeriodicEventStream` / `AdjustPeriodicEventStream` /
`ClosePeriodicEventStream`). If your CSMS cannot receive `MessageTypeId 6`, do **not** expose a
`POST /chargers/{id}/events/stream` endpoint — it will silently accept and deliver nothing.

## Error codes

`FormatViolation` · `GenericError` · `InternalError` · `MessageTypeNotSupported` ·
`NotImplemented` · `NotSupported` · `OccurrenceConstraintViolation` ·
`PropertyConstraintViolation` · `ProtocolError` · `RpcFrameworkError` · `SecurityError` ·
`TypeConstraintViolation`

Note 2.1 **corrects** the 1.6/2.0.1 typos: `OccurrenceConstraintViolation` (two `r`s) and
`FormatViolation` (not `FormationViolation`).

| Code | Meaning | Your behaviour |
|---|---|---|
| `NotImplemented` | receiver has no handler / does not know the action | degrade permanently, **501** |
| `NotSupported` | action known, functionality absent | degrade permanently, **501**, disable |
| `MessageTypeNotSupported` | receiver cannot handle that `MessageTypeId` | **502** — infrastructure bug, alert |
| `RpcFrameworkError` | malformed envelope | **502** |
| `SecurityError` | not registered / unauthorised | **423** |

Domain refusals (`Rejected`, `Unknown`, `NoTariff`, `NoBatteryAvailable`, `NoProfile`,
`TxNotFound`, `DuplicateTariffId`) are **normal CALLRESULT statuses** → 4xx, never 5xx.

## Outbound operations (CSMS → station) on your behalf

`*` required.

| Operation | Request | Conf | Notable |
|---|---|---|---|
| `SetDefaultTariff` ⭐ | `evseId`*, `tariff`* | `status`* | `evseId = 0` installs at **every** EVSE |
| `GetTariffs` ⭐ | `evseId`* | `status`*, `tariffAssignments` | `NoTariff` when none installed |
| `ClearTariffs` ⭐ | `tariffIds` (min 1), `evseId` | `clearTariffsResult[1..*]` | **per-tariff** status array |
| `ChangeTransactionTariff` ⭐ | `transactionId`*, `tariff`* | `status`* | `NoCurrencyChange` if currency differs |
| `CostUpdated` ⭐ | `totalCost`*, `transactionId`* | *(empty)* | display only; rate-limit to `Interval[Cost]` |
| `NotifyWebPaymentStarted` ⭐ | `evseId`*, `timeout`* | *(empty)* | blocks a local start for `timeout` s |
| `NotifyAllowedEnergyTransfer` | `transactionId`*, `allowedEnergyTransfer[1..*]`* | `status`* | **CSMS → station** |
| `VatNumberValidation` ⭐ | `vatNumber`*, `evseId` | `vatNumber`* (**echo**), `evseId`?, `status`* (`GenericStatusEnumType`), `company`?, `statusInfo`? | **echo `vatNumber`** — omitting it breaks the reply |
| `RequestStartTransaction` | `idToken`*, `remoteStartId`*, `evseId`, `groupIdToken`, `chargingProfile` | `transactionId`, `status`* | identical to 2.0.1; `idToken.type = "DirectPayment"` for ad-hoc |
| `RequestStopTransaction` | `transactionId`* | `status`* | identical to 2.0.1 |
| `UsePriorityCharging` ⭐ | `transactionId`*, `activate`* | `status`* | `NoProfile` when not installed |
| `RequestBatterySwap` ⭐ | `idToken`*, `requestId`* (**yours**) | `status`* | `NoBatteryAvailable` + `reasonCode` |
| `UnlockConnector` | `evseId`*, `connectorId`* | `status`* | `OngoingAuthorizedTransaction` |
| `SetVariables` / `GetVariables` | arrays | per-element | **partial success is normal** |
| `SetChargingProfile` / `ClearChargingProfile` / `GetCompositeSchedule` / `GetChargingProfiles` | see 2.0.1 | | unchanged |
| `ChangeAvailability` / `Reset` / `TriggerMessage` / `ReserveNow` / `CancelReservation` / `SendLocalList` / `SetNetworkProfile` / `SetDisplayMessage` / `GetTransactionStatus` / `DataTransfer` | | | unchanged from 2.0.1 |
| `UpdateDynamicSchedule` ⭐ | `chargingProfileId`*, `scheduleUpdate`* | `status`* | |
| `SetDERControl` / `GetDERControl` / `ReportDERControl` / `ClearDERControl` ⭐ | DER contract | | energy limits / DER |
| `AFRRSignal` ⭐ | | | **station → CSMS**, response is empty |

`Reset.type` gains **`ImmediateAndResume`** in 2.1 — reset now and resume the session afterwards.
Useful, but it means a reset may **not** end your session; reconcile via `GetTransactionStatus`.

### Status enums for the new operations — exact names and values

```
TariffSetStatusEnumType       (SetDefaultTariffResponse)
  Accepted | Rejected | TooManyElements | ConditionNotSupported | DuplicateTariffId

TariffGetStatusEnumType       (GetTariffsResponse)
  Accepted | Rejected | NoTariff

TariffClearStatusEnumType     (ClearTariffsResultType.status — PER TARIFF)
  Accepted | Rejected | NoTariff
    NoTariff ⇒ nothing found; ClearTariffsResultType.tariffId is then ABSENT

TariffChangeStatusEnumType    (ChangeTransactionTariffResponse)
  Accepted | Rejected | TooManyElements | ConditionNotSupported | TxNotFound | NoCurrencyChange

PriorityChargingStatusEnumType (UsePriorityChargingResponse)
  Accepted | Rejected | NoProfile

GenericStatusEnumType         (VatNumberValidationResponse, RequestBatterySwapResponse, AFRRSignalResponse, …)
  Accepted | Rejected
```

Three consequences that catch people out:

- **`VatNumberValidation` and `RequestBatterySwap` have only `Accepted`/`Rejected`.** The reason
  lives in `statusInfo.reasonCode` — e.g. `RequestBatterySwap` returns `Rejected` +
  `statusInfo.reasonCode = "NoBatteryAvailable"`. **Read `reasonCode`, not an invented enum value.**
- **`ChangeTransactionTariff` has no `NotFound`.** `TxNotFound` means the transaction does not exist
  **or has already ended** → **404**.
- **`TariffClearStatusEnumType` has `NoTariff`, not `NotFound`** — and it is returned *per tariff*,
  not once for the call.

## `GetTariffs` response shape

```
TariffAssignmentType[]
  tariffId    string[0..60]*    the tariff
  tariffKind  TariffKindEnumType*   DefaultTariff | DriverTariff
  validFrom   dateTime?
  evseIds     integer[]         which EVSEs hold it
  idTokens    identifierString[0..255][]   which tokens it is bound to (driver tariffs)
```

`tariffKind` is how you tell a station-wide default from a driver-specific tariff — use it when
reconciling drift. `DriverTariff` assignments mean the driver rejected or has not yet accepted their
tariff: re-authorize rather than republish.

## `TotalCostType` — the itemised cost

```
currency    string[0..3]*      ISO 4217
typeOfCost  TariffCostEnumType*  NormalCost | MinCost | MaxCost
fixed        PriceType?        all flat fees in the currency
energy       PriceType?        all energy cost
chargingTime PriceType?        all charging-duration cost
idleTime     PriceType?        all idle-time cost, INCLUDING flat components
reservationTime PriceType?     TariffType.reservationTime
total        TotalPriceType*   sum of the above
```

Each `PriceType` is `{exclTax?, inclTax?, taxRates?(0..5)}`, so the station itemises tax for you.
`typeOfCost != NormalCost` means `minCost`/`maxCost` on the tariff clamped the result — **honour
it**, or the invoice will not match the quote.

`reservationTime` is counted here but a reservation is **not** reported as a `chargingPeriod` —
it happened outside the transaction.

## The requestId/follow-up pattern

As in 2.0.1, these answer immediately then stream results as a **separate inbound CALL** with the
same `requestId`. Expose them as **202 + a pollable resource**, never as a blocking request:

| You send | Results arrive as |
|---|---|
| `GetBaseReport`, `GetReport` | `NotifyReport` — assemble until `tbc == false` |
| `GetChargingProfiles` | `ReportChargingProfiles` |
| `GetDisplayMessages` | `NotifyDisplayMessages` |
| `GetMonitoringReport` | `NotifyMonitoringReport` |
| `CustomerInformation` | `NotifyCustomerInformation` |
| `GetLog`, `UpdateFirmware`, `PublishFirmware` | `LogStatusNotification`, `FirmwareStatusNotification`, `PublishFirmwareStatusNotification` |
| `GetPeriodicEventStream` ⭐ | periodic events over **SEND** |
| `TriggerMessage(<m>)` | `<m>` itself |

## Inbound events the CSMS must forward

| Message | Extract | Response |
|---|---|---|
| `TransactionEvent` ⭐ | **the billing record** — `costDetails`, `transactionInfo.tariffId`, `transactionLimit`, `evseSleep`, `preconditioningStatus`, `meterValue[]`, `seqNo`, `offline`, `idToken` | `totalCost`?, `transactionLimit`?, `idTokenInfo`?, `updatedPersonalMessage`?, `updatedPersonalMessageExtra`? |
| `NotifySettlement` ⭐ | `pspRef`, `status`, `settlementAmount`, `settlementTime`, `transactionId`?, `receiptId`?, `receiptUrl`?, `vatNumber`?, `vatCompany`? | `receiptUrl`?, `receiptId`? |
| `NotifyPriorityCharging` ⭐ | `transactionId`, `activated` | *(empty)* |
| `BatterySwap` ⭐ | `eventType` (`BatteryIn`/`BatteryOut`/`BatteryOutTimeout`), `requestId`*, `idToken`*, `batteryData[1..*]`* | *(empty)* |
| `ClosePeriodicEventStream` ⭐ | `id` — **station-initiated** | *(empty)* — **no handler ⇒ `NotImplemented`** |
| `PullDynamicScheduleUpdate` ⭐ | `chargingProfileId`* — **the station asks you** | `status`*, `scheduleUpdate`? |
| `AFRRSignal` ⭐ | station → CSMS | *(empty)* |
| `NotifyDERAlarm` / `NotifyDERStartStop` / `ReportDERControl` ⭐ | | *(empty)* |
| `Authorize` | `idToken`* (`DirectPayment` ⇒ value is the `pspRef`) | `idTokenInfo`*, `tariff`? ⭐ |
| `StatusNotification` / `MeterValues` / `Heartbeat` / `NotifyEvent` / `NotifyReport` / `NotifyCustomerInformation` | | *(empty)* |
| `Get15118EVCertificate` | station → CSMS (Plug&Charge) | — do not implement as outbound |
| `SignCertificate` / `SecurityEventNotification` / `LogStatusNotification` / `FirmwareStatusNotification` / `PublishFirmwareStatusNotification` / `ReservationStatusUpdate` | | *(empty)* |

**Register a handler for every inbound action you forward.** A missing handler yields
`NotImplemented` and can stall the station.

`VatNumberValidation` is **outbound** (you ask, the station answers). Model it as a webhook your
CSMS calls into your API, not as a REST endpoint your clients call.

## Functional blocks (2.1's replacement for feature profiles)

Part 5 is **not published** for 2.1. Part 2 is organised into 19 blocks:

| Block | Name | Block | Name |
|---|---|---|---|
| **A** | Security | **J** | Metering |
| **B** | Provisioning | **K** | SmartCharging |
| **C** | Authorization | **L** | Firmware |
| **D** | LocalAuthList | **M** | CertificateMgmt |
| **E** | Transactions | **N** | Diagnostics |
| **F** | RemoteControl | **O** | DisplayMessage |
| **G** | Availability | **P** | DataTransfer |
| **H** | Reservation | **Q** | Bidirectional / V2X ⭐ |
| **I** | Tariff & Cost ⭐ | **R** | DER Control ⭐ |
| | | **S** | BatterySwapping ⭐ |

⭐ = 2.1-only.

## Capability discovery

There is **no** `SupportedFeatureProfiles` variable and `BootNotification` announces nothing.

```
on BootNotification(Accepted)
  → GetBaseReport(ConfigurationInventory) → NotifyReport → read the device model
  → targeted GetVariables on "<X>Ctrlr.Available" / "<X>Ctrlr.Enabled[...]"
```

Probe at minimum, before exposing any tariff or payment endpoint:

| Variable | Gates |
|---|---|
| `TariffCostCtrlr.Available` | every tariff endpoint |
| `TariffCostCtrlr.Enabled[Tariff]` | local cost calculation |
| `TariffCostCtrlr.ConditionsSupported[Tariff]` | may reject your `conditions` ⇒ `ConditionNotSupported` |
| `TariffCostCtrlr.MaxElements[Tariff]` | how many prices you may send |
| `PaymentCtrlr.Available` / `.SettlementByCSMS` / `.ReceiptByCSMS` / `.AuthorizeDirectPayment` | settlement mode, receipts, ad-hoc payments |
| `WebPaymentsCtrlr.Available` | `NotifyWebPaymentStarted` |
| `SampledDataCtrlr.Available` / `.Enabled` / `.TxUpdatedInterval` | metering |
| `PriorityChargingCtrlr.Available` | `UsePriorityCharging` |
| `BatterySwappingCtrlr.*` | battery swap |
| `DerCtrlr.Available` | DER control |

| Result | Meaning | HTTP |
|---|---|---|
| `UnknownComponent` / `UnknownVariable` | **absent** | **501** + hide the feature |
| `Rejected` | exists but unreadable (WriteOnly) | **403** |
| `Accepted` with a value | present | — |

**Cache per station. Invalidate on every boot and after firmware reaches `Installed`.**

## Correlation and idempotency

| Your identifier | Maps to |
|---|---|
| `session_id` | `RequestStartTransaction.remoteStartId` |
| OCPP `transactionId` | **allocated by the station**; join on `Started` |
| `tariff_id` | `TariffType.tariffId` — **new id per content** |
| `reservation_id` | `ReserveNow.id` |
| `swap_op_id` | `RequestBatterySwap.requestId` |
| `report_op_id` | `GetBaseReport`/`GetReport.requestId` |
| `msg_id` | `MessageInfoType.id` (`SetDisplayMessage`) |
| `profile_id` | `ChargingProfileType.id` (re-sending replaces) |
| `monitor_id` | `SetVariableMonitoring.id` |
| `psp_ref` | `idToken.idToken` for `DirectPayment` → `NotifySettlement.pspRef` |

- **Inbound dedupe** on `(stationId, transactionId, seqNo)`, and on `(stationId, MessageId)` for
  retries.
- `MessageId` must **never** repeat for a station, **including across reconnects**.
- **Outbound idempotency:** `Idempotency-Key` → persist `key → (MessageId, status)` **before**
  sending. Store every mapping durably before the call goes out.
- **Never re-send `RequestStartTransaction`** on reconnect — the station owns the lifecycle.

### Reconnect reconciliation

```
socket dropped with sessions open
  → mark orphaned
  → on reconnect: GetTransactionStatus for each open session
       messagesInQueue == true  → wait
       messagesInQueue == false → close as estimated, alert
  → GetTariffs to confirm the tariff is still installed   (republish on NoTariff)
  → re-assert SetChargingProfile / SetVariables
  → NEVER re-send RequestStartTransaction
```

## What the CSMS should reject on your behalf

| Condition | Reply to you |
|---|---|
| station not connected | **409/503** `{chargerOffline: true, lastSeen}` |
| station negotiated only `ocpp2.0.1` | **501** on every tariff/payment endpoint + `{"requiredSubprotocol": "ocpp2.1"}` |
| capability probe says the block is absent | **501** + hide the feature from your UI |
| CALLERROR `NotImplemented` on a 2.1-only action | **501** + flip the per-station capability flag off permanently |
| CALLERROR `SecurityError` | **423** |
| CALLERROR `FormatViolation` | **502** — your payload is wrong; a bug in the CSMS |
| no reply in ~30 s | **504** — ambiguous; do not auto-retry non-idempotent ops |
| `DuplicateTariffId` | **409** — mint a new `tariffId` and retry once |
| `NoTariff` from `GetTariffs` | **404** + republish |
