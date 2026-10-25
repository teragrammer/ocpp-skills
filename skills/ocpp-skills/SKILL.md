---
name: ocpp-skills
description: "Build the HTTP/JSON API backend that sits in front of an OCPP central system (CSMS) for EV charging across OCPP-J 1.6, 2.0.1 and 2.1. Use when mapping REST endpoints to OCPP actions such as RemoteStartTransaction, RequestStartTransaction, TransactionEvent, SetDefaultTariff and NotifySettlement; when computing session energy, tariffs, cost, VAT, invoices or refunds; when authorizing drivers or payments; when handling smart charging, reservations, configuration or status; or when debugging OCPP statuses, seqNo gaps, meter values and protocol traps. Trigger on OCPP, OCPP-J, ocpp1.6, ocpp2.0.1, ocpp2.1, CSMS or charge-point backend even when no version is named. Do not use to write charger firmware or a raw OCPP WebSocket server."
license: MIT
compatibility: "Agent Skills standard (SKILL.md). Works with Claude Code, OpenCode, and other compatible agents. No runtime dependencies."
metadata:
  opencode/autoinvoke: true
  version: "1.0.0"
---

# OCPP API Backend

Build the **public HTTP/JSON API** that fronts an OCPP central system (CSMS). The CSMS owns the
WebSocket, the subprotocol, the RPC envelope and the station session. You own the product
contract: who may charge, what it costs, how it is paid, invoiced and refunded.

```
driver app / portal / partner ──HTTP──▶ YOUR API ──command + event contract──▶ OCPP CSMS ──WS──▶ charger
```

**Out of scope:** charger firmware, OCPP-J framing, a raw WebSocket CSMS. If the task is to build
the CSMS itself, say so instead of pretending this skill covers it.

## Step 0 — Establish the version before anything else

OCPP 1.6, 2.0.1 and 2.1 are **different dialects**, not minor revisions. The same endpoint has a
different operation, different identity model, different transaction lifecycle and sometimes a
different error spelling in each one.

Find the version in the CSMS configuration, the negotiated subprotocol, the repository manifest, or
the charger's `BootNotification`. If it is still unclear, ask exactly one question:

> Which OCPP subprotocol does the CSMS negotiate: `ocpp1.6`, `ocpp2.0.1` or `ocpp2.1`?

Do not write "version-neutral" code that silently assumes 2.x. Then load exactly one playbook:

| Subprotocol | Playbook | Wire contract |
|---|---|---|
| `ocpp1.6` | [references/version-1.6.md](references/version-1.6.md) | [references/contract-1.6.md](references/contract-1.6.md) |
| `ocpp2.0.1` | [references/version-2.0.1.md](references/version-2.0.1.md) | [references/contract-2.0.1.md](references/contract-2.0.1.md) |
| `ocpp2.1` | [references/version-2.1.md](references/version-2.1.md) | [references/contract-2.1.md](references/contract-2.1.md) |

For choosing, comparing or migrating versions, read [references/versions.md](references/versions.md).

## The only two contracts you need

The CSMS already speaks OCPP. Your API needs a **command contract** and an **event contract** —
not a reimplementation of the protocol.

**Command contract** — for each public endpoint: which OCPP operation the CSMS must issue, which
payload fields are required, which reply statuses map to which HTTP codes, and whether the
operation may be queued while the charger is offline.

**Event contract** — for each inbound OCPP message the CSMS must forward: which fields you need,
how you correlate them to your own `session_id`, and how you deduplicate replays.

Write both down before writing handlers. A missing event field is discovered in production; a
missing correlation key is discovered in billing.

## Universal invariants

These hold in every version. Version-specific rules are in the playbooks.

1. **`POST /sessions` returns `202`, never `200`.** `Accepted` from the CSMS means "request
   accepted", not "charging started". In 2.x the OCPP `transactionId` does not even exist until the
   charger sends `TransactionEvent(Started)`.
