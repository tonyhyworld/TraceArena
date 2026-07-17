# Qualified lead log template

Use this template for private maintainer operations. Do not commit names,
private messages, customer data, credentials, or confidential requirements to
the public repository. Keep the private copy in an access-controlled system;
publish only aggregate counts and links that the other party has approved.

## Qualification rule

Count a lead as **qualified** only when at least three of the following are
confirmed:

- a real Agent workflow or funded near-term project exists;
- the outcome can be checked by rules, data, or an authorized system;
- the cost of an incorrect action is understood;
- a decision-maker or technical owner is participating;
- tools, fixtures, or a safe test environment can be provided;
- work could start within 90 days.

## One-record template

```yaml
lead_id: "YYYY-MM-###"
source: "github_issue|discussion|email|referral|event"
received_at: "YYYY-MM-DD"
consent_to_follow_up: true
workflow_category: ""
qualified: false
qualification_signals: []
decision_owner_role: ""
technical_owner_role: ""
requested_engagement: "pilot|scenario_design|integration|continuous_evaluation|other"
acceptance_criterion: ""
agent_or_model_scope: ""
tool_or_data_scope: ""
deployment_constraint: ""
target_start: ""
estimated_value_band: "RMB 29,800+|to be scoped"
stage: "new|discovery|qualified|proposal|negotiation|won|lost|nurture"
next_action: ""
next_action_due: "YYYY-MM-DD"
owner: ""
evidence_links: []
loss_or_delay_reason: ""
notes_without_sensitive_data: ""
```

## Stage definitions

| Stage | Entry evidence | Exit evidence |
| --- | --- | --- |
| `new` | A person or organization has made a concrete request | Scope questions sent |
| `discovery` | Workflow, agents, and evidence needs are being clarified | Qualification rule evaluated |
| `qualified` | At least three qualification signals are evidenced | Bounded scope and acceptance criterion drafted |
| `proposal` | A written scope and estimate were sent | Customer accepts, rejects, or requests changes |
| `negotiation` | Commercial, data, ownership, and timing terms are being agreed | Signed SOW or explicit no-go |
| `won` | SOW and payment/approval are confirmed | Delivery and acceptance tracked separately |
| `lost` | The opportunity will not proceed now | Reason recorded without confidential detail |
| `nurture` | Not qualified yet but a time-bounded follow-up is appropriate | Re-enter discovery or close |

## Monthly aggregate report

Publish only approved aggregate numbers:

| Month | New requests | Qualified | Proposals | Won | Paid revenue | Median response time | Public evidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| YYYY-MM | 0 | 0 | 0 | 0 | RMB 0 | — | link or `none` |

Never infer revenue from stars, views, downloads, or an unaccepted proposal.
