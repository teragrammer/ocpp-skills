# OCPP-J 2.0.1 — build playbook

Use this when the CSMS negotiates `ocpp2.0.1`. For wire fields and enums, read
`contract-2.0.1.md`. For money, read `billing.md`. For traps, read `traps.md`.

## Identity card

```
subprotocol     : ocpp2.0.1
station identity: last non-empty path segment of the CSMS URL, percent-encoded, ≤ 48 chars, no ':'
session model   : TransactionEvent(Started) → (0..n) TransactionEvent(Updated) → TransactionEvent(Ended)
transactionId   : ALLOCATED BY THE CHARGER, string ≤ 36  ← never mint one
pricing         : NONE. No tariff message exists in 2.0.1. You compute and push the cost.
```

You build the public HTTP API, not the CSMS. The CSMS owns the WebSocket, the envelope and the
station session. You need a **command contract** and an **event contract**.

## The 3-message transaction model — the #1 difference from 1.6

```
CSMS    ── RequestStartTransaction ─────▶ station   idToken + remoteStartId
station ── TransactionEvent(Started) ───▶ CSMS      ★ SESSION EXISTS — charger's transactionId
station ── TransactionEvent(Updated) ───▶ CSMS      0..n: meterValue[], chargingState
CSMS    ── RequestStopTransaction ──────▶ station   uses the CHARGER-assigned transactionId
station ── TransactionEvent(Ended) ─────▶ CSMS      ★ BILLING FINALISATION (final meterValue)
```

| | 1.6 | **2.0.1** |
|---|---|---|
| `transactionId` owner | **CSMS** (integer) | **charger** (string ≤ 36) |
| lifecycle | `StartTransaction`/`StopTransaction` | `TransactionEvent` Started/Updated/Ended |
| authorization result | `StartTransaction.conf.idTagInfo` | `TransactionEventResponse.idTokenInfo` |
| config | `ChangeConfiguration(key,value)` | `SetVariables(component,variable)` |
| token | `idTag` (string) | `IdToken{idToken, type}` |
| connector addressing | `connectorId` | `evseId` + `connectorId` |
| cost | none | **you** push it via `CostUpdated`; it is display-only |

`RequestStartTransactionResponse.transactionId` is present **only** when the station had already
started the transaction before your request (cable plugged first). Otherwise it is absent — so you
**cannot** return an OCPP transaction id from `POST /sessions`. Use **202** and your own
`session_id`; bind the OCPP id when `Started` arrives.

## Endpoint → OCPP operation

`*` = required. Optional fields are **omitted**, never `null`/`{}`/`[]`.