2. **Know who owns `transactionId`.** 1.6: the **CSMS** allocates an integer and you persist it
   from `StartTransaction.conf`. 2.x: the **charger** allocates a string and you bind it on
   `Started`. Never mint a 2.x id; never lose a 1.6 id.
3. **Omit absent optional fields.** Never send `null`, `""`, `{}` or `[]` for an absent field.
   Schemas are `additionalProperties: false`, and every `0..*` list has `minItems: 1` when present.
4. **Status is not error.** `Rejected`, `Occupied`, `Unknown`, `NoTariff`, `NoProfile`,
   `DuplicateTariffId` and friends are normal CALLRESULTs. Map them to 4xx. Reserve 5xx for your
   own failures or malformed OCPP.
5. **Do not queue operations that need a live socket.** Start, stop, unlock, reset, trigger,
   `CostUpdated` and certificate operations go stale or retarget. Reject with **409/503**
   `{chargerOffline: true, lastSeen}`. A queued stop can hit a **recycled** transaction id and stop
   the wrong session.
6. **MeterValues is not the invoice.** 1.6 bills `meterStop − meterStart`. 2.x bills the
   `Transaction.Begin`/`Transaction.End` register difference. Meter samples are for display,
   previews and cross-checks.
7. **`.Register` is cumulative — difference it. `.Interval` is a delta — sum it.** Never mix the
   two. Never sum L1+L2+L3 when the charger already sends an all-phase total. Never sum `Inlet` and
   `Outlet`. Never bill `SignedData`.
8. **`SampledValue.value` is a string.** Parse it as a decimal, not a float. In 2.x,
   `unitOfMeasure.multiplier` is a **base-10 exponent**, not a conversion factor.
9. **Prove completeness before invoicing in 2.x.** `seqNo` is per-EVSE monotonic. A gap or
   `offline: true` means `GetTransactionStatus`; `messagesInQueue: true` means defer billing.
10. **Deduplicate and order by the charger.** Inbound dedupe key: 1.6
    `(station, action, transactionId, timestamp)`; 2.x `(stationId, transactionId, seqNo)`. Store
    both the charger `timestamp` and your `received_at`; use the charger clock for billing windows.
11. **Negotiate capabilities; never assume them.** 2.x has no `SupportedFeatureProfiles`. Probe the
    device model with `GetBaseReport` + targeted `GetVariables`, cache per station, and invalidate on
    every boot and post-firmware-install. A 2.0.1 station answers `NotImplemented` to every
    2.1-only action without dropping the session.
12. **Money has one source of truth per version.** 1.6: your rate table over the meter delta. 2.0.1:
    your rate table over the meter delta; `CostUpdated` is display-only. 2.1: the station may
    calculate `costDetails`, but you still compute and store a central fallback and reconcile both.

## Version deltas that change the design

| Concept | 1.6 | 2.0.1 | 2.1 |
|---|---|---|---|
| Subprotocol | `ocpp1.6` | `ocpp2.0.1` | `ocpp2.1` |
| Transaction lifecycle | `StartTransaction` → `MeterValues` → `StopTransaction` | `TransactionEvent` `Started`/`Updated`/`Ended` | same as 2.0.1 |
| `transactionId` owner | **CSMS** (integer) | **charger** (string ≤ 36) | **charger** (string ≤ 36) |
| Authorization | `idTag` → `IdTagInfo` | `IdToken` → `idTokenInfo` | same as 2.0.1 + `DirectPayment` |
| Config | `ChangeConfiguration(key, value)` | `SetVariables(component, variable)` | same as 2.0.1 |
| Connector addressing | `connectorId` | `evseId` + `connectorId` | same as 2.0.1 |
| Price / tariff | **none** | **none** (`CostUpdated` push only) | native `SetDefaultTariff`, `costDetails` |
| Payment / settlement | **none** | **none** | `NotifySettlement`, `VatNumberValidation`, `transactionLimit` |
| Message types | 2, 3, 4 | 2, 3, 4 | 2, 3, 4, **5, 6** |
| RPC error spelling | `Occurence…`, `Formation…` | `Occurence…`, `FormatViolation` | `Occurrence…`, `FormatViolation` |
| Completeness proof | dedupe + orphan handling | `seqNo` per EVSE | `seqNo` per EVSE |

