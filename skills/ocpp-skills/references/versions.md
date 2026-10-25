# Choosing, comparing and migrating OCPP versions

The version is a **wire contract**, not a feature flag. Pick one per charger from the negotiated
WebSocket subprotocol and keep it on the station record.

| Subprotocol | Marketing name | This skill's playbook |
|---|---|---|
| `ocpp1.6` | OCPP-J 1.6 | `version-1.6.md` |
| `ocpp2.0.1` | OCPP-J 2.0.1 | `version-2.0.1.md` |
| `ocpp2.1` | OCPP-J 2.1 | `version-2.1.md` |

## How to identify the version

Authoritative sources, in order:

1. The **negotiated WebSocket subprotocol** (`Sec-WebSocket-Protocol`) — the only value the CSMS and
   charger actually agreed on.
2. The charger's connection record / CSMS database row.
3. The repository's CSMS adapter or generated types (`ocpp1.6`, `ocpp2.0.1`, `ocpp2.1`).
4. `BootNotification.chargingStation` model/firmware, then the vendor datasheet.

`BootNotification` does not carry a version field. A charger model number is not proof. If two
sources disagree, trust the negotiated subprotocol and record the conflict.

## Which version should you build?

| Requirement | Recommended | Why |
|---|---|---|
| Existing fleet of 1.6 chargers | 1.6 | Do not force a firmware migration for an API feature. |
| New AC fleet, no tariff/payment requirement | 2.0.1 | Modern device model, `TransactionEvent`, `IdToken`; no 2.1-only complexity. |
| Tariffs published to the charger, station-side cost, VAT, settlement | 2.1 | The only version with native tariff and payment messages. |
| Prepaid card flow with a hard cap | 2.1 preferred, 2.0.1 fallback | 2.1 has `transactionLimit`; older versions need amp limits + polling. |
| Plug & Charge / ISO 15118 | 2.0.1 or 2.1 | 1.6 has only the SecurityExtension. |
| V2X, DER, battery swap, periodic event streams | 2.1 | 2.1-only functional blocks Q/R/S and message types 5/6. |
| Must support every charger in a mixed fleet | Build an adapter per version | Do not make one version's concepts leak into another. |

The API's public shape can stay stable across versions. Keep a **canonical internal model** and put
version differences in an adapter — not in every handler.

## Full comparison

| Area | 1.6 | 2.0.1 | 2.1 |
|---|---|---|---|
| Envelope message types | 2 CALL, 3 CALLRESULT, 4 CALLERROR | same | + 5 CALLRESULTERROR, 6 SEND |
| Envelope id name | `uniqueId` | `uniqueId` | `MessageId` |
| Station identity | last non-empty path segment of CSMS URL, percent-encoded | same, ≤ 48 chars, no `:` | same |
| Transaction start | charger `StartTransaction.req`; CSMS returns `transactionId` | `TransactionEvent(Started)`; charger owns `transactionId` | same |
| Transaction updates | `MeterValues.req` | `TransactionEvent(Updated)` | same |
| Transaction end | `StopTransaction.req` with `meterStop` | `TransactionEvent(Ended)` | same |
| Transaction id | CSMS integer | charger string ≤ 36 | charger string ≤ 36 |
| Auth token | `idTag` string | `IdToken{idToken, type}` | same + `DirectPayment` |
| Auth result | `IdTagInfo` | `idTokenInfo` | same + optional `tariff` |
| Config | flat `key`/`value` | `component`/`variable`/`instance` | same |
| Connector address | `connectorId` | `evseId` + `connectorId` | same |
| Charging profile | `connectorId`, `csChargingProfiles` | `evseId`, `chargingProfile` | same |
| Reservation | `connectorId`, `reservationId`, `expiryDate` | `id`, `evseId`, `expiryDateTime` | same |
| Reset types | `Soft`/`Hard` | `Immediate`/`OnIdle` | + `ImmediateAndResume` |
| Availability | `connectorId`, `type` | `operationalStatus`, `evse` | same |
| Local auth list | `listVersion` | `versionNumber` | same |
| Price / tariff | none | none | `SetDefaultTariff`, `GetTariffs`, `ClearTariffs`, `ChangeTransactionTariff`, `costDetails` |
| Payment / settlement | none | none | `NotifySettlement`, `NotifyWebPaymentStarted`, `VatNumberValidation`, `transactionLimit` |
| Message-size / feature model | Part 5 profiles | Part 5 profiles | 19 functional blocks (Part 5 unpublished) |
| Completeness | none (dedupe only) | `seqNo` per EVSE | `seqNo` per EVSE |
| `format` values | `Raw`/`SignedData` | `Raw`/`SignedData` | `Raw`/`SignedData`/`SignedData` variants |
| Meter `location` | `Inlet`/`Outlet` | `Body`/`Cable`/`EV`/`Inlet`/`Outlet` | + `Upstream` |
| Error spelling | `OccurenceConstraintViolation`, `FormationViolation` | `OccurenceConstraintViolation`, `FormatViolation` | `OccurrenceConstraintViolation`, `FormatViolation` |