| Endpoint | OCPP operation | Payload fields to require | Reply → HTTP |
|---|---|---|---|
| `POST /sessions` | `RequestStartTransaction` | `idToken`*, `remoteStartId`* (**yours**), `evseId`, `groupIdToken`, `chargingProfile` | `Accepted` → **202** `{status:"starting"}`; `Rejected` → 409; offline → 409/503 |
| `POST /sessions/{id}/stop` | `RequestStopTransaction` | `transactionId`* (charger's string) | `Accepted` → **202**; may only yield `Updated`, not `Ended` |
| `POST /sessions/{id}/unlock` | `UnlockConnector` | `evseId`*, `connectorId`* | `Unlocked` → 200; `OngoingAuthorizedTransaction` → **409** |
| `PATCH /chargers/{id}/config` | `SetVariables` | `setVariableData[1..*]`* — `component`, `variable`, `componentVariable` | 200 with a **per-item** status array; only 400 if every item is `UnknownComponent` |
| `GET /chargers/{id}/config` | `GetVariables` | `getVariableData[1..*]`* — **no wildcards** | 200; `""` instance/variable means unset |
| `POST /chargers/{id}/charging-profile` | `SetChargingProfile` | `evseId`*, `chargingProfile`* | `Accepted` → 200; CALLERROR `NotSupported` → **501**, disable |
| `DELETE /chargers/{id}/charging-profile` | `ClearChargingProfile` | `chargingProfileId`, `chargingProfileCriteria` — **both absent = clear all** | `Accepted` → 200; `Unknown` → 404 |
| `GET /chargers/{id}/schedule` | `GetCompositeSchedule` | `evseId`*, `duration`* | `Accepted` → 200; `schedule` absent when `Rejected` |
| `GET /chargers/{id}/profiles` | `GetChargingProfiles` | `requestId`*, `chargingProfile`* | `Accepted` → 202; results stream back as `ReportChargingProfiles` |
| `POST /chargers/{id}/availability` | `ChangeAvailability` | `operationalStatus`*, `evse` | `Accepted` → 200; `Scheduled` → **202**; `Rejected` → 409 |
| `POST /chargers/{id}/reset` | `Reset` | `type`* = `Immediate`\|`OnIdle`, `evseId` | `Accepted` → 202; **socket drops**, drop cached tx state |
| `POST /chargers/{id}/reservations` | `ReserveNow` | `id`* (**yours**), `expiryDateTime`*, `idToken`*, `evseId`, `connectorType`, `groupIdToken` | `Accepted` → 201; `Occupied`/`Rejected`/`Unavailable` → 409 |
| `DELETE /chargers/{id}/reservations/{rid}` | `CancelReservation` | `reservationId`* | `Accepted` → 200; `Rejected` → 404 |
| `POST /sessions/{id}/cost` | `CostUpdated` | `totalCost`*, `transactionId`* | *(empty)* — **202**, the station just displays it |
| `GET /chargers/{id}/transaction-queue` | `GetTransactionStatus` | `transactionId` | `messagesInQueue`* — **run this before finalising any invoice** |
| `POST /chargers/{id}/trigger` | `TriggerMessage` | `requestedMessage`*, `evse` (`evse.id` > 0) | `Accepted` → 202 |
| `POST /chargers/{id}/message` | `SetDisplayMessage` | `message`* | `Accepted` → 200; each `NotSupported*` status → a distinct 4xx |
| `PUT /chargers/{id}/local-auth-list` | `SendLocalList` | `versionNumber`*, `updateType`*, `localAuthorizationList` | `Accepted` → 200; `Failed`/`VersionMismatch` → 409, resend as `Full` |
| `GET /chargers/{id}` | *(none — cached)* | — | serve cached `StatusNotification` |

### Queue rules

**Do not queue:** `RequestStartTransaction`, `RequestStopTransaction`, `UnlockConnector`, `Reset`,
`TriggerMessage`, `CostUpdated`, `DataTransfer`. Reject with **409/503**
`{chargerOffline:true, lastSeen}`. A queued `RequestStopTransaction` can hit a **recycled**
`transactionId` and stop the wrong session.

**Safe to queue** (station persists and applies on boot): `SetChargingProfile`,
`ClearChargingProfile`, `SendLocalList`, `SetNetworkProfile`, `SetDisplayMessage`,
`ChangeAvailability`.

## Event feed — what the CSMS must hand you

**`TransactionEvent` is your billing record.** Every inbound event you care about lives in it.

| Field | Required | Use |
|---|---|---|
| `eventType`* | ✔ | `Started` / `Updated` / `Ended` — drives your state machine |
| `timestamp`* | ✔ | the **charger** clock; keep your `received_at` too |
| `triggerReason`* | ✔ | why the event was sent |
| `seqNo`* | ✔ | **per-EVSE monotonic**; the only way to prove you have every message |
| `transactionInfo`* | ✔ | `transactionId`*, `chargingState`, `timeSpentCharging`, `stoppedReason`, `remoteStartId` |
| `meterValue` | 0..* | the energy. Absent on `Ended` is **legal** |
| `offline` | 0..1 | `true` ⇒ the station buffered this; there may be gaps |
| `idToken` | 0..1 | present at auth start and auth end; **persist the first one** |
| `evse`, `reservationId`, `numberOfPhasesUsed`, `cableMaxCurrent` | 0..1 | optional detail |

| OCPP message | Response you get | Why |
|---|---|---|
| `TransactionEvent` | `TransactionEventResponse`: `totalCost`?, `chargingPriority`?, **`idTokenInfo`** (required when the request carried `idToken`), `updatedPersonalMessage`? | session lifecycle + authorization |
| `Authorize` | `idTokenInfo`*, `certificateStatus`? | gate a token before you start |
| `StatusNotification` | *(empty)* | connector availability in your UI |
| `MeterValues` | *(empty)* | **never transaction-linked in 2.0.1** — bulk/energy-mode only. Do not use for billing |
| `BootNotification` | — | CSMS business; ask for a station-online event instead |

**Correlation — the two joins you must implement:**

1. `session_id ↔ transactionId`: bind on `TransactionEvent(Started)` by matching
   `transactionInfo.remoteStartId` against your outstanding `RequestStartTransaction`. Fall back to
   `(stationId, evseId, Started timestamp)` when no remote start was used.
2. Dedupe on **`(stationId, transactionId, seqNo)`**.

`idToken` appears once when authorization starts and once when it ends — and is **absent** when the
session was ended by `RequestStopTransaction` or `Reset`. Persist the first one; never require it on
`Ended`.

## Billing — the whole formula

2.0.1 is **still CSMS-priced**. There is no tariff message, so you rate everything.

```
start_wh  = Energy.Active.Import.Register, context == "Transaction.Begin"   (on Started)
end_wh    = Energy.Active.Import.Register, context == "Transaction.End"     (on Ended)
energy_wh = end_wh − start_wh
kWh       = energy_wh / 1000
```

Per-sample normalisation (2.x only — this does not exist in 1.6):

```
wh = value × 10^unitOfMeasure.multiplier      # multiplier is an EXPONENT to base 10
if unitOfMeasure.unit == "kWh": wh ×= 1000
```

> **`multiplier` is `10^n`, not a unit conversion.** A value of `4.9` with
> `unit: "kWh", multiplier: 0` is **4900 Wh**, not 4.9 Wh. A value of `4900` with
> `unit: "kWh", multiplier: 0` is **4,900,000 Wh (4900 kWh)**. Forgetting the `× 1000` unit factor
> is the most common 2.x billing bug.

Non-negotiables:

- `.Register` is cumulative — **difference**. `.Interval` is a delta — **sum**. Never mix.
- Prefer `location = "Outlet"`. If both `Inlet` and `Outlet` arrive, **never sum them**.
- If `SampledDataCtrlr.RegisterValuesWithoutPhases == true`, only the all-phase total is sent —
  never sum L1+L2+L3 yourself.
- `Ended` with **no** `meterValue` is legal. Bill from the last `Updated` sample and mark
  `estimated: true`.
- `stoppedReason` **may be omitted** → default `Local`, never `Unknown`.

### Prove you have every message before you bill

`seqNo` is per-EVSE and monotonic. Completeness proof:

```
Started at seqNo = a ,  Ended at seqNo = o
every n in [a, o] present  →  billing is safe
```

On a gap, or when `offline == true`:

```
GetTransactionStatus(transactionId)
  messagesInQueue == true   → DEFER billing, poll again
  messagesInQueue == false  → close as estimated: true, flag gaps, alert ops
```

This is the single most important control in 2.0.1. Without it you will bill sessions whose meter
data has holes.

Push the running cost with `CostUpdated(totalCost, transactionId)` at a rate no faster than
`Interval[Cost]` — it is for the station's **display**, never your invoice source.

See `billing.md` for the measurand table, rate snapshotting and the invoice shape.

## Payments

2.0.1 has **no payment, VAT or settlement message** — those are 2.1-only. Payment is entirely
yours, driven off `TransactionEvent`:

- **Prepaid:** authorise the card at your API, start with `idToken` bound to that payment, then
  enforce the cap by pushing a `SetChargingProfile` `TxProfile` with an amp limit. Watch
  `TransactionEvent(Updated).transactionInfo.timeSpentCharging` and
  `triggerReason == "CostLimitReached"` to stop on time.
- **Postpaid:** rate the session yourself, invoice on `Ended`.
- **Refund on early stop:** prorate from the meter, never from the authorisation amount.
- **Reserve funds:** for long sessions, authorise an estimate and top up when `totalCost` crosses a
  threshold, since 2.0.1 gives you no in-protocol way to demand more money mid-session.

## 2.0.1-specific landmines

1. Never mint a `transactionId` — **the charger owns it**.
2. Never return 200 from `POST /sessions` on `Accepted`, and never return an OCPP `transactionId`
   you do not have.
3. Never finalise an invoice without the `seqNo` completeness proof (or a `GetTransactionStatus`
   check).
4. Never treat `SetVariables` as all-or-nothing — read **every** element of `setVariableResult`.
5. Never wildcard an `instance` in `GetVariables` — you get `UnknownComponent`/`UnknownVariable`.
6. Never read back `SecurityCtrlr.BasicAuthPassword` — it is WriteOnly, returns `Rejected`.
7. Never treat `SuspendedEV`/`SuspendedEVSE`/`Idle` as the end of a session — only `Ended` is.
8. Never close an `Ended` event because the last `chargingState` was `Charging` — `Ended` wins.
9. Never read `unitOfMeasure.multiplier` as a unit factor.
10. Never use 1.6 config names (`TxEnabled`, `MeterValuesSampledData`, `SignedMeterValue`) — they
    do not exist here. Use `SampledDataCtrlr.Enabled`, `SampledDataCtrlr.TxUpdatedInterval`,
    `SampledDataCtrlr.TxUpdatedMeasurands`, `SampledDataCtrlr.SignReadings`.
11. Never add extra keys to a payload — schemas are `additionalProperties: false`. Use
    `customData` or `DataTransfer`.
12. Never lower `SecurityCtrlr.SecurityProfile` from a public API endpoint.

More: `traps.md` and `contract-2.0.1.md`.