## Route by task

| Task | Read first |
|---|---|
| Choose or migrate a version | [references/versions.md](references/versions.md) |
| Design the REST surface, error codes, idempotency, offline behaviour | [references/api-design.md](references/api-design.md) |
| Start, stop, unlock, reserve or configure a charger | the version playbook, then its contract |
| Read energy, compute kWh, rate a session, invoice or refund | [references/billing.md](references/billing.md) |
| Publish tariffs, verify `costDetails`, settle payments, validate VAT | [references/tariffs.md](references/tariffs.md) |
| Debug a status, missing event, duplicate, gap or 1000× bill | [references/traps.md](references/traps.md) |
| Look up an operation, field, enum or CALLERROR code | the version contract |

## Never do this

1. Never use `connectorId = 0` on `RemoteStartTransaction`, `TriggerMessage` or `UnlockConnector`
   in 1.6 — it is a spec violation.
2. Never return an OCPP `transactionId` from `POST /sessions` in 2.x before `Started` arrives.
3. Never finalise a 2.x invoice without the `seqNo` completeness proof or a `GetTransactionStatus`
   check.
4. Never treat `SetVariables`/`GetVariables` as all-or-nothing — read **every** element of the
   per-item result array.
5. Never wildcard an `instance` in `GetVariables`; `""` means the default instance, not "all".
6. Never expose lowering `SecurityCtrlr.SecurityProfile` through a public API.
7. Never bill a 2.1 session with `triggerReason = TariffNotAccepted` and no `tariffId` — refund it.
8. Never re-send a 2.1 `tariffId` with different content. Mint a new id; `tariffId` is immutable per
   content.
9. Never omit the unconditional fallback entry in a 2.1 `prices[]` list — unmatched sessions would
   cost nothing.
10. Never treat `SuspendedEV`, `SuspendedEVSE`, `Idle` or `evseSleep` as the end of a session. Only
    `Ended` ends it.
11. Never use 1.6 config names in 2.x (`TxEnabled`, `MeterValuesSampledData`, `SignedMeterValue` do
    not exist there).
12. Never add extra keys to an OCPP payload. Use `customData` or `DataTransfer`.

## Reference map

| File | Contents |
|---|---|
| [references/versions.md](references/versions.md) | version selection, full comparison, negotiation, migration |
| [references/version-1.6.md](references/version-1.6.md) | 1.6 build playbook: endpoint map, events, billing, traps |
| [references/version-2.0.1.md](references/version-2.0.1.md) | 2.0.1 build playbook: endpoint map, events, `seqNo`, billing |
| [references/version-2.1.md](references/version-2.1.md) | 2.1 build playbook: tariffs, settlement, new actions |
| [references/contract-1.6.md](references/contract-1.6.md) | 1.6 operations, enums, event fields, CALLERRORs |
| [references/contract-2.0.1.md](references/contract-2.0.1.md) | 2.0.1 operations, enums, event fields, CALLERRORs |
| [references/contract-2.1.md](references/contract-2.1.md) | 2.1 operations, enums, event fields, message types 5/6 |
| [references/api-design.md](references/api-design.md) | REST↔OCPP contract, HTTP mapping, idempotency, reconnect |
| [references/billing.md](references/billing.md) | energy maths, units, rating, invoices, refunds, reconciliation |
| [references/tariffs.md](references/tariffs.md) | 2.1 tariff model, `costDetails`, VAT, settlement, prepaid |
| [references/traps.md](references/traps.md) | cross-version trap catalogue and symptom index |