## Session lifecycle

**1.6** — the CSMS owns the id:

```
POST /sessions
  → CSMS RemoteStartTransaction(idTag, connectorId)
  → charger Authorize(idTag)                         [optional gate]
  → charger StartTransaction(meterStart, idTag)      ★ session exists
  → CSMS StartTransaction.conf(transactionId)        ★ bind your session_id here
  → charger MeterValues(0..n)                        transactionId optional
  → charger StopTransaction(meterStop)               ★ billing truth
  → CSMS StopTransaction.conf(idTagInfo?)            optional
```

**2.0.1 / 2.1** — the charger owns the id:

```
POST /sessions
  → CSMS RequestStartTransaction(idToken, remoteStartId)
  → charger TransactionEvent(Started)                ★ session exists, charger transactionId
  → API reply may carry idTokenInfo / transactionLimit (2.1)
  → charger TransactionEvent(Updated)(0..n)          seqNo increments
  → CSMS RequestStopTransaction(transactionId)
  → charger TransactionEvent(Ended)                  ★ billing finalisation
```

`RequestStartTransactionResponse.transactionId` is present **only** if the station had already
started the transaction before your request (cable plugged first). Never depend on it.

## Capability negotiation

### 1.6

Feature support is advertised in the charger's configuration (`SupportedFeatureProfiles`,
`AdditionalSupportedFeatureProfiles`, `ChargePointModel`, etc.). Read it with `GetConfiguration`
and cache it. SmartCharging can still answer CALLERROR `NotSupported` — degrade to **501** and
disable the feature for that station.

### 2.0.1 and 2.1

There is **no** `SupportedFeatureProfiles` variable and `BootNotification` announces nothing.

```
on BootNotification(Accepted)
  → GetBaseReport(ConfigurationInventory)   → NotifyReport (assemble until tbc == false)
  → read the device model
  → targeted GetVariables on "<X>Ctrlr.Available" / "<X>Ctrlr.Enabled"
  → store per-station capability flags
```

| Probe result | Meaning | Public API |
|---|---|---|
| `UnknownComponent` / `UnknownVariable` | absent | **501** + hide the feature |
| `Rejected` | exists but unreadable (WriteOnly) | **403**, never 404 |
| `Accepted` + value | present | enable |

Probe at minimum: `SampledDataCtrlr.*`, `SmartChargingCtrlr.Available`,
`ReservationCtrlr.Available`, `RemoteTriggerCtrlr.Available`, `DisplayMessageCtrlr.Available`,
`SecurityCtrlr.Available`, `AuthCtrlr.Available`, `LocalAuthListCtrlr.Enabled`.

For 2.1, additionally probe `TariffCostCtrlr.Available`, `TariffCostCtrlr.Enabled[Tariff]`,
`TariffCostCtrlr.ConditionsSupported[Tariff]`, `TariffCostCtrlr.MaxElements[Tariff]`,
`PaymentCtrlr.Available`, `PaymentCtrlr.SettlementByCSMS`, `PaymentCtrlr.ReceiptByCSMS`,
`PaymentCtrlr.AuthorizeDirectPayment`, `WebPaymentsCtrlr.Available`,
`PriorityChargingCtrlr.Available`, `BatterySwappingCtrlr.*`, `DerCtrlr.Available`.

Cache the result per station. Invalidate on every `BootNotification` and after firmware reaches
`Installed` — a firmware update can add or remove capabilities.

## Migrating 1.6 → 2.0.1

This is a **data-model migration**, not a field rename.

| 1.6 | 2.0.1 | Migration note |
|---|---|---|
| `StartTransaction` + `StopTransaction` | `TransactionEvent` S/U/E | Rebuild the session state machine around events. |
| CSMS-allocated integer `transactionId` | charger string `transactionId` | Drop your allocator; add a `transactionId` binding table keyed by `remoteStartId`. |
| `idTag` | `IdToken{idToken, type}` | Store the type. `Central`, `eMAID`, `ISO14443`, `ISO15693`, `KeyCode`, `Local`, `MacAddress`, `NoAuthorization`. |
| `IdTagInfo` | `idTokenInfo` | `NoCredit` is new and useful for prepaid. |
| `ChangeConfiguration(key, value)` | `SetVariables(component, variable, value)` | Build a key→component/variable mapping table; partial success is normal. |
| `GetConfiguration` | `GetVariables` | No wildcards. `""` means default instance, not all. |
| `connectorId` | `evseId` + `connectorId` | Your public API should expose an EVSE/connector pair, not a single integer. |
| `MeterValues` linked by `transactionId` | `TransactionEvent.meterValue` | 2.x `MeterValues.req` is **not** transaction-linked; never bill from it. |
| `meterStop − meterStart` | register delta at `Transaction.Begin`/`End` | Add `unitOfMeasure.multiplier` normalisation. |
| No completeness proof | `seqNo` per EVSE | Add `GetTransactionStatus` reconciliation. |
| No standard cost | `CostUpdated` (display only) | Your rate engine is still authoritative. |
| `Soft`/`Hard` reset | `Immediate`/`OnIdle` | Map your API's reset types explicitly. |
| `listVersion` | `versionNumber` | Watch `Full` + empty list — it wipes the list. |

