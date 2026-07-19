# TraceArena Outreach & Feedback Playbook

> This is an operational guide for the first 90 days after the public release.
> It turns a public demo into repeatable adoption, contribution, and qualified
> commercial conversations without making unverified performance claims.

## 1. One public path

Use one path in every announcement so a reader always knows what to do next:

1. **See it:** [live demo](https://tonyworld888-tracearena-demo.static.hf.space/index.html)
2. **Run it:** [no-key Market Replay](../../examples/market_replay/README.md)
3. **Discuss a world:** [scenario-pack guide](../scenario-pack-guide.md)
4. **Join the public technical discussion:** [Physical World OS contract discussion](https://github.com/tonyhyworld/TraceArena/discussions/14)
5. **Request an evaluation pilot:** [pilot issue form](../../.github/ISSUE_TEMPLATE/agent-evaluation-pilot.yml)
6. **Ask about a private engagement:** [commercial support](../commercial-support.md)

Do not send people directly to a generic “contact us” message when a runnable
example or structured issue form can answer the next question.

## 2. Audience-specific messages

### Agent developers

> Put your Agent in a stateful world, give it real tools and explicit rules,
> then inspect whether its evidence, actions, and outcomes agree.

Call to action: run the replay and open a bug, feature request, or scenario
proposal with the smallest reproducible trace.

### Evaluation and platform teams

> Compare agents on the same world state and authoritative settlement instead
> of comparing ungrounded transcripts.

Call to action: submit the evaluation pilot form with the workflow and
acceptance criteria.

### Scenario and tool builders

> A scenario pack is a reusable contract for roles, tools, actions, visibility,
> pressure, and settlement—not a prompt collection.

Call to action: contribute a small deterministic scenario before proposing a
large integration.

## 3. Weekly operating cadence

| Day | Public action | Evidence to retain |
| --- | --- | --- |
| Monday | Share one design decision or failure category | Link to code, test, or replay |
| Wednesday | Publish one successful or rejected run | Fixture/seed, commit, and limitation |
| Friday | Report a release change and ask one concrete community question | Issue, discussion, or PR link |
| Every two weeks | Ship a small release or documentation improvement | Changelog entry and regression result |
| Monthly | Host one replay walkthrough or office hour | Recording, questions, and follow-ups |

One engineering change should produce several durable assets: a changelog
entry, a reproducible trace, a short technical explanation, and (when useful) a
scenario or good-first-issue proposal. Do not manufacture activity by repeating
the same announcement across channels.

## 4. First-contact response rules

- **Security report:** move to the private channel in `SECURITY.md`; do not
  discuss exploitable details in a public issue.
- **Install or reproducibility failure:** acknowledge within 48 hours and ask
  for OS, Python version, commit, command, and the smallest trace.
- **Scenario proposal:** ask for authoritative outcome, state transitions,
  tools, and acceptance checks before discussing implementation.
- **Commercial request:** use the pilot form or email
  `tonyhyworld@gmail.com`; do not promise a date, ranking, or business result
  before scope and evidence are agreed.

Close the loop publicly with a short status note when a report becomes a fix,
documentation change, or intentionally rejected proposal.

## 5. What counts as a qualified lead

Track a lead only when at least three of these are true:

- an existing Agent or funded near-term project exists;
- the business outcome can be checked by rules, data, or an authorized system;
- the team can describe the cost of a wrong action;
- a decision-maker or technical owner is involved;
- tools, fixtures, or a safe test environment can be provided;
- the work could start within 90 days.

Conceptual questions remain welcome in the community, but they are not counted
as pipeline. Record source, date, scenario, next action, and consent before
putting a conversation in a private sales tracker.

Use the [qualified lead log template](QUALIFIED_LEAD_LOG_TEMPLATE.md) for the
minimum fields, stage definitions, and monthly aggregate report. Keep the
record private and publish only approved totals.

## 6. Minimum operating metrics

Report these monthly; do not use stars alone as the success metric:

- first successful Quickstart runs and median time to first run;
- returning external runners and third-party scenario/adapter contributions;
- install/documentation failures by category and time to resolution;
- qualified pilot requests, proposals sent, and paid engagements;
- public replay examples with fixture, seed, commit, and known limitations.

The project is making progress when an outside developer can run, challenge,
and extend a world—and when a qualified team can buy a clearly bounded,
evidence-linked evaluation without the open-source runtime being weakened.

## 7. Safety and credibility checklist

Before publishing a case or metric, verify:

- the exact commit, fixture, seed, model/provider, and tool versions are named;
- simulated, synthetic, historical, and live data are clearly distinguished;
- failures and rejected actions are not omitted;
- no private data, credentials, customer identity, or restricted asset is
  exposed;
- financial examples state that they are simulations and not investment advice;
- commercial copy describes scope and evidence, never a guaranteed outcome.
