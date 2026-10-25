# OCPP-J 1.6 — build playbook

Use this when the CSMS negotiates `ocpp1.6`. For wire fields and enums, read
`contract-1.6.md`. For money, read `billing.md`. For traps, read `traps.md`.

## Identity card

```
subprotocol     : ocpp1.6
station identity: last non-empty path segment of the CSMS URL, percent-encoded
session model   : StartTransaction.req → (0..n) MeterValues → StopTransaction.req
transactionId   : ALLOCATED BY THE CSMS, integer  ← you must hand it back on stop
pricing         : NONE. 1.6 has no cost, currency, price or tariff field anywhere.
```

You build the public HTTP API. You do **not** build the OCPP central system. The CSMS owns the
WebSocket, the `ocpp1.6` subprotocol, the RPC envelope and the charger session. You own
authorization, money, invoicing and the product surface.

## The five messages your API lives on

```
CSMS    ── RemoteStartTransaction ──▶ charger    your POST /sessions
charger ── Authorize ──────────────▶ CSMS       "may idTag X charge?" → idTagInfo
charger ── StartTransaction ───────▶ CSMS       ★ SESSION EXISTS. meterStart (Wh), idTag, connectorId
CSMS    ── conf(transactionId, idTagInfo) ────▶ charger   ← idTagInfo is the LAST authz gate
charger ── MeterValues (0..n) ─────▶ CSMS       time series; transactionId is OPTIONAL
charger ── StopTransaction ────────▶ CSMS       ★ meterStop (Wh) — the billing truth
```

`BootNotification`, `Heartbeat`, `SignCertificate`, `SecurityEventNotification` and
`FirmwareStatusNotification` are CSMS business. Ask for a forwarded station-online event instead of
modelling them in your API.

## Endpoint → OCPP operation

`→` is what the CSMS issues on your behalf. `*` = required by the spec. Optional fields are
**omitted**, never sent as `null`/`""`/`{}`/`[]`.

| Endpoint | OCPP operation | Payload fields to require | Reply → HTTP |
|---|---|---|---|
| `POST /sessions` | `RemoteStartTransaction` | `idTag`*, `connectorId` (>0), `chargingProfile`? | `Accepted` → **202** `{status:"starting"}`; `Rejected` → **409**; offline → **409** |
| `POST /sessions/{id}/stop` | `RemoteStopTransaction` | `transactionId`* (yours) | `Accepted` → **202**; do **not** finalise billing here |
| `POST /sessions/{id}/unlock` | `UnlockConnector` | `connectorId`* >0 | `Unlocked` → **200**; expect an unsolicited `StopTransaction` first |
| `POST /chargers/{id}/availability` | `ChangeAvailability` | `connectorId`* (0 = all), `type`* | `Accepted` → 200; `Scheduled` → **202**; `Unavailable`/`Rejected` → 409 |
| `PATCH /chargers/{id}/config` | `ChangeConfiguration` | `key`* (≤50), `value`* (≤500) | `Accepted` → 200; `RebootRequired` → 200 + `{rebootRequired:true}`; `Rejected`/`NotSupported` → 409 |
| `GET /chargers/{id}/config` | `GetConfiguration` | `key[]`? — **omit to get all** | 200; absent key → `NotSupported` |
| `POST /chargers/{id}/charging-profile` | `SetChargingProfile` | `connectorId`*, `csChargingProfiles`* | `Accepted` → 200; CALLERROR `NotSupported` → **501** and disable the feature |
| `DELETE /chargers/{id}/charging-profile` | `ClearChargingProfile` | `chargingProfileId`? `chargingProfileCriteria`? — **both absent = clear all** | `Accepted` → 200; `Unknown` → 404 |
| `GET /chargers/{id}/schedule` | `GetCompositeSchedule` | `connectorId`*, `duration`* | `Accepted` → 200; indicative only, never authoritative |
| `POST /chargers/{id}/reset` | `Reset` | `type`* = `Soft`\|`Hard` | `Accepted` → 202; **socket drops right after** |
| `POST /chargers/{id}/reservations` | `ReserveNow` | `connectorId`*, `expiryDate`*, `idTag`*, `reservationId`* (yours), `parentIdTag`? | `Accepted` → 201; `Occupied`/`Rejected`/`Faulted` → 409 |
| `DELETE /chargers/{id}/reservations/{rid}` | `CancelReservation` | `reservationId`* | `Accepted` → 200 |
| `POST /chargers/{id}/trigger` | `TriggerMessage` | `requestedMessage`*, `connectorId` >0 | `Accepted` → 202; never trigger `BootNotification` |
| `PUT /chargers/{id}/local-auth-list` | `SendLocalList` | `listVersion`*, `updateType`*, `localAuthorizationList`? | `Accepted` → 200; `Failed`/`VersionMismatch` → 409, resend as `Full` |
| `GET /chargers/{id}` | *(none — cached)* | — | serve cached `StatusNotification`; stale by up to `MinimumStatusDuration` |

### Queue rules

**Do not queue** — these need a live socket and go stale or retarget: `RemoteStartTransaction`,
`RemoteStopTransaction`, `UnlockConnector`, `Reset`, `TriggerMessage`, `UpdateFirmware`,
certificates. A queued `RemoteStopTransaction` can hit a **recycled** `transactionId` after a
reconnect and stop the wrong session. Reject with **409/503**
`{chargerOffline:true, lastSeen}`.

