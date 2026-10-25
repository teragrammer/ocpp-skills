# Billing, rating and invoicing

Money rules differ by version only in **where energy and cost come from**. The rest of the discipline
— one connector, one location, one unit, snapshot the rate, prove completeness, never mutate a
finalised invoice — is shared.

## Contents

- [Where the money comes from](#where-the-money-comes-from)
- [The authoritative energy formulas](#the-authoritative-energy-formulas)
- [Unit normalisation](#unit-normalisation)
- [Measurands](#measurands)
- [The five billing rules](#the-five-billing-rules)
- [Prove completeness before invoicing (2.x)](#prove-completeness-before-invoicing-2x)
- [Rating engine shape](#rating-engine-shape)
- [Session state machine](#session-state-machine)
- [Enforcing limits](#enforcing-limits)
- [Authorization gating](#authorization-gating-before-you-accept-money)
- [Invoice shape](#invoice-shape)
- [2.1 cost reconciliation](#21-cost-reconciliation)
- [Daily reconciliation](#daily-reconciliation)
- [Refunds and adjustments](#refunds-and-adjustments)

## Where the money comes from

| Version | Authoritative energy | Authoritative cost | What is display-only |
|---|---|---|---|
| 1.6 | `meterStop − meterStart` (Wh) | your rate table | `MeterValues` |
| 2.0.1 | register at `Transaction.Begin` − register at `Transaction.End` | your rate table | `MeterValues`, `CostUpdated` |
| 2.1 | same as 2.0.1 | `costDetails.totalCost` **after verification**, else your rate table | `CostUpdated`, running `costDetails` |

**Compute a central cost for every 2.1 session anyway.** Stores the number you can defend if the
station's tariff copy drifts or `failureToCalculate = true`. Never store only one of the two.

## The authoritative energy formulas

**1.6**

```
session_wh  = StopTransaction.meterStop − StartTransaction.meterStart   # both Wh
session_kWh = session_wh / 1000
```

Both values are from the **same connector** and are the only numbers you bill on. `MeterValues` is
for display, previews and cross-checks.

**2.0.1 / 2.1**

```
start_wh  = Energy.Active.Import.Register, context == "Transaction.Begin"   (on Started)
end_wh    = Energy.Active.Import.Register, context == "Transaction.End"     (on Ended)
energy_wh = end_wh − start_wh
kWh       = energy_wh / 1000
```

Fallback when the begin/end register contexts are missing:

```
energy_wh = last Register before Ended − first Register after Started
```

Mark the session `estimated: true` whenever you use the fallback.

## Unit normalisation

**1.6**

| Source | Unit | Convert |
|---|---|---|
| `StartTransaction.meterStart` | **always Wh** | as-is |
| `StopTransaction.meterStop` | **always Wh** | as-is |
| `MeterValues` `SampledValue` | `Wh` default, `kWh` if stated | `× 1000` when `unit == "kWh"` |

**2.x**

```
wh = value × 10 ^ unitOfMeasure.multiplier      # multiplier is an EXPONENT to base 10
if unitOfMeasure.unit == "kWh": wh ×= 1000
```

`multiplier` defaults to `0`. It is **not** a unit conversion factor.

| Reported | Correct reading | Naive (wrong) reading |
|---|---|---|
| `4900`, unit `Wh`, multiplier `0` | 4900 Wh = 4.9 kWh | 4900 kWh |
| `4.9`, unit `kWh`, multiplier `0` | 4.9 kWh = **4900 Wh** | 4.9 Wh (1000× low) |
| `4.9`, unit `Wh`, multiplier `-3` | 4.9 mWh = 0.0049 Wh | 4.9 Wh |
| `4900`, unit `Wh`, multiplier `3` | 4 900 000 Wh = 4900 kWh | 4900 Wh |

`SampledValue.value` is a **string**. Parse as a decimal — never a float. Floating point on meter
values is a rounding bug waiting to happen.

## Measurands

| Measurand | Meaning | Billing use |
|---|---|---|
| `Energy.Active.Import.Register` | absolute register of energy **into the EV** | **difference** it; this is the money field |
| `Energy.Active.Import.Interval` | energy imported **during one interval** | **sum** it; secondary |
| `Energy.Active.Export.Register` / `.Interval` | V2G export | ignore unless you bill export |
| `Energy.Reactive.Import.Register` / `.Interval` | VARh | ignore for kWh billing |
| `Energy.Active.Import.CableLoss` | cable loss (2.1) | ignore; not delivered energy |
| `Energy.Active.Import.LocalGeneration.Register` | local generation (2.1) | exclude from billed import |
| `Energy.Active.Setpoint.Interval` | setpoint reporting (2.1) | not a measurement |
| `EnergyRequest.*` | request-side signalling (2.1) | not a measurement |
| `Power.Active.Import` / `Power.Offered` | W | live kW display |
| `Current.Import` / `Current.Offered` / `Current.Export` | A | limits and phase checks |
| `SoC` | EV state of charge | display, prepaid caps |
| `Voltage` / `Frequency` | grid | diagnostics |
| `Temperature` | device | diagnostics, derating |

`.Register` is cumulative — **difference** it. `.Interval` is a per-interval delta — **sum** it.
Mixing them up inflates or deflates a bill by orders of magnitude.

### Location

| Version | Values | Bill |
|---|---|---|
| 1.6 | `Inlet`, `Outlet` | `Outlet` (EV side) |
| 2.0.1 | `Body`, `Cable`, `EV`, `Inlet`, `Outlet` | `Outlet` |
| 2.1 | same + `Upstream` | `Outlet`; **filter `Upstream` out** |

Never add `Inlet` and `Outlet` together. Never add `Body`/`Cable`/`EV` sub-meters to `Outlet`. If
both inlet and outlet arrive, pick one, record which, and stay consistent for the session.

### Phases

If `SampledDataCtrlr.RegisterValuesWithoutPhases == true`, the charger sends only the all-phase
total. Do **not** sum L1+L2+L3. Probe this per station during capability discovery and store the flag.

## The five billing rules

1. **One connector.** Never mix `connectorId 0` (main/aggregate meter) with connector N, and never
   sum across connectors into one session.
2. **One location.** Never add `Inlet` and `Outlet` values together. Bill the EV side.
3. **One unit.** Normalise everything to Wh before any arithmetic.
4. **Signed data is not billable.** `format = "SignedData"` → route to manual review. The signature
   is an MDM/legal feature; 1.6 has no verification flow for it.
5. **Never re-base a falling register.** `meterStop < meterStart` or a register that decreases is a
   meter reset or a swapped meter, **not** wraparound. Quarantine the session for review.

## Prove completeness before invoicing (2.x)

`seqNo` is monotonic **per EVSE**. It is the only way to prove you received every message.

```
Started at seqNo = a
Ended   at seqNo = o
every n in [a, o] present  →  COMPLETE, bill normally

gap detected  or  offline == true
  → GetTransactionStatus(transactionId)
       messagesInQueue == true   → DEFER. Poll again. Do not invoice.
       messagesInQueue == false  → close as estimated: true, record gap count, alert ops
```

Store `seq_start`, `seq_end` and `missing_seq_count` on every session. Without them you cannot
answer "was this session complete?" after the fact.

**1.6 has no `seqNo`.** Use dedupe plus orphan detection instead: a `StopTransaction` without its
`StartTransaction`, a session open across a reconnect, or a `StatusNotification` that goes
`Available` while you still have an open session. Close as `estimated` and alert.

## Rating engine shape

Keep the rate table **versioned and separate** from the session, then snapshot it onto the session
at start. A tariff edited mid-session must never retro-price a closed session.

A rate entry needs, at minimum:

| Field | Purpose |
|---|---|
| `rate_id` / `version` | which table produced this price |
| `price_per_kWh`, `price_per_min`, `price_per_idle_min`, `start_fee`, `currency` | the numbers |
| `tax_rate`, `tax_included` | VAT handling — decide once, store the decision |
| `valid_from`, `valid_to` | time windows |
| `conditions` | user group, connector type, AC/DC, time of day, day of week |
| `minimum_charge`, `rounding` | floor and rounding rule |

Store on every session row: `rate_id`, `price_per_kWh` (the resolved value, not a pointer),
`currency`, `tax_rate`, `rate_snapshot`. Then a closed invoice is reproducible even if the rate
table is deleted.

Evaluate time-of-day and day-of-week conditions in the **station's local timezone**, not the
server's. Store the timezone name (IANA) with the session.

### The total

```
gross = energy_kWh × price_per_kWh
      + charging_time_s / 60 × price_per_min
      + idle_time_min × price_per_idle_min
      + start_fee
tax   = gross × tax_rate
total = gross + tax
```

`timeSpentCharging` (seconds, in `transactionInfo`) is your charging-time source for AC sessions
with pauses. `Ended.timestamp − Started.timestamp` is the wall-clock duration — the difference is
your idle time.

**2.1 min/max:** if `costDetails.totalCost.typeOfCost` is `MinCost` or `MaxCost`, the tariff clamped
the result. Honour the clamped value — otherwise the invoice will not match the quote. Apply the
same floor/ceiling in your central recomputation.

## Session state machine

```
CREATED           POST /sessions accepted, CSMS issued the start operation
PENDING_START     waiting for the charger (2.x: remoteStartId outstanding)
AUTHORIZED        1.6 only: StartTransaction.conf.idTagInfo Accepted
ACTIVE            session bound; start register captured; rate snapshot taken
                  Updated / MeterValues accumulate; running cost may be pushed
STOP_REQUESTED    stop accepted (2.x may yield only another Updated)
ENDED             final meter captured; completeness proof; cost frozen
INVOICED          invoice issued

ALTERNATES
  REJECTED         auth status != Accepted → reverse/refund the payment, no billable session
  NO_TARIFF        2.1: TariffNotAccepted → no tariffId, no cost → refund, do not bill
  CANCELLED_PRE_TX 2.1: NotifySettlement(Canceled) with no transactionId → void, do not invoice
  FAILED_SETTLEMENT 2.1: NotifySettlement(Rejected|Failed) → retry capture off-protocol
  ORPHANED         socket/reset lost the session; close from the last sample, estimated: true
  UNKNOWN_END      stop requested but no Ended → reconcile, then close as estimated
  ABANDONED        no Ended after reconciliation → escalate to a claim, never auto-close
```

`ORPHANED`, `UNKNOWN_END` and `ABANDONED` must be reachable by design — power cuts and resets are
routine, not exceptions. Alert on them; never auto-invoice an `estimated` session without a flag the
finance team can filter on.

## Enforcing limits

### 1.6

| Mechanism | How |
|---|---|
| Energy ceiling | `SetChargingProfile` → `TxProfile`, `chargingSchedulePeriod.limit` in **A** |
| Power ceiling | same, `chargingRateUnit: "W"` |
| Stop at target | watch `MeterValues`, issue `RemoteStopTransaction` |
| Start deadline | watch `transactionData`/timestamps, or `GetCompositeSchedule` |

A current limit in amps is the most reliable 1.6 mechanism. Convert a kW target with
`I = P × 1000 / (U × √3)` for three-phase (`U` = nominal phase-to-neutral voltage).

Install the `TxProfile` in the same command as the start when you need a limit from second zero.

### 2.0.1

| Mechanism | How |
|---|---|
| Amp ceiling | `SetChargingProfile` `TxProfile`, `chargingSchedulePeriod.limit` in A |
| Power ceiling | same, `chargingRateUnit: "W"` |
| Stop at target cost | watch `TransactionEvent(Updated).meterValue`, issue `RequestStopTransaction` |
| Local credit check | `IdTokenInfo.status = "NoCredit"` when the wallet is empty |

`triggerReason: EnergyLimitReached` / `TimeLimitReached` tell you a limit fired — do not treat them
as errors.

### 2.1

Use `TransactionEventResponse.transactionLimit` on `Started`:

```
maxCost    : decimal?    in the tariff currency
maxEnergy  : decimal?    Wh
maxTime    : integer?    seconds
maxSoC     : integer?    0..100
```

The station enforces it and reports `CostLimitReached` / `EnergyLimitReached` / `TimeLimitReached` /
`SoCLimitReached`. This is the real prepaid mechanism. Round `maxCost` **up** and add a small buffer
so a driver is not cut off a few cents short of their authorisation.

## Authorization gating before you accept money

```
POST /sessions
  → 1. your auth: who is the caller, do they have a valid entitlement
  → 2. payment: authorised, or covered by a subscription/contract
  → 3. OCPP Authorize(idTag/idToken) — via the CSMS; read the result
  → 4. start the transaction
  → 5. the final auth verdict: 1.6 StartTransaction.conf.idTagInfo;
       2.x TransactionEventResponse.idTokenInfo on Started
  → 6. if step 5 != Accepted: reverse/refund the payment, do not create a billable session
```

Step 6 is the one teams forget. A charger's authorization cache means step 3 and step 5 can
disagree, and the **later** one wins. `ClearCache` forces revalidation when you revoke a token and
need it to take effect now.

`IdTagInfo`/`IdTokenInfo` mapping:

| Status | Meaning | API behaviour |
|---|---|---|
| `Accepted` | may charge | allow |
| `Blocked` | explicitly denied | **403** |
| `Expired` | token past `expiryDate` | **401** — re-auth |
| `Invalid` | unknown token | **401** |
| `ConcurrentTx` | already charging elsewhere | **409** — offer the existing session |
| `NoCredit` | 2.0.1+ prepaid wallet empty | **402** or 409 with a top-up link |

`expiryDate` absent means **no expiry**, not "expired". `parentIdTag`/`parentIdToken` groups tokens
by exact match; absent never groups.

## Invoice shape

Every invoice row should carry enough to re-derive the number without the charger:

```
session_id, station_id, ocpp_version, evse_id, connector_id
started_at, ended_at               # charger timestamps AND your received_at
meter_start_wh, meter_stop_wh, energy_kWh
rate_id, rate_snapshot, price_per_kWh, currency, tax_rate, tax_amount
charging_time_s, idle_time_min
seq_start, seq_end, missing_seq_count        # null for 1.6
cost_source                        # "meter" | "estimated" | "charger" | "central" | "partial"
cost_total, cost_currency
tariff_id, tariff_content_hash     # null when central
charger_reported_cost, computed_cost, variance
tax_source
reconciliation_flags               # ["tariff_drift", "cost_mismatch", ...]
psp_ref, settlement_status, settlement_amount, settlement_time
receipt_id, receipt_url, vat_number
```

`cost_source`, `sequence_complete` and `reconciliation_flags` are what let finance separate exact
from approximated revenue and prove completeness later. Write them at close time — they cannot be
reconstructed.

## 2.1 cost reconciliation

Run this on every `Ended`, in order:

```
1. costDetails present and failureToCalculate != true ?
      no  → cost_source = "central", bill from your own meter accumulator
      yes → continue
2. chargingPeriods[] non-empty ?
      no  → cost_source = "central"   (it was a running-cost update, not a final cost)
      yes → continue
3. every chargingPeriod.tariffId known in your tariff store and byte-identical to what you sent ?
      no  → cost_source = "central", flag "tariff_drift"
      yes → continue
4. the only tariffIds used == transactionInfo.tariffId, or the change was explicit
   (a TariffChanged triggerReason followed your ChangeTransactionTariff) ?
      no  → cost_source = "central", flag "unexpected_tariff_change"
      yes → continue
5. recompute from chargingPeriods + your stored tariff copy
      |recomputed − totalCost| <= tolerance ?
      no  → cost_source = "central", flag "cost_mismatch", alert ops
      yes → cost_source = "charger"
6. cross-check energy: your kWh from meterValue[] vs the sum implied by chargingPeriods
      divergence > tolerance ? → flag "energy_divergence" (do not block, but record it)
```

Use a **relative** tolerance (e.g. 1 % + 1 cent) — the station may round per charging period.

Steps 3-5 are the highest-value control in a 2.1 billing system. They catch a stale tariff, a
station-side rounding bug and a misconfigured VAT rate before they reach a customer.

## Daily reconciliation

```
1. Every Ended session has exactly one terminal state.
   Any session open > 72 h → alarm (usually TxCtrlr misconfiguration).
2. cost_source counts: charger vs central vs flagged.
   A sudden shift to "central" means stations stopped honouring tariffs — investigate.
3. For every NotifySettlement: match (pspRef, transactionId) to a session.
   Unmatched → ad-hoc correlation is broken; alert.
4. Sum settlementAmount per pspRef == your PSP ledger total for that pspRef.
   Mismatch → financial reconciliation break; block auto-collection.
5. Every Settled session has an invoice; every Failed/Rejected has a retry record.
6. Recompute a random sample of cost_source == "charger" sessions from your tariff store.
   Divergence → your tariff replication or your recomputation is wrong.
```

Step 4 is the one that catches real money. `NotifySettlement` is optional, so your own PSP ledger
must be authoritative in `SettlementByCSMS = true` mode.

## Refunds and adjustments

- **Early stop:** prorate from `meterStop − meterStart` (1.6) or `end_wh − start_wh` (2.x). Refund
  the difference against the authorisation; never refund the authorisation amount itself.
- **Failed session** (`Rejected`, `PowerLoss` before any energy): refund in full, emit a zero-value
  or non-invoice row so reconciliation still balances.
- **`TariffNotAccepted`:** refund in full, write a zero-value row, do not invoice.
- **`SettlementStatus = Canceled`:** void, do not invoice.
- **`Rejected` / `Failed` settlement:** retry the capture off-protocol; never re-send
  `NotifySettlement` — it is an inbound report, not a request.
- **Orphaned/estimated:** charge only for metered energy, mark `estimated`, hold from
  auto-collection until reviewed.
- **Correction after invoice:** issue a credit note against the original `invoice_id`. Never edit a
  finalised invoice row.
