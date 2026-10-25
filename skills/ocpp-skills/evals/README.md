# Evals

These are maintainer tools, not an automatic grader. They exist so a change to the description or
the version router can be checked against realistic prompts before release.

## `trigger-evals.json`

A mixed set of should-trigger and should-not-trigger queries. The negative cases are deliberately
close to the domain: charger firmware, a raw WebSocket CSMS, general EV questions, adjacent
payments work and plain database tuning. A description that triggers on those is too broad.

Run them through a real agent with and without the skill, and compare:

- **Should trigger:** the agent should load the OCPP skill.
- **Should not trigger:** the agent should answer directly or load a different skill.

There is no built-in runner because the available harness differs by tool. Keep the before/after
rate in the pull request when changing the description.

## `evals.json`

Six task prompts with expected behaviour and a small rubric. They cover:

1. 1.6 start/stop and the `meterStop − meterStart` formula.
2. 2.0.1 `seqNo` completeness and deferred invoicing.
3. 2.1 tariff publication, fallback pricing, VAT and `costDetails` verification.
4. Mixed-fleet adapter architecture.
5. Offline stop commands and the live-socket queue rule.
6. `VatNumberValidation` direction and the required echo.

Use them as a smoke test: a fresh agent with only `SKILL.md` should route each prompt to the right
reference and avoid the named trap. If it fails, check the router and the relevant playbook before
adding more prose.

## Schema

`evals.json` follows the common skill-eval shape:

```json
{
  "skill_name": "ocpp",
  "evals": [
    {
      "id": 1,
      "name": "descriptive-name",
      "prompt": "The user's request",
      "expected_output": "What a good answer must contain",
      "assertions": ["An objectively checkable statement"],
      "files": []
    }
  ]
}
```

`trigger-evals.json` is a flat array:

```json
[
  { "query": "A realistic user request", "should_trigger": true }
]
```

The validator only checks that both files parse as JSON. It does not run the agent.