**Safe to queue** (charger persists and applies on boot): `ChangeConfiguration`,
`ChangeAvailability`, `SetChargingProfile`, `ClearChargingProfile`, `SendLocalList`,
`GetConfiguration`, `ClearCache`.

## Event feed — what the CSMS must hand you

| OCPP message | Fields you need | Why |
|---|---|---|
| `StartTransaction.req` | `connectorId` `idTag` **`meterStart`** `timestamp` `reservationId`? | create the session; meterStart is your energy origin |
| `StartTransaction.conf` | **`transactionId`** `idTagInfo` | the only place the transactionId exists — bind it to your `session_id` **here** |
| `MeterValues.req` | `connectorId` `meterValue[]` (`timestamp`, `sampledValue[]`: `value`, `context`, `format`, `measurand`, `location`, `phase`, `unit`) | running energy + cost display. `transactionId` may be **absent** |
| `StopTransaction.req` | **`meterStop`** `transactionId` `timestamp` `reason`? `idTag`? `transactionData`? | finalise billing |
| `StopTransaction.conf` | `idTagInfo`? | last authz outcome; **optional** — do not require it |
| `Authorize.conf` | `idTagInfo{status, parentIdTag?, expiryDate?}` | gate the token before you start |
| `StatusNotification.req` | `connectorId` `status` `errorCode` `timestamp` | connector availability in your UI |

**Correlation:** your `session_id` ↔ OCPP `transactionId`, stored durably at
`StartTransaction.conf`. `MeterValues.transactionId` is optional — attribute samples to the open
session by `(station, connectorId, timestamp)`, never by arrival order.

**Dedup key:** `(station, action, transactionId, timestamp)`. Chargers queue offline messages and
replay them chronologically; retries duplicate.

## Billing — the whole formula

```
session_wh  = StopTransaction.meterStop − StartTransaction.meterStart   # authoritative
session_kWh = session_wh / 1000
```

Both are **Wh**, from the same connector. `meterStart`/`meterStop` are the only numbers you bill on.

There is **no price in 1.6** — you own the entire rating engine. Shape it as
`price(energy, time, conditions, tariff) → amount`, versioned and snapshotted onto the invoice at
session start, so later tariff edits never retro-price a closed session.

From `MeterValues` (display + cross-check only):

```
wh = value × 1000            if unit == "kWh"
wh = value                    if unit == "Wh"   (the default)
Energy.Active.Import.Register → CUMULATIVE, difference it   (never sum)
Energy.Active.Import.Interval → DELTA,        sum it        (never difference)
```

Rules that prevent real money bugs:

- Never sum `...Import.Register`. It is an absolute meter register.
- `format = SignedData` → unusable for billing; route to review, never to the accumulator.
- Same connector only. Never mix `connectorId 0` (main meter) with connector N.
- Never sum across `location` (`Inlet` vs `Outlet`) or across `phase`.
- Order by `timestamp`, never by arrival. Store both the charger timestamp and your `received_at`;
  use `received_at` for ordering/TTL and the charger timestamp for billing windows.
- `reason` may be **absent** in `StopTransaction` → default `Local`, never `Unknown`.
- `meterStop < meterStart` = meter reset, **not** wraparound. Quarantine; never re-base.
- Orphaned sessions (power loss, `Reset`) → close from the last sample, mark `estimated: true`,
  alert ops.

See `billing.md` for the rating-engine shape, authorization gating and invoice schema.

## Payments

1.6 has no payment, price, VAT or settlement message. Payment is entirely yours:

- **Prepaid / ad-hoc:** authorise the card at your API, then start with an `idTag` bound to that
  payment. Enforce the cap by pushing a `SetChargingProfile` with a `chargingLimit` on the
  `chargingSchedulePeriod`, not by polling the card.
- **Postpaid:** rate the session yourself and invoice.
- **Refund on early stop:** prorate from the meter, never from the payment authorisation amount.

## 1.6-specific landmines

1. Never use `connectorId = 0` on `RemoteStartTransaction`, `TriggerMessage` or `UnlockConnector` —
   spec violation. `0` means "all" only in `ChangeAvailability` (and conditionally `ReserveNow`).
2. Never return **200** from `POST /sessions` on `Accepted` — charging has not started. Use 202.
3. Never read `RemoteStartTransaction.conf` as an authorization result — it returns `status` only.
4. Never require `idTagInfo` on `StopTransaction.conf` — it is optional.
5. Never bill from `MeterValues` alone; `meterStop − meterStart` is the truth.
6. Never send `SendLocalList` with `updateType: Full` and an empty list — it **wipes** the list.
7. Never infer station availability from `StatusNotification(connectorId = 0)`.
8. Never send `null`/`""`/`{}`/`[]` for an absent optional field — omit the key.
9. Never send a `chargingProfile` inside `RemoteStartTransaction` unless it is a `TxProfile`.
10. Never look for 2.x concepts (`SetVariables`, `TransactionEvent`, `IdTokenInfo`, `TotalCost`,
    `TariffType`, `CostUpdated`) in 1.6 — they do not exist.

More: `traps.md` and `contract-1.6.md`.
