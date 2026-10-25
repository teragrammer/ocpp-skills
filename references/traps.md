# Trap catalogue — cross-version

These are the defects that reach production. Use the symptom index first, then the section. For
wire-level detail, follow the links to the version contract.

## Symptom index

| Symptom | Likely cause | Section |
|---|---|---|
| Bill is off by a power of 1000 | `unitOfMeasure.multiplier` read as a unit factor, or the kWh/Wh conversion is wrong | [Metering](#metering-and-units) |
| Bill is N× too high | summed `Energy.Active.Import.Register` instead of differencing it | [Metering](#metering-and-units) |
| Bill is far too low | differenced `...Interval` instead of summing it | [Metering](#metering-and-units) |
| Bill is exactly 3× | summed L1+L2+L3 when the charger already sends an all-phase total | [Metering](#metering-and-units) |
| Bill is ~2× | added `Inlet` and `Outlet` | [Metering](#metering-and-units) |
| Session billed twice | replayed `Ended`/`StopTransaction`; no dedupe | [Lifecycle](#transaction-lifecycle) |
| Wrong session stopped | recycled `transactionId`; queued stop | [Identity](#identity-and-correlation) |
| Stop returns 504 and retries stop another session | non-idempotent auto-retry after timeout | [Identity](#identity-and-correlation) |
| Tariff endpoint returns 501 on a working charger | 2.0.1 station + 2.1-only action; no capability gate | [Version confusion](#version-confusion) |
| Tariff endpoint returns 202 but nothing happens | `SEND` (type 6) not handled by the CSMS | [Envelope](#envelope-and-schema) |
| `SetVariables` "succeeded" but one variable did not change | treated per-item results as all-or-nothing | [Configuration](#configuration-and-capabilities) |
| `GetVariables` returns `UnknownComponent` for a component that exists | wildcarded `instance`; `""` means default, not all | [Configuration](#configuration-and-capabilities) |
| `NotifySettlement` never arrives | only ad-hoc payments send it; or `SettlementByCSMS = true` | [Settlement](#tariff-payment-and-settlement-21) |
| VAT reverse charge not applied | did not echo `vatNumber`/`evseId` in `VatNumberValidationResponse` | [Settlement](#tariff-payment-and-settlement-21) |
| `SetDefaultTariff` rejected with `DuplicateTariffId` | re-sent the same id; mint a new id per content | [Tariff](#tariff-payment-and-settlement-21) |
| Free sessions on a 2.1 charger | `prices[]` has no unconditional fallback, or `taxRates` absent assumed 0 % tax | [Tariff](#tariff-payment-and-settlement-21) |
| Invoice differs from quote by a cent or two | `minCost`/`maxCost` clamp ignored | [Tariff](#tariff-payment-and-settlement-21) |
| Authorization succeeds at `Authorize` but session is rejected later | charger cache; `StartTransaction.conf.idTagInfo` / `idTokenInfo` is the later gate | [Authorization](#authorization) |
| Session stays open forever | `SuspendedEV`/`Idle`/`evseSleep` treated as stop; or `Ended` not handled | [Lifecycle](#transaction-lifecycle) |
| Session closed while still charging | last `chargingState` used instead of `Ended` | [Lifecycle](#transaction-lifecycle) |
| Missing meter samples after reconnect | `offline: true` ignored; no `GetTransactionStatus` reconciliation | [Completeness](#completeness-and-ordering) |
| Billing window lands in the wrong tariff period | used `received_at`/arrival order instead of charger `timestamp` | [Completeness](#completeness-and-ordering) |
| 502 from the CSMS | extra keys or wrong types in the OCPP payload; your bug | [Envelope](#envelope-and-schema) |
| 423 from the CSMS | `SecurityError` — station not registered / unauthorised | [Security](#security) |
| 504 on every call | one in-flight CALL per connection; you are flooding the CSMS | [Performance](#performance) |

## Version confusion

The most expensive class of bug: applying one version's concepts to another.

- 1.6 has **no** `TransactionEvent`, `IdToken`, `SetVariables`, `IdTokenInfo`, `TotalCost`,
  `TariffType`, `CostUpdated`, `tariffId`, `seqNo`. If you see those names in a 1.6 codebase, it is
  wrong.
- 2.0.1 has **no** `SetDefaultTariff`, `GetTariffs`, `ClearTariffs`, `ChangeTransactionTariff`,
  `costDetails`, `transactionLimit`, `NotifySettlement`, `NotifyWebPaymentStarted`,
  `VatNumberValidation`, message types 5/6. A 2.0.1 station answers `NotImplemented` to all of them
  **without dropping the session** — your feature fails silently.
- 2.1 has **no** `StartTransaction`/`StopTransaction` (those are 1.6-era), and `connectorId`-only
  addressing. Use `evseId` + `connectorId`.
- Error spelling is version-specific: 1.6/2.0.1 use `OccurenceConstraintViolation` (one `r`) and
  1.6 uses `FormationViolation`; 2.1 uses `OccurrenceConstraintViolation` and `FormatViolation`.
  Do not "fix" the typos on the wire.
- The version is the **negotiated subprotocol**, not the charger model, not the firmware version,
  not the CSMS's marketing name.

## Envelope and schema

- `null`, `{}` and `[]` are invalid for an absent optional field. **Omit the key.** Every `0..*`
  field has `minItems: 1` when present.
- Every payload schema is `additionalProperties: false`. Extra keys cause
  `FormatViolation`/`PropertyConstraintViolation` → **502**; that means your integration is buggy,
  not that the station misbehaved.
- Use `customData` (typed) or `DataTransfer` (untyped, vendor-specific) for vendor fields. Never
  invent top-level keys.
- `customData` is constrained: `TechnicalData.namespace` must be a vendor prefix; treat
  `additionalData` as untrusted input.
- The `Action` is the message name **without** the `Request`/`Response` suffix.
- 2.1 renames `uniqueId` to `MessageId` and adds `CALLRESULTERROR` (5) and `SEND` (6).
- `CALLRESULTERROR.MessageId` must equal the `CALLRESULT` it rejects. A `SEND` is **never answered**
  — no delivery guarantee, no confirmation. Never build billing-critical flows on it.
- A missing handler for an inbound action yields `NotImplemented` and can stall the station. Register
  a handler for every action you forward.
- The 30 s CALL timeout is a design constraint: return **202** for anything that is not an immediate
  reply, and never hold an HTTP request open waiting for a follow-up OCPP message.

## Identity and correlation

- **1.6:** the **CSMS** allocates `transactionId` (integer). Persist it from
  `StartTransaction.conf`. Never reuse an id after close. On a new `StartTransaction` with an
  already-open id, close the previous session as `ORPHANED` and alert.
- **2.x:** the **charger** allocates `transactionId` (string ≤ 36). Never mint one. Bind it on
  `Started` via `remoteStartId`.
- `RequestStartTransactionResponse.transactionId` is present **only** if the station had already
  started the transaction before your request. Do not treat its absence as failure.
- Correlate 2.x settlement on **`(pspRef, transactionId)`**. `pspRef` alone is reusable.
- `MessageId`/`uniqueId` must never repeat for a station, including across reconnects. Persist the
  mapping **before** sending.
- Outbound timeout is ambiguous. Never auto-retry a non-idempotent operation. Persist
  `Idempotency-Key → (message id, state)` first.
- A `Started` with no matching `remoteStartId` is plug-and-charge or a retry — **adopt** it. Do not
  orphan it.
- Two `Started` events for one `remoteStartId` are a duplicate — create one session.
- A 1.6 `StopTransaction` without its `StartTransaction` is an orphan; close it as `estimated`,
  not as a new session.
- 1.6 `MeterValues.transactionId` is optional. Attribute by `(station, connectorId, timestamp)`,
  never by arrival order.
- `StatusNotification(connectorId = 0)` / `evseId = 0` reports the **main controller**, not a
  connector and not an aggregate. Never derive "is this station free?" from it.

## Transaction lifecycle

- Only `Ended` ends a 2.x session. `Idle`, `SuspendedEV`, `SuspendedEVSE` and `evseSleep` still
  count as open and billable (and may accrue idle time).
- An `Ended` whose last `chargingState` was `Charging` is normal. **`Ended` wins.**
- An `Ended` with no `meterValue` is legal. Bill from the last `Updated` sample and mark
  `estimated: true`.
- An `Ended` with no `costDetails` in 2.1 is legal. Fall back to central accounting.
- `costDetails.chargingPeriods` omitted means it was a **running-cost** update, not a final cost.
- `idToken` is absent on `Ended` when the session was ended by `RequestStopTransaction` or `Reset`.
  Persist the first one you see; never require it on `Ended`.
- `stoppedReason`/`reason` may be omitted → default `Local`, never `Unknown`.
- `Reset(ImmediateAndResume)` may **not** end the session. Reconcile with `GetTransactionStatus`.
- A session open for more than ~72 h is almost always `TxCtrlr.TxStartPoint`/`TxStopPoint`
  misconfiguration. Alarm; do not silently bill infinity.
- `RequestStopTransaction` may yield only another `Updated`, not `Ended`. Keep the stop state
  machine open and reconcile.

## Completeness and ordering

- 2.x `seqNo` is **per EVSE**, not per transaction. Scope the gap check to the EVSE.
- Completeness proof: `Started` at `a`, `Ended` at `o`, every `n` in `[a, o]` present.
- A gap or `offline: true` → `GetTransactionStatus`:
  `messagesInQueue: true` ⇒ defer billing; `false` ⇒ close as `estimated`, record gaps, alert.
- Store `seq_start`, `seq_end`, `missing_seq_count` at close time. They cannot be reconstructed.
- Chargers buffer offline messages and replay them **chronologically**. Retries duplicate.
  Dedupe: 1.6 `(station, action, transactionId, timestamp)`; 2.x
  `(stationId, transactionId, seqNo)`.
- Order by the charger `timestamp`, never by arrival. Store both `timestamp` and `received_at`.
- Clock skew: quarantine `|skew| > 300 s`; use `received_at` for TTL/ordering, charger time for
  billing windows.
- Expect `StopTransaction` after a burst of `MeterValues` on reconnect. Do not close the session on
  the first meter sample gap.
- `StatusNotification` may arrive before `StartTransaction`/`Started`; it is not session evidence.

## Metering and units

- `.Register` is cumulative — **difference** it. `.Interval` is a delta — **sum** it. Never mix.
- `SampledValue.value` is a **string**. Parse as decimal; never float.
- 1.6 `unit` defaults to `Wh`; convert `kWh` × 1000.
- 2.x `multiplier` is a **base-10 exponent**, not a unit factor:
  `wh = value × 10^multiplier`, then `× 1000` if unit is `kWh`.
  A value of `4.9` with `unit: "kWh", multiplier: 0` is **4900 Wh**, not 4.9 Wh.
- Never sum `Inlet` + `Outlet`. Bill `Outlet`.
- 2.1 `location = "Upstream"` is not transaction energy — filter it out.
- Never sum L1+L2+L3 when `SampledDataCtrlr.RegisterValuesWithoutPhases == true`.
- `SignedData` is not billable. Route to review.
- `Energy.Active.Import.CableLoss`, `LocalGeneration.Register`, `Energy.Active.Setpoint.Interval`,
  `EnergyRequest.*`, `Power.Active.Setpoint`, `Power.Active.Residual` are not billed import.
- A falling register (`meterStop < meterStart`) is a meter reset or swap, **not** wraparound.
  Quarantine; never re-base.
- Never mix `connectorId 0` (main meter) with connector N.
- `MeterValues` in 2.0.1/2.1 is **not transaction-linked**. Never bill from it.

## Authorization

- `StartTransaction.conf.idTagInfo` is the **last** 1.6 gate and may contradict an earlier
  `Authorize` because of the charger's cache. The later verdict wins; be able to reverse a payment.
- `TransactionEventResponse.idTokenInfo` is the 2.x equivalent, required when the request carried an
  `idToken`.
- `expiryDate` absent means **no expiry**, not "expired".
- `parentIdTag`/`parentIdToken` groups by exact match. Absent never groups.
- `ConcurrentTx` means already charging elsewhere → **409**, offer the existing session.
- `NoCredit` is 2.0.1+ and is your prepaid hook.
- `ClearCache` forces revalidation when you revoke a token and need it now.
- Never trust `idTag`/`idToken` type blindly; check `idToken.type` (`Central`, `eMAID`,
  `ISO14443`, `ISO15693`, `KeyCode`, `Local`, `MacAddress`, `NoAuthorization`, `DirectPayment`).
- `DirectPayment` means the `idToken` value is a `pspRef`, not a driver identity.

## Configuration and capabilities

- There is **no** `SupportedFeatureProfiles` in 2.x. Probe the device model with `GetBaseReport` +
  targeted `GetVariables`; cache per station.
- `SetVariables`/`GetVariables` return **one status per element**. Partial success is normal. Return
  200 with a per-item array; only aggregate-400 when every item is `UnknownComponent`/
  `UnknownVariable`.
- `UnknownComponent`/`UnknownVariable` = absent (501 + hide). `Rejected` = exists but unreadable
  (403). `NotSupported` = write/read-only violation (403).
- Never wildcard `instance`. `""` means the default instance, not "all".
- `SecurityCtrlr.BasicAuthPassword` is WriteOnly. Never serialize it; map a read rejection to 403.
- 1.6 config names do not exist in 2.x: `TxEnabled` → `SampledDataCtrlr.Enabled`;
  `MeterValueSampleInterval` → `SampledDataCtrlr.TxUpdatedInterval`;
  `MeterValuesSampledData` → `SampledDataCtrlr.TxUpdatedMeasurands`;
  `ClockAlignedDataInterval` → `SampledDataCtrlr.ClockAlignedDataInterval`;
  `SignedMeterValue` → `SampledDataCtrlr.SignReadings`;
  `StopTxnOnEVSideDisconnect` → `TxCtrlr.TxStopPoint` / `EVCtrlr.EVSEIsPresent`;
  `ConnectorPhaseRotation` → `EvseCtrlr.PhaseRotation`.
- Invalidate capability flags on every `BootNotification` and after firmware reaches `Installed`.
  A firmware update can add or remove capabilities.
- `NotSupported`/`NotImplemented` degrade **permanently** for that station. Never blind-retry.
- 1.6 `SendLocalList` `Full` + empty list **wipes** the list. 2.x same with `versionNumber`.
- 1.6 `GetConfiguration` with no `key` returns everything; an unknown key is `unknownKey`, not an
  error.
- 1.6 `ChangeConfiguration` may return `RebootRequired`; the write took effect, tell the caller.
- `Reset` drops the socket. Your session state must survive reconnect, and a queued stop must not
  hit a recycled id.
- `TriggerMessage(BootNotification)` is not allowed in 1.6; do not expose it.

## Tariff, payment and settlement (2.1)

- `tariffId` is immutable per content. Re-sending the same id ⇒ `DuplicateTariffId` (409). New
  content ⇒ new id. "Refresh" is not a thing.
- Always append an unconditional fallback entry **last** in every `prices[]`. Without it, unmatched
  sessions cost nothing silently. Putting it first shadows every conditional entry.
- `taxRates` absent means **no tax**, not 0 %. `tax` is a **percentage** (`21.0`), not a fraction.
  `inclTax` requires `exclTax`.
- `validFrom` in `AuthorizeResponse.tariff` violates I08.FR.09.
- Do not `ClearTariffs` an id used by a live session — return 409.
- `ClearTariffs` is **per-tariff**; `NoTariff` means not found, and `tariffId` is then absent.
- `ChangeTransactionTariff` uses `TxNotFound` for "does not exist or already ended" (404).
- `minCost`/`maxCost` clamp the cost and change `typeOfCost`. Honour it.
- Currency cannot change mid-session (`NoCurrencyChange`).
- `NotifySettlement` is optional, ad-hoc only, and never when `PaymentCtrlr.SettlementByCSMS = true`.
- Correlate on `(pspRef, transactionId)`; the last settlement for a `pspRef` wins.
- `Canceled` (single L) means no billable part — void, do not invoice.
- `settlementAmount` on `Failed` is the **attempted** amount, not collected.
- `VatNumberValidation` has only `Accepted`/`Rejected`; read `statusInfo.reasonCode`, and echo
  `vatNumber`.
- `RequestBatterySwap` has no `NoBatteryAvailable` enum; it is `Rejected` + reasonCode.
- `transactionLimit.maxEnergy` is **Wh**, `maxCost` is in the tariff currency, `maxTime` seconds,
  `maxSoC` 0-100. Round maxCost up and add a buffer.
- A Local Authorization List is incompatible with local cost calculation unless the default tariff
  applies to everyone.
- Never bill a `TariffNotAccepted` session; it has no `tariffId` and no cost. Refund.
- `costDetails` must be verified, not trusted. Check `failureToCalculate`, `chargingPeriods`,
  `tariffId` drift and recompute.
- `OpenPeriodicEventStream`/`ClosePeriodicEventStream` require a CSMS that can receive
  `MessageTypeId 6`. Otherwise the stream silently delivers nothing.
- `ClosePeriodicEventStream` is station-initiated; no handler ⇒ `NotImplemented` and the station may
  error.

## Direction traps

Trust the spec table, not the message name.

| Message | Actual direction |
|---|---|
| `NotifyAllowedEnergyTransfer` | **CSMS → station** |
| `NotifyWebPaymentStarted` | **CSMS → station** (some stations also send it inbound — tolerate both) |
| `NotifySettlement` · `NotifyPriorityCharging` · `NotifyCustomerInformation` · `BatterySwap` · `NotifyDERAlarm` · `NotifyDERStartStop` · `ReportDERControl` · `ClosePeriodicEventStream` · `AFRRSignal` | **station → CSMS** |
| `PullDynamicScheduleUpdate` | **station → CSMS** — the station asks *you* |
| `VatNumberValidation` | **CSMS → station** — you ask, it answers |
| `Get15118EVCertificate` | **station → CSMS** — do not implement as outbound |

`VatNumberValidation` is the one teams expose as a public REST endpoint. It is a **CSMS → station**
operation: model it as a callback your CSMS invokes, not something a driver app calls.

## Security

- Never expose lowering `SecurityCtrlr.SecurityProfile` through a public API. Profile 1 is
  plaintext Basic auth.
- `SecurityCtrlr.BasicAuthPassword` is WriteOnly — never serialize it; `Rejected` on read → 403.
- `SecurityEventNotification` is CSMS business; ask for a daily digest rather than a raw stream.
- Treat `DataTransfer.data` and `customData` as untrusted, untyped and versionless: cap size,
  validate, and never let them mutate your rate table.
- Never send raw card data in `idToken.additionalInfo`; only `CardBin`, `CardLast4Digits`,
  `CardBrand`.
- Authenticate CSMS → API webhooks separately from public API auth.

## Performance

- Most CSMS implementations allow **one in-flight CALL per connection**, not per station. A flood of
  concurrent REST calls serialises into timeouts — rate-limit per station in your API.
- The spec suggests a **30 s** CALL timeout. Design every endpoint around it: 202 for anything not
  an immediate reply.
- `seqNo` gaps from buffering are normal at reconnect. Reconcile with `GetTransactionStatus` rather
  than assuming loss.
- Cache `StatusNotification` and the device model. Do not call `GetVariables` on every read.

## Library and CSMS defects seen in the wild

Treat these as things to verify in *your* stack, not as protocol facts:

- `mobilityhouse/ocpp` v21 cannot receive `MessageTypeId 5` or `6` at all — periodic event streams
  and `CALLRESULTERROR` are unsupported. Verify before exposing either.
- `NotifySettlementResponse.receiptUrl` has a field-name mismatch in that library (`receiptURL` vs
  the schema's `receiptUrl`), so returning a `receiptUrl` can make the station see a CALLERROR.
  Return only `receiptId`, or bypass schema validation.
- `BatteryDataType.soc`, `Get15118EVCertificate.prioritized_emaids` and DER `fixed_pf_*` fields can
  fail schema validation.
- `Decimal` is truncated to one decimal place on the wire by that library's encoder — never use it
  for money or `totalCost`.

These are library-specific, not protocol defects. Check your own implementation rather than copying
a workaround blindly.

## Debugging playbook

1. **Identify the subprotocol** from the negotiated connection. Confirm the charger record.
2. **Reproduce with the raw OCPP message**, not only the REST call. Ask the CSMS for the
   `uniqueId`/`MessageId`, the action, the payload and the reply.
3. **Check the version's identity model** first: who owns `transactionId`, and where is it bound?
4. **Check dedupe** before assuming a new event. Replays are normal.
5. **Check completeness** before touching money: `seqNo` gaps, `offline`, `messagesInQueue`.
6. **Check units and register semantics** before touching money again.
7. **Check capability flags** before assuming the charger ignored you.
8. **Check direction** before adding an endpoint. A "notify" may be outbound.
9. If the answer is still unclear, reduce to a single charger, a single session and one message —
   multi-charger correlation bugs hide in aggregate views.