Things that **do not** carry over: `TxEnabled`, `MeterValuesSampledData`, `SignedMeterValue`,
`RegisterType`, `SupportedFeatureProfiles`, flat config keys. Do not write compatibility shims that
send 1.6 config keys to a 2.x station; they will be rejected or, worse, silently ignored.

## Migrating 2.0.1 → 2.1

2.1 is largely additive. `RequestStartTransaction` and `RequestStopTransaction` are
**byte-identical** to 2.0.1 — migrating those endpoints is not work.

What you must gate:

- **26 actions are 2.1-only.** A 2.0.1 station answers CALLERROR `NotImplemented` to every one,
  without breaking the session. Your tariff/payment path then fails **quietly**. Keep a per-station
  capability flag and expose those endpoints only when the flag is on.
- **Message types 5 and 6.** `CALLRESULTERROR` and `SEND` are new. If your CSMS cannot receive
  `MessageTypeId 6`, do not expose periodic event streams — they will return 202 and deliver nothing.
- **`Reset(ImmediateAndResume)`** may **not** end the session. Reconcile with
  `GetTransactionStatus`; do not assume a stop.
- **`location = Upstream`** is new metering and is not transaction energy. Filter it out.
- **`costDetails`** is new. You still need central accounting: compute both, store both, reconcile.
- **`transactionLimit`** replaces the amp-limit hack as the prepaid mechanism. Use `maxCost` for
  cards.
- **Settlement** adds `NotifySettlement`, `NotifyWebPaymentStarted`, `VatNumberValidation`. All are
  optional and depend on `PaymentCtrlr` variables — probe before exposing them.

The 26 2.1-only actions:

`AFRRSignal` · `AdjustPeriodicEventStream` · `BatterySwap` · `ChangeTransactionTariff` ·
`ClearDERControl` · `ClearTariffs` · `ClosePeriodicEventStream` · `GetCertificateChainStatus` ·
`GetDERControl` · `GetPeriodicEventStream` · `GetTariffs` · `NotifyAllowedEnergyTransfer` ·
`NotifyDERAlarm` · `NotifyDERStartStop` · `NotifyPriorityCharging` · `NotifySettlement` ·
`NotifyWebPaymentStarted` · `OpenPeriodicEventStream` · `PullDynamicScheduleUpdate` ·
`ReportDERControl` · `RequestBatterySwap` · `SetDERControl` · `SetDefaultTariff` ·
`UpdateDynamicSchedule` · `UsePriorityCharging` · `VatNumberValidation`

## Designing a multi-version backend

Keep three layers:

1. **Public API / domain** — stable across versions: `Charger`, `Connector`, `Session`, `Tariff`,
   `Invoice`, `Payment`. No `idTag`, `evseId` or `seqNo` leaking into every handler.
2. **Version adapter** — one per subprotocol. Maps domain commands to OCPP operations and OCPP
   events to domain events. Owns version-specific identity, status enums and error spells.
3. **CSMS client** — transport, correlation, timeouts, retries, idempotency. It should not know
   what a tariff is.

Rules for the adapter boundary:

- A station has exactly one negotiated subprotocol. Store it; never infer it per message.
- Capability flags are per station **and per version**. A firmware downgrade invalidates them.
- The adapter translates OCPP statuses to a small internal enum (`OK`, `REJECTED`, `CONFLICT`,
  `UNSUPPORTED`, `OFFLINE`, `TIMEOUT`) and the HTTP layer maps that to 2xx/4xx/5xx.
- Feature endpoints exist only when the adapter advertises them. Return **501** with
  `{requiredSubprotocol: "ocpp2.1"}` for a 2.1-only feature on a 2.0.1 station.
- Never send a 2.1-only message to a 2.0.1 station "to see if it works"; it returns `NotImplemented`
  and can leave your feature flag in a half-on state.

## Mixed-fleet rules

- A 1.6 charger and a 2.1 charger can share the same public API, but not the same session table
  shape. Use nullable version-specific columns or a JSON `raw` column beside the canonical fields.
- Never backfill a 2.x `seqNo` onto a 1.6 session. Leave it `null`; your completeness logic must
  branch on version.
- Never compare a 1.6 integer `transactionId` with a 2.x string. Namespace transaction ids by
  `(station_id, version, transaction_id)`.
- Invoices must carry `ocpp_version`, `cost_source` and `sequence_complete`. Finance needs to know
  which rules produced the number.
