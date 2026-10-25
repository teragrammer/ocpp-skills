# Changelog

All notable changes to this skill are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- The validator no longer skips every file when the skill is installed under a hidden directory
  such as `~/.claude/skills/ocpp-skills` or `~/.config/opencode/skills/ocpp-skills`.
- `install.sh --dir PATH` now treats `PATH` as a parent directory and installs to `PATH/ocpp-skills`, keeping
  the skill name aligned with its directory.

### Changed

- Renamed the application from `ocpp` to `ocpp-skills`; the frontmatter `name`, installer target and
  docs now all use `ocpp-skills`.
- Moved the skill into `skills/ocpp-skills/` so the repository is discoverable by the
  [`npx skills`](https://github.com/vercel-labs/skills) CLI (`npx skills add <owner>/ocpp-skills`).
  Repository docs, installer and CI workflow stay at the root.
- Moved the maintainer tooling (`scripts/validate_skill.py`, `evals/`) out of the skill directory to
  the repository root, so installing the skill ships only `SKILL.md` and `references/`. The validator
  now takes an optional package directory argument (`python3 scripts/validate_skill.py <dir>`) to
  validate installed copies.
- Corrected the 2.x unit-normalisation example: for `value = 4.9`, unit `kWh` and
  `multiplier = 0`, the reading is **4900 Wh**, not 4.9 Wh; the old "naive" column entry was wrong.

## [1.0.0] — 2026-10-25

### Added

- One unified `ocpp` skill covering OCPP-J 1.6, OCPP 2.0.1 and OCPP 2.1, replacing the three
  separate API-backend skills.
- Version router in `SKILL.md` with a single "establish the version first" step.
- Version playbooks: `references/version-1.6.md`, `version-2.0.1.md`, `version-2.1.md`.
- Wire contracts: `references/contract-1.6.md`, `contract-2.0.1.md`, `contract-2.1.md`.
- Shared API integration guidance in `references/api-design.md`: REST↔OCPP command/event contracts,
  HTTP status mapping, idempotency, offline queue classes, long-running operations, capability
  flags, security and a testing checklist.
- Shared billing guidance in `references/billing.md`: energy formulas, unit normalisation, `seqNo`
  completeness, rating, invoice shape, reconciliation, refunds and daily money checks.
- 2.1 tariff and settlement deep dive in `references/tariffs.md`.
- Cross-version trap catalogue with a symptom index in `references/traps.md`.
- Version selection, comparison and migration guide in `references/versions.md`.
- Publish-ready repository files: README, MIT license, contributing guide, changelog.
- `install.sh` for Claude Code and OpenCode, with personal, project and custom-directory modes.
- Dependency-free `scripts/validate_skill.py` and a GitHub Actions validation workflow.
- Trigger and task eval sets under `evals/`.

### Changed

- Consolidated the repeated universal invariants from the three source skills into one place.
- Standardised the frontmatter on the Agent Skills layout (`name: ocpp`, portable `description`,
  `license`, `compatibility`) so the same directory works in Claude Code and OpenCode.
- Replaced per-version copies of the billing guidance with one shared `billing.md` plus a 2.1
  tariff/settlement file.
