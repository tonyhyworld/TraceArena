# AI World: A Scenario-Pack Framework for Verifiable Multi-Agent Problem Solving

## Abstract

Large language models are increasingly used as agents, yet most agent systems are built around one-shot answers or fixed workflows. This makes it difficult for domain experts to encode their own constraints, for multiple agents to explore competing strategies, and for users to verify how an outcome was produced. We present **AI World**, implemented by the open-source **TraceArena** runtime, a scenario-pack framework for turning domain problems into executable worlds. A scenario pack declares goals, roles, resources, rules, tools, external data, termination conditions, settlement logic, and presentation metadata. Within a loaded world, multiple agents execute a bounded observation--planning--action--feedback loop. A world kernel validates actions and advances state; a settlement runtime computes outcomes from simulation rules, external facts, deterministic verifiers, or hybrid combinations; and an event ledger preserves an auditable trace that can be replayed visually. The contribution is a reusable interface between domain expertise and agent execution: experts define the world, while the runtime provides orchestration, verification, and observability. We describe the architecture, execution protocol, scenario-pack design, and an evaluation methodology for comparing agents and strategies under identical constraints. The system is released with public examples and reproducibility guidance.

**Keywords:** multi-agent systems, agent environments, scenario packs, agent loop, verifiable execution, AI simulation, decision traceability, visual replay

## 1. Introduction

An agent that produces a plausible paragraph is not necessarily an agent that can solve a real problem. Real decisions unfold over time, consume resources, face permissions and constraints, interact with other decision makers, and produce consequences that may only become visible later. Domain experts also need to express what counts as a legal action and what counts as a good result. These requirements are difficult to satisfy with a single prompt, a one-shot benchmark, or a fixed workflow engine.

AI World addresses this gap by providing an executable world abstraction for domain experts. A world is defined by a scenario pack rather than hard-coded into the operating system. The expert declares the domain objective, participants, resources, rules, tools, evidence sources, and settlement criteria. Multiple agents can then act in the same world, compete or cooperate, receive feedback, revise plans, and continue until a goal or termination condition is reached. The runtime makes the entire chain visible: what an agent observed, what it decided, what action it attempted, how the world responded, and how the final result was settled.

Our central thesis is:

> A domain expert should be able to turn a real problem into a runnable world without first building a complete agent platform, while every important action remains verifiable and replayable.

This paper makes four contributions:

1. A scenario-pack abstraction that separates domain definitions from the general-purpose runtime.
2. A multi-agent execution loop with explicit world validation, feedback, bounded retries, and termination.
3. A settlement and trace model that supports simulated, external-reality, deterministic-verifier, and hybrid worlds.
4. A visual presentation path that converts verified facts into human-readable, replayable decision stories without making the narrator authoritative over the world state.

## 2. Design Goals and Non-Goals

### 2.1 Goals

AI World is designed to:

- lower the barrier for domain experts to build agent environments;
- support continuous action rather than one-shot completion;
- allow multiple agents and strategies to be compared under the same world constraints;
- keep world state, actions, events, settlement, and traces auditable;
- work with different LLM providers and internal or external tools;
- make complex execution understandable through live visualization and replay.

### 2.2 Non-goals

AI World is not a claim that an LLM is correct, safe, or autonomous in every setting. It is not a replacement for production controls, regulatory review, human authorization, or physical safety systems. It is also not primarily a dataset marketplace. Trajectories and evaluation records are useful outputs, but the product's primary value is providing a reusable world framework for solving and inspecting domain problems.

## 3. System Model

Let a scenario pack define a world (W) with state (s_t), agents (A), actions (U), tools (T), observations (O), and a settlement function (S). At step (t), agent (a_i) receives an authorized observation (o_{i,t} = V_i(s_t)), where (V_i) is the visibility policy for that role. The agent produces a plan and a candidate action (u_{i,t}). The world kernel applies a legality function (L(u_{i,t}, s_t)). If the action is legal, the transition function produces (s_{t+1}) and a world event (e_t); otherwise the kernel returns a structured failure that can be used by the agent for reflection.

The run ends when a goal predicate, a termination predicate, or a resource/time budget is reached. The settlement runtime computes (r = S(s_{0:T}, e_{0:T}, x)), where (x) may include external facts such as market prices or deterministic verifier outputs. The trace ledger stores observations, model decisions, tool calls, actions, failures, events, settlement records, and presentation facts.

## 4. Architecture

```text
Scenario Pack
  goals / roles / resources / rules / tools / settlement / presentation
                              |
                              v
TraceArena Runtime
  loader -> scheduler -> agent harness -> world kernel -> event ledger
                                      |                 |
                                      v                 v
                               LLM providers       settlement runtime
                                      \                 /
                                       v               v
                                  verified facts and traces
                                             |
                                             v
                              director -> renderer -> replay / console
```

### 4.1 Scenario-pack layer

The scenario pack is the extension boundary. It declares the world vocabulary, roles, actions, resources, tools, clocks, goals, settlement manifest, and rendering bindings. The runtime does not assume that every world has the same action schema or reward function.

### 4.2 Agent harness

The harness converts an LLM into a bounded actor. It assembles role prompts and world observations, exposes approved capabilities, invokes tools, parses structured actions, collects feedback, and controls retries and budgets. A failed action is not silently treated as success; it becomes an explicit feedback event.

### 4.3 World kernel

The world kernel is authoritative for state transitions. It enforces permissions, action schemas, resource availability, visibility, phase rules, and event creation. This separation prevents a language model or a narrative component from directly declaring its own outcome.

