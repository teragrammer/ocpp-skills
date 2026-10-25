# 2.1 tariffs, cost details and settlement

This file applies to `ocpp2.1` only. 1.6 and 2.0.1 have **no tariff, cost or settlement message** —
use `billing.md` and your own rate engine.

Read this before writing any pricing or payment code. The tariff model is where 2.1 integrations
lose money silently.

## Contents

- [`TariffType`](#tarifftype)
- [Component types](#component-types)
- [Conditions](#conditions)
- [Tax](#tax)
- [Selection semantics](#selection-semantics--the-rules-that-break-billing)
- [Worked example](#worked-example--flat-energy-tariff-with-vat)
- [`costDetails`](#costdetails)
- [Tariff storage](#tariff-storage)
- [Settlement](#settlement)
- [`NotifyWebPaymentStarted`](#notifywebpaymentstarted-csms--station)
- [`VatNumberValidation`](#vatnumbervalidation-csms--station)
- [`transactionLimit`](#transactionlimit--the-prepaid-mechanism)
- [Prepaid charging](#prepaid-charging--the-21-way)
- [VAT handling summary](#vat-handling-summary)
- [Tariff and payment landmines](#tariff-and-payment-landmines)

## `TariffType`

| Field | Type | Card | Notes |
|---|---|---|---|
| `tariffId` | `string[0..60]` | 1..1 | **immutable per content** (I08.FR.08) |
| `currency` | `string[0..3]` | 1..1 | ISO 4217. **A plain string — there is no Currency enum** |
| `validFrom` | `dateTime` | 0..1 | when it becomes active; absent ⇒ immediately active |
| `description` | `MessageContentType` | 0..10 | multi-language text for the display |
| `energy` | `TariffEnergyType` | 0..1 | per kWh |
| `chargingTime` | `TariffTimeType` | 0..1 | per minute |
| `idleTime` | `TariffTimeType` | 0..1 | per minute |
| `fixedFee` | `TariffFixedType` | 0..1 | once, at transaction start |
| `minCost` / `maxCost` | `PriceType` | 0..1 | session floor/ceiling; changes `typeOfCost` |
| `reservationTime` | `TariffTimeType` | 0..1 | reservation duration |
| `reservationFixed` | `TariffFixedType` | 0..1 | reservation flat fee |

Used by `SetDefaultTariffRequest`, `ChangeTransactionTariffRequest`, `AuthorizeResponse`.

**There is no `TariffStatus` enum and no `PriceUnitType` enum.** The price unit lives in the field
name:

| Field | Unit |
|---|---|
| `priceKwh` | per kWh |
| `priceMinute` | per minute |
| `priceFixed` | flat |

## Component types

```
TariffEnergyType  = prices*(TariffEnergyPriceType{priceKwh*, conditions?}) , taxRates?(0..5)
TariffTimeType    = prices*(TariffTimePriceType{priceMinute*, conditions?}), taxRates?(0..5)
TariffFixedType   = prices*(TariffFixedPriceType{priceFixed*, conditions?}), taxRates?(0..5)

TariffEnergyPriceType = priceKwh*    + TariffConditionsType?
TariffTimePriceType   = priceMinute* + TariffConditionsType?
TariffFixedPriceType  = priceFixed*  + TariffConditionsFixedType?
```

Evaluation moments:

| Component | Evaluated |
|---|---|
| `energy.prices[]` | per kWh delivered |
| `chargingTime.prices[]` | per minute spent charging |
| `idleTime.prices[]` | per minute idle inside the session |
| `fixedFee.prices[]` | **once**, at transaction start |
| `reservationTime` / `reservationFixed` | once, at reservation time |

A reservation is **not** reported as a `chargingPeriod` — it happened outside the transaction.

## Conditions

`TariffConditionsType` — all fields optional; a condition set is only applied when it is present.

| Condition | Type | Unit / notes |
|---|---|---|
| `startTimeOfDay` / `endTimeOfDay` | `string[0..5]` | **local** `hh:mm`. Wraps past midnight |
| `dayOfWeek` | `DayOfWeekEnumType` | `0..7` — `Sunday`..`Saturday` |
| `validFromDate` / `validToDate` | `date` | **local**, RFC 3339 full-date |
| `evseKind` | `AC` \| `DC` | |
| `minEnergy` / `maxEnergy` | `decimal` | **Wh** — session total |
| `minCurrent` / `maxCurrent` | `decimal` | **A**, **summed over all phases**, instantaneous |
| `minPower` / `maxPower` | `decimal` | W |
| `minTime` / `maxTime` | `integer` | s, **total transaction duration** |
| `minChargingTime` / `maxChargingTime` | `integer` | s, energy actually flowing |
| `minIdleTime` / `maxIdleTime` | `integer` | s |

`TariffConditionsFixedType` = the time/date/`evseKind` subset + `paymentBrand` (≤ 20) +
`paymentRecognition` (≤ 20) — used for card-tier pricing on `fixedFee`.

Time conditions are **station-local**, not UTC. Store the station timezone alongside the tariff.

## Tax

```
TaxRateType = type* string[0..20]  ·  tax* decimal (a PERCENTAGE)  ·  stack? integer ≥ 0 (default 0)
PriceType   = exclTax? decimal  ·  inclTax? decimal  ·  taxRates?(0..5)
```

| Trap | Rule |
|---|---|
| `tax` is a **percentage** | `21.0` means 21 %, **not** 0.21 and not 21 EUR |
| `taxRates` absent | **no tax applies** — it is *not* 0 % |
| stacking | `stack 0` applies to net; `stack 1` applies to the stack-0 result; etc. |
| `inclTax` present | **`exclTax` becomes mandatory** |
| all prices | **excluding tax**. `taxRates` layers on top |

`tax` is a `decimal` with no declared precision. Send it as a number and validate the range
yourself — `tax: 21.0` and `tax: 2100` both parse.

## Selection semantics — the rules that break billing

1. **Unconditional entries always match.** A price entry with no `conditions` is applicable to
   everything.
2. **First match wins.** When several entries match, only the **first in list order** is used.
   ⇒ **always append an unconditional fallback entry last.** Without it, an unhandled case
   silently costs nothing.
3. **A tariff cannot change mid-session by itself.** Only `ChangeTransactionTariff` changes it.
4. **`validFrom` replaces, never pre-empts.** A new tariff with `validFrom = T` takes effect at `T`,
   not immediately on delivery.
5. **Rejection has no cost.** The station deauthorizes and sends `triggerReason = TariffNotAccepted`
   — no `tariffId`, no `costDetails`. Do not invoice a tariff-less transaction; refund any
   prepayment.
6. **One association, once.** `transactionInfo.tariffId` reports the session↔tariff link exactly
   once.
7. **Local Authorization List breaks local costing.** LAL is incompatible with local cost
   calculation unless the default tariff applies to every driver.
8. **I08.FR.09** — never set `TariffType.validFrom` in `AuthorizeResponse.tariff`.
9. **I08.FR.08** — `tariffId` is immutable per content. New content ⇒ new id, or historic
   `chargingPeriods.tariffId` references become unverifiable.
10. **Re-sending the same id fails.** `DuplicateTariffId`. "Refreshing" means minting a new id.
11. **`minCost`/`maxCost` are load-bearing.** They set `typeOfCost` to `MinCost`/`MaxCost` — honour
    them when invoicing, or the invoice will not match what the driver was quoted.
12. **Currency is immutable mid-session** (`NoCurrencyChange`).

## Worked example — flat energy tariff with VAT

```jsonc
{
  "tariffId": "ADHOC-EUR-001",
  "currency": "EUR",
  "description": [ { "format": "ASCII", "language": "en", "content": "0.44 EUR/kWh incl. 21% VAT" } ],
  "energy": {
    "prices": [
      // peak first — first match wins
      { "priceKwh": 0.69, "conditions": { "startTimeOfDay": "16:00", "endTimeOfDay": "22:00" } },
      // unconditional fallback — MUST be last
      { "priceKwh": 0.44 }
    ],
    "taxRates": [ { "type": "vat", "tax": 21.0, "stack": 0 } ]
  },
  "fixedFee": {
    "prices": [ { "priceFixed": 0.50 } ],
    "taxRates": [ { "type": "vat", "tax": 21.0, "stack": 0 } ]
  }
}
```

Result for a 10 kWh peak session with the fixed fee:

```
energy  = 10 × 0.69        = 6.90 EUR   (net)
fee     = 1 × 0.50         = 0.50 EUR   (net)
net     = 7.40 EUR
vat     = 7.40 × 21%       = 1.554 EUR
gross   = 8.954 EUR
```

Recompute this **yourself** from `chargingPeriods` on every session. Never trust `totalCost`
blindly — see below.

## `costDetails`

```
costDetails (on TransactionEventRequest)
  failureToCalculate : boolean?          true ⇒ discard this cost, fall back to your own maths
  failureReason      : string[0..500]?
  chargingPeriods[]  : ChargingPeriodType   omitted on running-cost updates
  totalCost          : TotalCostType

ChargingPeriodType
  tariffId    : string[0..60]?    absent ⇒ "cost was calculated by some other means"
  startPeriod : dateTime*         a period ends when the next starts; the last ends at session end
  dimensions  : CostDimensionType?
```

`TotalCostType` carries the amount plus the tax breakdown:

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

### Mandatory verification before you invoice from `costDetails`

```
1. failureToCalculate != true           else fall back
2. chargingPeriods[] is present         else fall back   (absent on running-cost updates)
3. every period.tariffId is known       else you cannot prove the price
4. every period.tariffId == transactionInfo.tariffId, OR the change was explicit
                                        (TariffChanged triggerReason) — else reject
5. recompute from chargingPeriods + your stored tariff copy and compare to totalCost
   mismatch → flag for review, do not auto-invoice
6. cross-check total energy against your own meter accumulator from meterValue[]
   divergence beyond your tolerance → flag for review
```

Step 5 is the single highest-value control you can add. The station can be misconfigured, hold a
stale tariff or have a rounding bug. Recomputing from your own tariff copy turns a silent revenue
leak into a reviewable exception.

## Tariff storage

The tariff you publish is the evidence behind the invoice. Store it durably:

```
tariff_id            unique per content
tariff_content_hash  → detect drift between what you sent and what the station reports
currency, valid_from
components           the full JSON you sent (energy/chargingTime/idleTime/fixedFee/…)
conditions           your structured conditions, for local recomputation
authoritative        "station" | "central"  ← which VAT/cost authority you chose
state                draft | published | superseded | cleared
published_at, superseded_at
stations             where it was installed (evseId list, or "all" for evseId = 0)
```

`tariff_content_hash` is what makes step 3 of the reconciliation cheap and exact. To "update" a
tariff you mint a new `tariffId` and mark the old one `superseded` — you never mutate content under
a live id.

## Settlement

### `NotifySettlement` (station → CSMS)

| Field | Type | Card | Notes |
|---|---|---|---|
| `pspRef` | `identifierString[0..255]` | 1..1 | from the payment terminal; **is** the `idToken` value of the `DirectPayment` session |
| `status` | `PaymentStatusEnumType` | 1..1 | see below |
| `statusInfo` | `string[0..500]` | 0..1 | free text from the terminal |
| `settlementAmount` | `decimal` | 1..1 | settled, **or attempted** on failure |
| `settlementTime` | `dateTime` | 1..1 | |
| `transactionId` | `identifierString[0..36]` | 0..1 | **absent when the payment was cancelled before the OCPP session started** |
| `receiptId` | `string[0..50]` | 0..1 | |
| `receiptUrl` | `string[0..2000]` | 0..1 | when generated by the terminal or the CSMS |
| `vatNumber` | `string[0..20]` | 0..1 | for a company receipt |
| `vatCompany` | `AddressType` | 0..1 | company address for that VAT number |

Response: `receiptUrl`? · `receiptId`? — reply only when `PaymentCtrlr.ReceiptByCSMS = true`.

| `status` | Meaning | API action |
|---|---|---|
| `Settled` | success | mark `SETTLED`, issue the invoice |
| `Canceled` | **no billable part** — cancelled before the session started | `CANCELLED_PRE_TX`; void the authorisation; **do not invoice** |
| `Rejected` | rejected by the PSP | `FAILED_SETTLEMENT`; retry the capture off-protocol |
| `Failed` | failed after the final attempt (communication) | `FAILED_SETTLEMENT`; retry off-protocol, then escalate |

`PaymentStatusEnumType` = `Settled` · `Canceled` · `Rejected` · `Failed`.
(`"Cancelled"` appears in spec prose — the schema and enum use **single-L `Canceled`**.)

### Correlation

```
idToken.idToken = <pspRef>, idToken.type = "DirectPayment"   on RequestStartTransaction
NotifySettlement.pspRef = <same pspRef>                     on settlement

match on (pspRef, transactionId)     ← both, always
```

`pspRef` alone is **not** unique enough: a driver can retry a payment at the same kiosk and reuse a
reference. Also store `settlementAmount` and `settlementTime` — a `pspRef` can legitimately receive
more than one `NotifySettlement` (a retry), and the **last** one wins.

### Two settlement modes

| `PaymentCtrlr.SettlementByCSMS` | Who calls the PSP | What you receive |
|---|---|---|
| `false` (default) | the station | `NotifySettlement` for ad-hoc payments |
| `true` | **you** | **nothing** — no `NotifySettlement` ever arrives |

Probe this variable during discovery and branch. In `true` mode your PSP ledger is the *only*
source of truth for money movement — which means your own reconciliation must be airtight.

## `NotifyWebPaymentStarted` (CSMS → station)

`evseId`* (≥ 0) · `timeout`* (seconds). Blocks a **local** (kiosk/panel) start for `timeout`
seconds so your web checkout can finish. Response is empty.

Use it between "driver pressed start on the station" and "payment authorised". Without it the
driver can start charging unpaid. Set `timeout` to your checkout's real worst case plus margin —
too short and the start times out mid-payment.

## `VatNumberValidation` (CSMS → station)

Request: `vatNumber`* (`string[0..20]`) · `evseId`?
Response: **`vatNumber`\* (echo)** · `evseId`? (**echo**) · `status`* · `company`? · `statusInfo`?

`status` is a **`GenericStatusEnumType`** — only `Accepted` or `Rejected`. There is **no**
`ValidationError` enum value; the specific reason lives in `statusInfo.reasonCode`.

**Echo `vatNumber` in your response** — it is required in the reply, and omitting it is the most
common integration bug here. The station then cannot apply the reverse-charge treatment.

Typical flow: the driver scans a company VAT number at the station ⇒ the station asks you to
validate ⇒ you check the VIES/registry ⇒ reply `Accepted` or `Rejected` (+ `statusInfo.reasonCode` =
`"InvalidVATNumber"`) and echo `vatNumber` ⇒ the station applies or refuses reverse charge.

Expose this as a **push callback to the CSMS**, not a public REST endpoint — the station initiates
it. Authenticate the callback as a CSMS webhook.

## `transactionLimit` — the prepaid mechanism

Set it on your `TransactionEvent(Started)` response:

```
transactionLimit
  maxCost    : decimal?    maximum cost, in the tariff's currency
  maxEnergy  : decimal?    maximum energy in Wh
  maxTime    : integer?    maximum seconds from start to end
  maxSoC     : integer?    0..100, maximum EV state of charge %
```

The station **enforces** the limit and later reports `triggerReason = CostLimitReached` /
`EnergyLimitReached` / `TimeLimitReached` / `SoCLimitReached`.

This is 2.1's real answer to prepaid charging, and it is far better than 1.6/2.0.1's
`SetChargingProfile` amp hack: it is expressed in the driver's own currency and it is enforced by
the party that owns the meter.

Use `maxCost` for card payments. Round **up** to the nearest cent and add a small buffer so a
driver is not cut off a few cents short of the authorization. Keep
`transactionInfo.transactionLimit` from the events so you can reconcile what you asked for against
what was applied.

## Prepaid charging — the 2.1 way

```
1. driver starts at the kiosk (or your app)
2. NotifyWebPaymentStarted(evseId, timeout)          ← blocks a local start while you charge
3. PSP authorises → you get a pspRef
4. RequestStartTransaction(idToken.idToken = pspRef, idToken.type = "DirectPayment",
                           idToken.additionalInfo[CardBin, CardLast4Digits, …])
5. on Started → TransactionEventResponse.transactionLimit{maxCost: <authorised + buffer>}
6. station enforces it → later reports triggerReason = CostLimitReached
7. on Ended → costDetails gives the final cost
8. NotifySettlement(pspRef, status, settlementAmount, settlementTime, transactionId, …)
   — or you settle yourself when PaymentCtrlr.SettlementByCSMS = true
```

Never send raw card data. `additionalInfo` carries only what the display needs: `CardBin`,
`CardLast4Digits`, `CardBrand`. Anything more is a PCI problem.

## VAT handling summary

| Need | Mechanism |
|---|---|
| charge VAT to the driver | `TaxRateType{tax: 21.0, stack: 0}` on the tariff component |
| layered taxes (national + local) | multiple `TaxRateType` entries with `stack` 0 and 1 |
| company reverse charge | `VatNumberValidation` → `Accepted` + echo `vatNumber`; driver VAT number in `NotifySettlement` |
| tax breakdown on the receipt | `PriceType{exclTax, inclTax, taxRates}` and `TotalCostType` |
| VAT number on the receipt | `NotifySettlement.vatNumber` + `vatCompany` |

**Pick one VAT authority.** Decide whether the station's tariff tax or your central rating is
authoritative, store that decision on the tariff record, and never let both apply — double taxing
is the most likely 2.1 billing bug.

## Tariff and payment landmines

| Trap | Consequence |
|---|---|
| re-sending a `tariffId` | `DuplicateTariffId` → **409**, and a retry loop if you auto-retry |
| "refreshing" a tariff by re-sending | **does not work.** Mint a new `tariffId` |
| mutating content under a live `tariffId` | breaks I08.FR.08; historic `chargingPeriods.tariffId` references become unverifiable |
| `prices[]` with no unconditional fallback | unmatched cases cost **nothing** — silent revenue loss |
| putting the fallback entry **first** | it always matches and the conditional entries are never used |
| `validFrom` in `AuthorizeResponse.tariff` | violates **I08.FR.09** |
| `taxRates` absent | **no tax**, not 0 % |
| `tax` sent as a fraction (`0.21`) | 100× under-tax. It is a **percentage** (`21.0`) |
| `inclTax` without `exclTax` | invalid — `exclTax` is mandatory when `inclTax` is present |
| currency change mid-session | `NoCurrencyChange` ⇒ **409** |
| `minCost`/`maxCost` ignored | `typeOfCost` becomes `MinCost`/`MaxCost`; the invoice disagrees with the quote |
| Local Authorization List + local costing | **incompatible** unless the default tariff applies to every driver |
| `ClearTariffs` on a tariff in use | breaks a live session — **409** from your API |
| expecting `NotFound` from `ClearTariffs` | the per-tariff enum is `Accepted`/`Rejected`/**`NoTariff`** |
| matching `VatNumberValidation` on `ValidationError` | no such value. `GenericStatusEnumType` is `Accepted`/`Rejected`; read `statusInfo.reasonCode` |
| matching `RequestBatterySwap` on `NoBatteryAvailable` | no such enum value. It is `Rejected` + `statusInfo.reasonCode = "NoBatteryAvailable"` |
| expecting `TxNotFound` from `UsePriorityCharging` | that enum has only `Accepted` / `Rejected` / `NoProfile` |
| ignoring `totalCost.typeOfCost` | `MinCost` / `MaxCost` mean the tariff clamped the result — invoice the clamped value |
| conditions in station-local time | computing them in UTC shifts every boundary |
| expecting `NotifySettlement` always | it is **optional** — ad-hoc only, and never when `SettlementByCSMS = true` |
| correlating on `pspRef` alone | a retried payment reuses the reference — correlate on **`(pspRef, transactionId)`** |
| assuming one `NotifySettlement` per `pspRef` | retries send more; the **last** wins |
| billing on `Canceled` | **no billable part** — void, do not invoice |
| treating `settlementAmount` on `Failed` as collected | it is the **attempted** amount |
| not echoing `vatNumber`/`evseId` | the station cannot apply reverse charge |
| sending raw card data in `additionalInfo` | PCI violation. Send only `CardBin`, `CardLast4Digits`, `CardBrand` |
