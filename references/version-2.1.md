# OCPP-J 2.1 — build playbook

Use this when the CSMS negotiates `ocpp2.1`. For wire fields and enums, read `contract-2.1.md`.
For the full tariff and payment model, read `tariffs.md`. For money, read `billing.md`. For traps,
read `traps.md`.

## Identity card

```
subprotocol     : ocpp2.1
station identity: last non-empty path segment of the CSMS URL, percent-encoded, ≤ 48 chars, no ':'
session model   : TransactionEvent(Started) → (0..n) Updated → TransactionEvent(Ended)
transactionId   : ALLOCATED BY THE CHARGER, string ≤ 36  ← never mint one
message types   : 2 CALL · 3 CALLRESULT · 4 CALLERROR · 5 CALLRESULTERROR · 6 SEND   ← 5 and 6 are new
optional fields : OMIT them. null / {} / [] are invalid for an absent field.
```

You build the public HTTP API, not the CSMS. 2.1 is the first OCPP version with **native tariff,
payment and settlement**. If tariffs or prepayment are a product requirement, this is the version
you want — but **always keep a central meter-accounting fallback**, because stations routinely
ignore tariffs and `NotifySettlement` only appears for ad-hoc payments.

`RequestStartTransaction` and `RequestStopTransaction` are **byte-identical to 2.0.1** — migrating
from 2.0.1 is not work on those endpoints.

## Compatibility — negotiate, never assume

26 actions are **2.1-only**. A 2.0.1 station answers CALLERROR `NotImplemented` to every one,
silently killing your tariff and payment path:

`AFRRSignal` · `AdjustPeriodicEventStream` · `BatterySwap` · `ChangeTransactionTariff` ·
`ClearDERControl` · `ClearTariffs` · `ClosePeriodicEventStream` · `GetCertificateChainStatus` ·
`GetDERControl` · `GetPeriodicEventStream` · `GetTariffs` · `NotifyAllowedEnergyTransfer` ·
`NotifyDERAlarm` · `NotifyDERStartStop` · `NotifyPriorityCharging` · `NotifySettlement` ·
`NotifyWebPaymentStarted` · `OpenPeriodicEventStream` · `PullDynamicScheduleUpdate` ·
`ReportDERControl` · `RequestBatterySwap` · `SetDERControl` · `SetDefaultTariff` ·
`UpdateDynamicSchedule` · `UsePriorityCharging` · `VatNumberValidation`

Only negotiate `ocpp2.1` when the station offers it. Keep a per-station capability flag
(`supportsTariffs`, `supportsSettlement`) from the negotiated subprotocol plus device-model probing,
and fall back to central accounting when it is false.

## "Notify" lies — direction traps

| Message | Actual direction |
|---|---|
| `NotifyAllowedEnergyTransfer` | **CSMS → station** |
| `NotifyWebPaymentStarted` | **CSMS → station** (some stations also send it inbound — tolerate both) |
| `NotifySettlement` · `NotifyPriorityCharging` · `NotifyCustomerInformation` · `BatterySwap` · `NotifyDERAlarm` · `NotifyDERStartStop` · `ReportDERControl` · `ClosePeriodicEventStream` | **station → CSMS** |
| `PullDynamicScheduleUpdate` | **station → CSMS** — the station asks *you* |

Trust the spec, not the name. `Get15118EVCertificate` is station → CSMS in 2.1. `VatNumberValidation`
is CSMS → station: you ask, the station answers.

## Endpoint → OCPP operation

`*` required. Optional fields are **omitted**.

