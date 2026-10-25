# Contributing

Thanks for improving the OCPP skill. This project is a **reference for building an API in front of
an OCPP CSMS**, not a protocol reimplementation. Contributions are judged on whether they help a
real integrator avoid a real failure.

## Ground rules

- **Version accuracy over generality.** If a rule differs between 1.6, 2.0.1 and 2.1, say so
  explicitly. Do not write "OCPP generally" when the versions disagree.
- **Explain the failure mode.** A rule without a consequence becomes cargo cult. State what breaks:
  a wrong bill, a stopped session, a silent 501, a duplicate invoice.
- **Cite the source.** Reference the OCPP specification part/section, an errata item, or a
  reproducible message trace. Vendor docs are acceptable for vendor quirks, clearly labelled.
- **No vendor marketing.** SDKs and CSMS products can appear as examples, not as requirements.
- **No secrets, customer data or private endpoints.** Redact traces before adding them.

## Repository layout

```text
README.md, CHANGELOG.md, CONTRIBUTING.md, LICENSE  # repository docs (root)
install.sh                    # installer for Claude Code and OpenCode
scripts/validate_skill.py     # dependency-free validator (repo tooling)
evals/                        # trigger and task eval sets (repo tooling)
.github/workflows/validate.yml # CI validation
skills/ocpp-skills/
  SKILL.md                    # the only skill entry point
  references/versions.md      # version selection, comparison, migration
  references/version-*.md     # build playbooks
  references/contract-*.md    # wire-level operations, enums, events
  references/billing.md       # energy → money, shared
  references/tariffs.md       # 2.1 tariff/cost/settlement
  references/api-design.md    # REST surface and integration patterns
  references/traps.md         # cross-version trap catalogue
```

The skill lives under `skills/ocpp-skills/` so it is discoverable by the
[`npx skills`](https://github.com/vercel-labs/skills) CLI — users installing it get only `SKILL.md`
and `references/`. Maintainer tooling (`scripts/`, `evals/`, installer, CI) stays at the repository
root. All paths below are relative to the repository root.

`SKILL.md` must stay a **router plus universal rules**. Version specifics belong in a playbook or
contract file. If `SKILL.md` grows past 500 lines, move detail into a reference and link it.

## Adding or changing a version

1. Create `references/version-<version>.md` and `references/contract-<version>.md`.
2. Add the subprotocol to the table in `SKILL.md` and `references/versions.md`.
3. Add its deltas to the comparison matrix and the task router.
4. Update `README.md` (supported versions, structure, compatibility).
5. Add a trigger eval and at least one task eval in `evals/`.
6. Run `python3 scripts/validate_skill.py`.

Do not create a second `SKILL.md`. One installable skill is the point of this project.

## Style

- Use the imperative: "persist the transaction id", not "the transaction id should be persisted".
- Prefer tables for field/status/operation matrices and short code blocks for formulas.
- Keep one idea per bullet.
- Use `text` fences for pseudo-code and `jsonc` for payload examples.
- Name files lower-case with hyphens.
- No trailing whitespace; one trailing newline.

## Frontmatter

```yaml
---
name: ocpp-skills
description: "..."
license: MIT
compatibility: "..."
metadata:
  opencode/autoinvoke: true
  version: "1.0.0"
---
```

- `name` must be lowercase kebab-case, 1–64 characters, and match the directory name.
- `description` must be ≤ 1024 characters and must include both **what** the skill does and **when**
  to use it. Put the strongest trigger terms first.
- Do not add tool-specific fields that break the Agent Skills standard. OpenCode-specific hints go
  under `metadata`.

## Validation

```bash
python3 scripts/validate_skill.py
```

The validator checks:

- frontmatter presence and basic YAML structure;
- name format, length and directory match;
- description presence and length;
- `SKILL.md` body size;
- local Markdown links resolve;
- every reference file is reachable from `SKILL.md`;
- no empty files and no invalid UTF-8;
- eval JSON parses.

CI runs the same command on every push and pull request.

## Evals

`evals/trigger-evals.json` contains should-trigger and should-not-trigger queries. `evals/evals.json`
contains task prompts with expected behaviour. They are maintainer tools, not an automatic grader.

When changing the description or the router, run the trigger set against a real agent and report
the before/after trigger rate in the pull request. When changing billing or tariff guidance, add a
task eval that exercises the new rule.

## Pull request checklist

- [ ] The change is version-specific where it needs to be, and says which version.
- [ ] The failure mode is explained, not just the rule.
- [ ] `SKILL.md` is still a router, not a dump.
- [ ] Local links resolve and new references are linked from `SKILL.md`.
- [ ] `python3 scripts/validate_skill.py` passes.
- [ ] `CHANGELOG.md` has an entry under `Unreleased`.
- [ ] No secrets, customer data or unredacted traces.

## Commit messages

Use a short imperative subject and a body that explains the failure mode:

```text
Fix 2.1 multiplier example in billing reference

The old example said 4.9 kWh × multiplier 0 was 4.9 kWh, which hides the
required ×1000 unit conversion. A 4900 Wh reading would be underbilled by
1000×. Correct the table and add the kWh case to the task eval.
```

## License

By contributing, you agree that your contribution is licensed under the MIT License.