### 4.4 Settlement runtime

Different domains require different sources of truth. AI World supports four settlement modes:

| Mode | Source of outcome | Example |
|---|---|---|
| Simulation | Scenario rules | social influence, resource changes |
| External reality | External data or service | observed prices, external task result |
| Deterministic verifier | Reproducible checker | tests, schemas, exact graders |
| Hybrid | External facts plus deterministic rules | market price plus portfolio ledger |

### 4.5 Trace ledger and replay

The ledger records the facts needed to explain a run. A run can be inspected as a timeline or replayed from fixtures. This supports debugging, model comparison, expert review, and later experimental analysis.

### 4.6 Director and renderer

The director translates verified events and settlement records into audience-facing descriptions and rendering commands. It may explain why an action mattered, but it cannot replace the world kernel or rewrite the settlement record. This design separates narrative clarity from factual authority.

## 5. Agent Loop Protocol

The canonical loop is:

```text
observe -> plan -> select capability -> execute -> validate
    ^                                         |
    |------------- feedback / reflect --------|
```

The loop is bounded by explicit policies:

- maximum steps or ticks;
- token and tool budgets;
- action permissions;
- world termination conditions;
- retry and failure policies;
- human approval gates where required.

This allows “continuous execution” to mean sustained goal-directed work rather than an unbounded or uncontrolled process.

## 6. Building a Domain Scenario Pack

A domain team can create a scenario pack in five stages:

1. **State the problem.** Define a measurable objective and what constitutes completion.
2. **Model the world.** Identify actors, resources, time, information, constraints, and external dependencies.
3. **Declare actions and tools.** Specify which actions are legal, which tools each role can use, and which side effects require authorization.
4. **Define settlement.** Select simulation rules, an external fact source, a deterministic verifier, or a hybrid.
5. **Define presentation.** Choose the events, metrics, decisions, and comparisons that experts and viewers need to see.

The resulting pack can be run repeatedly with different models, prompts, seeds, role policies, or tool configurations while keeping the world definition fixed.

## 7. Applications

AI World is domain-neutral. Public examples and target applications include:

- **Capital markets:** compare research and portfolio strategies under market data, risk budgets, and trading rules.
- **City governance:** test transport, emergency response, and resource allocation policies with multiple stakeholders.
- **Drug discovery:** plan experiments under budget, evidence, and trial-stage constraints.
- **Logistics:** coordinate orders, inventory, routes, weather, and disruptions.
- **Manufacturing and robotics:** schedule production, handle faults, and respect safety boundaries in a controlled world.
- **Education and research:** create reproducible experimental worlds for teaching, hypothesis testing, and model evaluation.

## 8. Evaluation Methodology

This paper intentionally distinguishes implemented capabilities from measured results. A reproducible evaluation should include:

### 8.1 Research questions

- Does explicit world validation reduce illegal or impossible actions?
- Does multi-agent competition discover different and better paths than a single agent?
- Does a feedback-and-reflection loop improve recovery after failure?
- Does visual replay improve expert ability to identify why a result occurred?
- How stable are results across models, seeds, and repeated runs?

### 8.2 Conditions

Compare at least:

1. single agent vs. multiple agents;
2. one-shot response vs. bounded Agent Loop;
3. no tools vs. approved tools;
4. no reflection vs. feedback-triggered reflection;
5. narrative-only judgment vs. authoritative settlement.

### 8.3 Metrics

Recommended metrics include goal completion, settlement score, resource cost, rule-violation rate, recovery rate after failed actions, number of tool calls, run-to-run variance, trace completeness, and expert review time.

All reported numbers should include the scenario-pack version, runtime commit, model and provider, prompts, tool configuration, budget, seed, hardware, and raw replay artifacts.

## 9. Limitations and Risks

The quality of a world depends on the quality of its rules, data, tools, and settlement design. A poorly specified scenario can produce precise-looking but invalid conclusions. External data can be delayed, unavailable, or subject to licensing constraints. LLM behavior remains probabilistic and can be sensitive to prompts and provider changes. For high-impact domains, AI World should be used for analysis, simulation, and decision support with appropriate human oversight, not as an unreviewed authority.

## 10. Open-source Release

TraceArena is released as the open-source runtime for AI World. The repository includes a scenario-pack template, runnable examples, local replay paths, deployment documentation, and contribution guidance. The community can extend the system by contributing domain packs rather than modifying the core runtime for every new use case.

## 11. Conclusion

AI World provides a practical interface between domain expertise and multi-agent execution. It allows a professional team to define a world, load it into a general runtime, let agents act and compete under explicit constraints, and inspect the path to the outcome. The central object is not a conversational answer but a verifiable run: a sequence of observations, decisions, actions, feedback, events, and settlement records that can be watched, replayed, compared, and improved.

The long-term vision is an ecosystem of domain-specific AI Worlds built on a shared open-source runtime. In this model, a financial expert, a city planner, a medical researcher, or a logistics operator can contribute a world in which AI works on the problems that matter to that field.

## References

[1] Yao et al. ReAct: Synergizing Reasoning and Acting in Language Models. 2023.  
[2] Wu et al. AutoGen: Enabling Next-Gen LLM Applications. 2023.  
[3] Wang et al. Voyager: An Open-Ended Embodied Agent with Large Language Models. 2023.  
[4] Zhou et al. WebArena: A Realistic Web Environment for Building Autonomous Agents. 2024.  
[5] TraceArena contributors. TraceArena: Open-source AI World runtime and scenario packs. 2026. https://github.com/tonyhyworld/TraceArena