| Endpoint | OCPP operation | Payload fields to require | Reply → HTTP |
|---|---|---|---|
| `PUT /chargers/{id}/tariff` | `SetDefaultTariff` ⭐ | `evseId`* (`0` = **all** EVSEs), `tariff`* | `Accepted` → 200; `Rejected` → 422; `DuplicateTariffId` → **409** (mint a new id); `ConditionNotSupported` → 422; `TooManyElements` → 422 |
| `GET /chargers/{id}/tariffs` | `GetTariffs` ⭐ | `evseId`* | `Accepted` → 200 with `tariffAssignments`; `NoTariff` → 404 |
| `DELETE /chargers/{id}/tariffs` | `ClearTariffs` ⭐ | `tariffIds` (min 1), `evseId` | **per-tariff** `clearTariffsResult[].status`; **409** if any id is referenced by a live session |
| `PATCH /sessions/{id}/tariff` | `ChangeTransactionTariff` ⭐ | `transactionId`*, `tariff`* | `Accepted` → 200; `NoCurrencyChange` → **409**; `TxNotFound` → 404 |
| `POST /sessions` | `RequestStartTransaction` | `idToken`*, `remoteStartId`* (**yours**), `evseId`, `groupIdToken`, `chargingProfile` | `Accepted` → **202** `{status:"starting"}` |
| `POST /sessions/{id}/stop` | `RequestStopTransaction` | `transactionId`* (charger's) | `Accepted` → **202**; may only yield `Updated` |
| `POST /sessions/{id}/cost` | `CostUpdated` ⭐ | `totalCost`*, `transactionId`* | *(empty)* → 202; rate-limit to `Interval[Cost]` |
| `POST /sessions/{id}/limit` | `TransactionEventResponse.transactionLimit` | `maxCost` \| `maxEnergy` (Wh) \| `maxTime` (s) \| `maxSoC` (0-100) ⭐ | set on your `Started` reply → 200 |
| `POST /chargers/{id}/web-payment-lock` | `NotifyWebPaymentStarted` ⭐ | `evseId`* (≥ 0), `timeout`* (s) | *(empty)* → 202 |
| `POST /chargers/{id}/vat-validate` | `VatNumberValidation` ⭐ | `vatNumber`*, `evseId` | `GenericStatusEnumType` = `Accepted`\|`Rejected`; reason in `statusInfo.reasonCode`. Echo **`vatNumber`*** and `evseId`; `company`? |
| `POST /sessions/{id}/unlock` | `UnlockConnector` | `evseId`*, `connectorId`* | `Unlocked` → 200; `OngoingAuthorizedTransaction` → 409 |
| `PATCH /chargers/{id}/config` | `SetVariables` | `setVariableData[1..*]`* | 200 with a **per-item** status array |
| `GET /chargers/{id}/config` | `GetVariables` | `getVariableData[1..*]`* | 200; no wildcards |
| `POST /chargers/{id}/charging-profile` | `SetChargingProfile` | `evseId`*, `chargingProfile`* | `Accepted` → 200; CALLERROR `NotSupported` → **501** |
| `DELETE /chargers/{id}/charging-profile` | `ClearChargingProfile` | `chargingProfileId`, `chargingProfileCriteria` — **both absent = clear all** | `Accepted` → 200; `Unknown` → 404 |
| `POST /sessions/{id}/soft-stop` | `SetChargingProfile(TxProfile, limit 0)` | `evseId`* `chargingProfile`* | **the offline-safe stop** — survives reconnect |
| `POST /chargers/{id}/reservations` | `ReserveNow` | `id`* (**yours**), `expiryDateTime`*, `idToken`*, `evseId`, `connectorType`, `groupIdToken` | `Accepted` → 201; `Occupied`/`Rejected`/`Unavailable` → 409 |
| `DELETE /chargers/{id}/reservations/{rid}` | `CancelReservation` | `reservationId`* | `Accepted` → 200; `Rejected` → 404 |
| `GET /chargers/{id}/transaction-queue` | `GetTransactionStatus` | `transactionId` | `messagesInQueue`* — run before finalising |
| `POST /chargers/{id}/battery-swap` | `RequestBatterySwap` ⭐ | `idToken`*, `requestId`* (**yours**) | `Accepted` → 202; `Rejected` + `statusInfo.reasonCode = "NoBatteryAvailable"` → **409** |
| `POST /sessions/{id}/priority` | `UsePriorityCharging` ⭐ | `transactionId`*, `activate`* | `Accepted` → 200; `NoProfile` → **409** |
| `POST /chargers/{id}/availability` | `ChangeAvailability` | `operationalStatus`*, `evse` | `Scheduled` → **202** |
| `POST /chargers/{id}/reset` | `Reset` | `type`* = `Immediate`\|`OnIdle`\|**`ImmediateAndResume`** | `Accepted` → 202; socket drops |
| `POST /chargers/{id}/message` | `SetDisplayMessage` | `message`* | each `NotSupported*` → a distinct 4xx |

### Queue rules

**Do not queue:** `RequestStartTransaction`, `RequestStopTransaction`, `UnlockConnector`, `Reset`,
`CostUpdated`, `NotifyWebPaymentStarted`. Reject with **409/503**
`{chargerOffline:true, lastSeen}`.

**Safe to queue** (station persists and applies on boot): `SetChargingProfile`,
`ClearChargingProfile`, `SendLocalList`, `SetNetworkProfile`, `SetMonitoringBase`,
`SetMonitoringLevel`, `SetDisplayMessage`, `ChangeAvailability`.

## Event feed — what the CSMS must hand you

**`TransactionEvent` is your billing record**, plus `costDetails`.

| Field | Card | Use |
|---|---|---|
| `eventType`* | ✔ | `Started` / `Updated` / `Ended` |
| `timestamp`*, `triggerReason`*, `seqNo`*, `transactionInfo`* | ✔ | `seqNo` is **per-EVSE monotonic** — your completeness proof |
| `costDetails` ⭐ | 0..1 | **the station's own cost calculation** |
| `evseSleep` | 0..1 | EVSE slept inside the session |
| `preconditioningStatus` | 0..1 | cabin preconditioning |
| `transactionInfo.tariffId` ⭐ | 0..1 | which tariff priced this session |
| `transactionInfo.operationMode` | 0..1 | `Idle` `ChargingOnly` `CentralSetpoint` `ExternalSetpoint` `ExternalLimits` `CentralFrequency` `LocalFrequency` `LocalLoadBalancing` |
| `transactionInfo.transactionLimit` | 0..1 | read back the cap you set |
| `meterValue` | 0..* | your independent energy cross-check |
| `offline` | 0..1 | station buffered it — expect gaps |
| `idToken` | 0..1 | **`type = "DirectPayment"` ⇒ the value is the `pspRef`** |

`TransactionEventResponse` you send back: `totalCost`? · `chargingPriority`? ·
**`transactionLimit`** (your prepaid cap) · `idTokenInfo`? (required when the request carried
`idToken`) · `updatedPersonalMessage`? · `updatedPersonalMessageExtra` (0..4)?

`triggerReason` adds: `CostLimitReached` `EnergyLimitReached` `LimitSet` `OperationModeChanged`
`RunningCost` `SoCLimitReached` `TariffChanged` `TariffNotAccepted` `TimeLimitReached` `TxResumed`.

### The payments end-to-end flow

| # | Step | OCPP traffic |
|---|---|---|
| 0 | **Probe the device model** | `GetBaseReport(ConfigurationInventory)` → `NotifyReport`. Read `TariffCostCtrlr.*`, `PaymentCtrlr.*`, `WebPaymentsCtrlr.*`. **Gates steps 1-10** |
| 1 | **Publish the default tariff** | `SetDefaultTariff(evseId=0, tariff)` → installs at **every** EVSE. New content ⇒ **new `tariffId`** |
| 1b | Verify what the station holds | `GetTariffs(evseId)` → `tariffAssignments[]`. Reconcile drift; `NoTariff` ⇒ republish |
| 1c | Retire stale tariffs | `ClearTariffs(tariffIds?, evseId?)` — defaults only, never one in use by a live session |
| 2 | Driver-specific tariff *(optional)* | `Authorize(idToken)` → `AuthorizeResponse.tariff`. Then clear the Authorization Cache or the driver never re-authorizes |
| 3 | Reserve | `ReserveNow(id, expiryDateTime, idToken, evseId?, connectorType?, groupIdToken?)` |
| 4 | Ad-hoc prepay lock *(optional)* | `NotifyWebPaymentStarted(evseId, timeout)` — blocks a local start for `timeout` s |
| 5 | Payment kiosk | PSP authorises ⇒ `RequestStartTransaction(idToken.idToken = PspRef, idToken.type = "DirectPayment", idToken.additionalInfo[CardBin, CardLast4Digits…])` |
| 6 | **Prepaid cap** | On `Started`, reply `transactionLimit{maxCost}` — the station enforces it and later reports `triggerReason = CostLimitReached` |
| 7 | Meter accumulation | `TransactionEvent(Started/Updated).meterValue[]` — your independent cross-check |
| 7b | Running cost push | `CostUpdated(transactionId, totalCost)` — only when the station does **not** do local costing |
| 7c | Tariff swap mid-session | `ChangeTransactionTariff(transactionId, tariff)` ⇒ `Updated` with `triggerReason = TariffChanged` |
| 8 | Stop | `RequestStopTransaction(transactionId)` |
| 9 | **Final cost** | `TransactionEvent(Ended).costDetails` ⇒ **primary billing record** |
| 9b | No `costDetails` | **Fallback:** rate from `Energy.Active.Import.Register` with your own table, stamp `cost_source: "central"` |
| 10 | VAT | `VatNumberValidation(vatNumber, evseId?)` → **echo `vatNumber` and `evseId`** |
| 11 | **Settle** | `NotifySettlement(pspRef, status, settlementAmount, settlementTime, transactionId?, receiptId?, receiptUrl?, vatNumber?, vatCompany?)` ⭐ |
| 11b | Receipt | Reply `receiptUrl`? / `receiptId`? when `PaymentCtrlr.ReceiptByCSMS = true` |
| 11c | CSMS-side settlement | With `PaymentCtrlr.SettlementByCSMS = true` **you** call the PSP — **no `NotifySettlement` ever arrives** |

### Settlement state machine

```
RESERVED          ReserveNow Accepted
PENDING           RequestStartTransaction Accepted  /  NotifyWebPaymentStarted sent
ACTIVE            TransactionEvent(Started) + your transactionLimit applied
SUSPENDED         chargingState in {SuspendedEV, SuspendedEVSE, Idle}
ENDED             TransactionEvent(Ended)             → freeze cost
SETTLED           NotifySettlement(status = Settled)  → issue invoice
FAILED_SETTLEMENT NotifySettlement(Rejected | Failed) → retry the capture off-protocol
CANCELLED_PRE_TX  NotifySettlement(Canceled) with NO transactionId → driver cancelled, no charge
ABANDONED         socket closed with no Ended         → escalate to a claim, never auto-close
```

`PaymentStatusEnumType` = `Settled` · `Canceled` · `Rejected` · `Failed`.
(`"Cancelled"` appears in spec prose — the schema and enum use **single-L `Canceled`**.)

`pspRef` **is** the `idToken` value of a `DirectPayment` transaction. Correlate on
**`(pspRef, transactionId)`**, never on `pspRef` alone.

**`NotifySettlement` is not mandatory.** It is only sent for ad-hoc payments, and never when
`PaymentCtrlr.SettlementByCSMS = true`. Reconcile money movement from `NotifySettlement` **plus**
your own PSP ledger — those two must agree daily.

## Tariff model — the essentials

**There is NO `TariffStatus` enum, NO `Currency` enum and NO `PriceUnitType` enum.** `currency` is a
plain ISO-4217 `string[0..3]`, and the price unit is encoded in the **field name** (`priceKwh` =
per kWh, `priceMinute` = per minute, `priceFixed` = flat). All prices are **excluding tax**; tax is
layered via `taxRates`.

`TariffType`: `tariffId`* (≤60) `currency`* (≤3) `validFrom`? `description`? (0..10
`MessageContentType`) `energy`? `chargingTime`? `idleTime`? `fixedFee`? `reservationTime`?
`reservationFixed`? `minCost`? `maxCost`?

| Component | Type | Evaluated |
|---|---|---|
| `energy` | `TariffEnergyType{prices*(TariffEnergyPriceType{priceKwh*, conditions?}), taxRates?(0..5)}` | per kWh |
| `chargingTime` | `TariffTimeType{prices*(TariffTimePriceType{priceMinute*, conditions?}), taxRates?}` | per minute |
| `idleTime` | `TariffTimeType` | per minute |
| `fixedFee` | `TariffFixedType{prices*(TariffFixedPriceType{priceFixed*, conditions?}), taxRates?}` | once at session start |
| `reservationTime` / `reservationFixed` | `TariffTimeType` / `TariffFixedType` | once at reservation |

`TaxRateType`: `type`* (≤20, e.g. `"vat"`) · `tax`* (**a percentage** — `21.0` = 21 %) ·
`stack`? (≥ 0, default 0). Stack 0 applies to net, stack 1 on the stack-0 result, and so on.
**`taxRates` absent ≠ 0 %** — it means *no tax applies*.
`PriceType`: `exclTax`? `inclTax`? `taxRates`?(0..5). **`exclTax` is mandatory whenever `inclTax` is
present.**

Selection rules you must design around:

1. A price entry with **no `conditions`** is **always** applicable; when several match, **only the
   first in list order wins**. Always append an unconditional fallback entry **last**.
2. A tariff **cannot change mid-session** by itself — only via `ChangeTransactionTariff`.
3. A new tariff with `validFrom = T` **replaces** the existing default at `T`, never before.
4. On rejection the station deauthorizes and sends `triggerReason = TariffNotAccepted` — no
   `tariffId`, no cost. **Do not bill a tariff-less transaction.**
5. The session↔tariff association is reported exactly once via `transactionInfo.tariffId`.
6. **A Local Authorization List is incompatible with local cost calculation** unless the default
   tariff applies to every driver.
7. **I08.FR.09: do not set `TariffType.validFrom` in `AuthorizeResponse.tariff`.**
8. `tariffId` must be **immutable per content** (I08.FR.08). Different content ⇒ a different id.
9. Re-sending the same `tariffId` ⇒ `DuplicateTariffId`. To "refresh" a tariff, **mint a new id**.
10. `minCost`/`maxCost` mutate `typeOfCost` to `MinCost`/`MaxCost` — honour them in the invoice.
11. Currency **cannot change** mid-session (`NoCurrencyChange`).

Full data model and worked examples: `tariffs.md`.

## Energy / fallback accounting

Same register maths as 2.0.1:

```
wh = value × 10 ^ unitOfMeasure.multiplier
if unitOfMeasure.unit == "kWh": wh ×= 1000
```

- 2.1 adds `location = Upstream` — **not** transaction energy. Filter it out.
- Never sum across `location`. Never sum L1+L2+L3 when only the all-phase total is sent.
- `.Register` → difference. `.Interval` → sum. Never mix.
- Dedupe on `(transactionId, seqNo)` and **always reply** to `TransactionEvent`.

**Completeness proof (E13.2)** — billing is safe when you hold `Started` at seqNo *a*, `Ended` at
*o*, **and every n in [a, o]**. On a gap or `offline = true` ⇒ `GetTransactionStatus`;
`messagesInQueue == true` ⇒ defer.

Clock skew: store both the charger `timestamp` and your `received_at`. Use `received_at` for
ordering and TTL, the charger timestamp for billing windows. Quarantine `|skew| > 300 s`.

## Functional blocks

Part 5 is **not published** for 2.1. Part 2 is organised into 19 blocks — use them as your
capability matrix:

**A** Security · **B** Provisioning · **C** Authorization · **D** LocalAuthList · **E** Transactions
· **F** RemoteControl · **G** Availability · **H** Reservation · **I** Tariff & Cost ⭐ ·
**J** Metering · **K** SmartCharging · **L** Firmware · **M** CertificateMgmt · **N** Diagnostics ·
**O** DisplayMessage · **P** DataTransfer · **Q** Bidirectional/V2X ⭐ · **R** DER Control ⭐ ·
**S** BatterySwapping ⭐  (⭐ = 2.1-only)

Probe block **I** before exposing any tariff endpoint. Details: `contract-2.1.md`.

## 2.1-specific landmines

1. Never mint a `transactionId` — the station owns it.
2. Never re-send a `tariffId` with different content, and never "refresh" by re-sending — **mint a
   new id**.
3. Never set `TariffType.validFrom` in `AuthorizeResponse.tariff` (I08.FR.09).
4. Never omit the unconditional fallback entry in a `prices[]` list.
5. Never expect `NotifySettlement` — only ad-hoc payments send it, and never when
   `PaymentCtrlr.SettlementByCSMS = true`.
6. Never rely on `costDetails` alone — always fall back to meter accounting when it is absent or
   `failureToCalculate = true`.
7. Never change currency mid-session.
8. Never send an empty array for an optional list field — **omit the key** entirely (every `0..*`
   field has `minItems: 1`).
9. Never bill a transaction with no `transactionInfo.tariffId` when you expected a tariff — that is
   a `TariffNotAccepted` rejection, not a free session.
10. Never sum across `location`, and never include `Upstream` samples.
11. Never expose `OpenPeriodicEventStream` / `ClosePeriodicEventStream` on a station whose CSMS
    cannot receive `MessageTypeId 6` (SEND) — you would lose the stream silently.
12. Never return 200 from `POST /sessions` on `Accepted`.

More: `tariffs.md`, `traps.md` and `contract-2.1.md`.
