# OCPP API Backend — one skill, three OCPP versions

A single, open-source [Agent Skill](https://agentskills.io) for building the **HTTP/JSON API
backend that sits in front of an OCPP central system (CSMS)** for EV charging.

It covers **OCPP-J 1.6**, **OCPP 2.0.1** and **OCPP 2.1** in one skill. You install one directory;
the skill asks which subprotocol the CSMS negotiates and loads only the right playbook. No
per-version skills, no protocol mixing, no copy-pasting the same invariants three times.

> **Scope:** the public API and its contract with the CSMS. The CSMS owns the WebSocket, the
> subprotocol, the RPC envelope and the charger session. Charger firmware and a raw OCPP WebSocket
> server are deliberately out of scope.

## Why this exists

Most OCPP guidance is either a protocol dump or a vendor-specific SDK tutorial. The hard part of a
charging backend is not the frame format — it is the **money and state contract**:

- Which OCPP operation backs each REST endpoint, and what HTTP code its status maps to.
- Who owns `transactionId` in this version (the CSMS in 1.6, the charger in 2.x).
- How to turn meter samples into a bill without a 1000× unit error.
- How to prove you received every `TransactionEvent` before invoicing.
- How to publish a tariff whose `tariffId` is immutable per content.
- How to reconcile a station-calculated cost against your own.
- What to do when a charger is offline, a session is orphaned, or a `StopTransaction` never arrives.

This skill encodes those decisions for all three versions, with the traps that actually reach
production.

## What's inside

```text
ocpp/
├── SKILL.md                     # the only entry point: version router + universal invariants
├── references/
│   ├── versions.md              # choose, compare and migrate versions
│   ├── version-1.6.md           # 1.6 build playbook
│   ├── version-2.0.1.md         # 2.0.1 build playbook
│   ├── version-2.1.md           # 2.1 build playbook (tariffs + settlement)
│   ├── contract-1.6.md          # 1.6 operations, enums, events, CALLERRORs
│   ├── contract-2.0.1.md        # 2.0.1 operations, enums, events, CALLERRORs
│   ├── contract-2.1.md          # 2.1 operations, enums, events, message types 5/6
│   ├── api-design.md            # REST↔OCPP contract, HTTP mapping, idempotency, reconnect
│   ├── billing.md               # energy maths, rating, invoices, refunds, reconciliation
│   ├── tariffs.md               # 2.1 TariffType, costDetails, VAT, settlement
│   └── traps.md                 # cross-version trap catalogue + symptom index
├── scripts/validate_skill.py    # dependency-free skill validator
├── evals/                       # trigger and task eval sets for maintainers
├── install.sh                   # installer for Claude Code and OpenCode
├── README.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── LICENSE
└── .github/workflows/validate.yml
```

Only `SKILL.md` is loaded when the skill triggers. The references load on demand, so the skill costs
roughly one description in context until you need a specific version or topic.

## Supported versions

| Subprotocol | Marketing name | Playbook | Native tariff / payment |
|---|---|---|---|
| `ocpp1.6` | OCPP-J 1.6 | `references/version-1.6.md` | No — you own pricing |
| `ocpp2.0.1` | OCPP 2.0.1 | `references/version-2.0.1.md` | No — `CostUpdated` is display-only |
| `ocpp2.1` | OCPP 2.1 | `references/version-2.1.md` | Yes — `SetDefaultTariff`, `costDetails`, `NotifySettlement` |

The skill also covers migration between versions and mixed-fleet architecture.

## Requirements

- An agent that loads the [Agent Skills](https://agentskills.io) `SKILL.md` layout:
  **Claude Code**, **OpenCode**, or another compatible tool.
- No MCP server, network access, API key, runtime dependency or build step.
- `python3` only if you want to run the validator.

## Installation

Pick **one** of the methods below. The skill directory must be named `ocpp` and contain `SKILL.md`
at its root.

### Claude Code — personal (all projects)

```bash
git clone https://github.com/<your-org>/ocpp.git ~/.claude/skills/ocpp
```

Or, if you already cloned this repository:

```bash
./install.sh --claude
```

The result is:

```text
~/.claude/skills/ocpp/SKILL.md
```

Claude Code detects skill changes live; run `/reload-skills` if you created the skills directory
during the current session.

### Claude Code — project (share with the repo)

```bash
mkdir -p .claude/skills
cp -R /path/to/ocpp .claude/skills/ocpp
```

Or:

```bash
./install.sh --project
```

Commit `.claude/skills/ocpp/` so every contributor gets the same guidance.

### OpenCode — personal (all projects)

```bash
mkdir -p ~/.config/opencode/skills
cp -R /path/to/ocpp ~/.config/opencode/skills/ocpp
```

Or:

```bash
./install.sh --opencode
```

OpenCode also discovers `~/.claude/skills/`, so the Claude personal install works for OpenCode too.
Use the native path when you want OpenCode-specific configuration and no dependency on Claude's
directory layout.

### OpenCode — project

```bash
mkdir -p .opencode/skills
cp -R /path/to/ocpp .opencode/skills/ocpp
```

Or:

```bash
./install.sh --project-opencode
```

OpenCode also discovers `.claude/skills/`, so a single project install under `.claude/skills/ocpp`
serves both tools.

### Install for both tools

```bash
./install.sh --both
```

This copies the skill to `~/.claude/skills/ocpp` and `~/.config/opencode/skills/ocpp`. The two
copies are independent; update both when you pull a new version.

### Custom location

```bash
./install.sh --dir ~/agent-skills
```

This installs to `~/agent-skills/ocpp`. `--dir` is the parent directory; the installer keeps the
`ocpp` directory name so the skill name and its directory stay aligned.

### Manual install (any agent, including Windows)

1. Copy this directory so the destination contains `SKILL.md` at its root.
2. Place it in your agent's skills directory. Common locations:
   - Claude Code personal: `%USERPROFILE%\.claude\skills\ocpp\`
   - Claude Code project: `.claude\skills\ocpp\`
   - OpenCode personal: `%USERPROFILE%\.config\opencode\skills\ocpp\`
   - OpenCode project: `.opencode\skills\ocpp\`
3. Restart or reload the agent if it does not pick up the new skill automatically.

### Verify

From the skill directory:

```bash
python3 scripts/validate_skill.py
```

Expected: `OK` with the skill name, version and file count. The validator checks frontmatter, name
format, description length, local links, reference reachability and empty files. It has no
third-party dependencies.

Then ask your agent something that should trigger it:

```text
I need to add a POST /sessions endpoint in front of our ocpp1.6 CSMS.
```

In Claude Code you can also invoke it explicitly with `/ocpp`. In OpenCode, mention `@ocpp` or let
the description trigger it.

### Update

If the skill directory is a git clone:

```bash
cd ~/.claude/skills/ocpp && git pull
```

If you copied it:

```bash
./install.sh --claude --force
```

`--force` replaces an existing install. Without it, the installer refuses to overwrite a directory.

### Uninstall

```bash
rm -rf ~/.claude/skills/ocpp
rm -rf ~/.config/opencode/skills/ocpp
```

Remove only the paths you installed.

## Usage

The skill is designed to trigger on real backend work, not only on the word "OCPP". Example prompts:

```text
Map our REST API onto ocpp2.1. We need start/stop, tariffs, prepaid card caps and invoices.
```

```text
Our 2.0.1 invoices are 1000x too high. The station sends 4900 with unit Wh and multiplier 0.
```

```text
Design the event contract the CSMS must forward so we can bill a session exactly once.
```

```text
We have a mixed fleet of 1.6 and 2.1 chargers. Show me how to keep one public API without
leaking version concepts into every handler.
```

```text
A station sends TransactionEvent(Ended) with no meterValue and offline=true. Should we invoice?
```

```text
Publish a tariff with a peak/off-peak energy price, a fixed fee, 21% VAT and an unconditional
fallback. Then show me how to verify the station's costDetails before invoicing.
```

The skill starts with the version question. If you already named the subprotocol, it goes straight
to that playbook.

## How it works

```
SKILL.md
  ├─ Step 0: identify ocpp1.6 / ocpp2.0.1 / ocpp2.1
  ├─ universal invariants that apply to every version
  ├─ version delta table for design decisions
  ├─ task router → one reference file
  └─ "never do this" list

references/version-<x>.md   → what to build for that version
references/contract-<x>.md  → exact operations, fields, enums, errors
references/billing.md       → energy → money, shared across versions
references/tariffs.md       → 2.1 tariff/cost/settlement model
references/api-design.md    → REST surface, HTTP mapping, idempotency, reconnect
references/traps.md         → symptom → cause → fix
```

The version playbooks deliberately do **not** repeat the full protocol. They point at the contract
file for wire details and at the shared money files for billing. That keeps each loaded file focused
and avoids three divergent copies of the same rule.

## Design principles

1. **Version first.** A 1.6 `transactionId` is a CSMS-owned integer; a 2.x one is a charger-owned
   string. There is no safe "generic" OCPP.
2. **Two contracts, not a proxy.** Your API exposes domain commands and events. It does not expose
   raw OCPP payloads.
3. **Money is a state machine.** Snapshot the rate, prove completeness, freeze the cost, then
   invoice. Never retro-price a closed session.
4. **Degrade explicitly.** A missing capability is a 501 and a hidden feature, not a silent retry.
5. **Fail visibly.** Offline, timeout and orphaned sessions get explicit states and alerts, never
   best-effort guesses.
6. **Progressive disclosure.** One entry point; the model reads only the version and topic it needs.
7. **Vendor-neutral.** No SDK or CSMS vendor is required. `customData` and `DataTransfer` are
   treated as untrusted extension points.

## Compatibility notes

| Tool | Status | Notes |
|---|---|---|
| Claude Code | Supported | Personal, project, plugin, or `--add-dir` skills directory. `/ocpp` invocation. |
| OpenCode V2 | Supported | Native `.opencode/skills/ocpp` or compatibility `.claude/skills/ocpp`. |
| Claude.ai / Cowork | Supported | Upload or package the skill directory as a skill archive. |
| Other Agent Skills tools | Supported | Standard `SKILL.md` + `references/` layout, no tool-specific runtime. |
| OCPP 1.6 / 2.0.1 / 2.1 | Supported | See the version matrix. |

Frontmatter is intentionally minimal and portable:

```yaml
name: ocpp
description: ...
license: MIT
compatibility: ...
metadata:
  opencode/autoinvoke: true
  version: "1.0.0"
```

`name` is lowercase kebab-case and matches the directory. `description` is under the 1024-character
Agent Skills limit. `metadata.opencode/autoinvoke` is an OpenCode-specific hint; other tools ignore
it.

## Quality gates

The repository ships a dependency-free validator and a GitHub Actions workflow:

```bash
python3 scripts/validate_skill.py
```

It checks:

- frontmatter exists, parses, and has a valid `name` (lowercase kebab-case, 1–64 chars);
- `name` matches the directory;
- `description` exists and is ≤ 1024 characters;
- `SKILL.md` stays under 500 lines;
- every local Markdown link resolves;
- every file in `references/` is reachable from some Markdown file;
- no empty files and no invalid UTF-8;
- eval JSON files parse.

The `evals/` directory contains realistic trigger prompts and task prompts. They are not run
automatically — they are a starting point for maintainers testing a change against a real agent.

## Customization

- **Add a version:** copy a `version-*.md` + `contract-*.md` pair, update the router in `SKILL.md`
  and the matrix in `references/versions.md`, then run the validator. See `CONTRIBUTING.md`.
- **Add a topic:** create `references/<topic>.md`, link it from the task router, and keep it focused
  on one decision.
- **Company-specific rules:** fork and add a `references/company-policy.md`; link it from the router.
  Do not edit the protocol facts to match an internal convention — document the convention as a
  policy layer.
- **Localization:** keep `SKILL.md` in English for trigger reliability; translated references are
  fine as long as the router names them.

## Publishing

To publish this as a single open-source Agent Skill repository:

1. Push this directory as the root of a new repository, for example `github.com/<your-org>/ocpp`.
2. Keep the directory name `ocpp` and the `SKILL.md` `name: ocpp` field aligned; both Claude Code and
   OpenCode require the skill name to match its directory.
3. Set the release version in the frontmatter metadata and the matching entry in `CHANGELOG.md`.
4. Tag the release (for example `v1.0.0`); the `validate` GitHub Actions workflow runs on every push
   and pull request.
5. Attach a zip of this directory, excluding `.git/`, to the GitHub release. Consumers extract it
   into their skills directory and validate with `scripts/validate_skill.py`.

No build step is required. The published artifact is just the directory tree: `SKILL.md` plus
`references/`, with the install script, validator and evals alongside.

## Contributing

Issues and pull requests are welcome. Read `CONTRIBUTING.md` first.

The most valuable contributions are:

- a reproducible OCPP trap with the exact message, version and consequence;
- a correction backed by the spec section or errata number;
- a new worked example for tariffs, billing or reconciliation;
- a compatibility fix for a real CSMS or library.

Please do not add vendor marketing, SDK-specific workarounds presented as protocol facts, or
"best practice" without a failure mode.

## License

MIT. See `LICENSE`.

OCPP is a trademark of the Open Charge Alliance. This project is an independent community skill and
is not affiliated with or endorsed by the OCA.
