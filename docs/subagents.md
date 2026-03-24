# Development Subagents

This document defines the engineering roles used to develop the browser agent foundation and the next runtime phases. These are development roles, not runtime task-specific branches.

## Role Set

### Architect

Goal:
- define the system shape, module boundaries, and long-term extensibility.

Responsibilities:
- own the high-level architecture;
- maintain documentation coherence across runtime, skills, safety, and browser layers;
- prevent monolithic design drift.

Inputs:
- product goals;
- system constraints;
- scenario requirements;
- engineering trade-offs.

Outputs:
- architecture decisions;
- module boundaries;
- roadmap and design notes;
- review guidance for new subsystems.

Definition of done:
- component responsibilities are explicit;
- boundaries are stable enough for implementation;
- no task-specific flow is embedded into the architecture.

### Runtime Engineer

Goal:
- implement the agent loop and session state management.

Responsibilities:
- runtime orchestration;
- session lifecycle;
- trace integration;
- step guards and stop conditions.

Inputs:
- typed models;
- planner contract;
- skill registry;
- safety policy.

Outputs:
- runtime loop code;
- session storage abstractions;
- final report assembly;
- step-limit and retry protections.

Definition of done:
- the loop can safely advance one step at a time;
- runtime state is inspectable and typed;
- task flow is driven by observations and tool results.

### Browser Engineer

Goal:
- build the browser automation adapter behind stable interfaces.

Responsibilities:
- Playwright integration;
- navigation and interaction primitives;
- page snapshot generation;
- selector strategy support.

Inputs:
- browser engine contract;
- page state schema;
- skill requirements.

Outputs:
- browser adapter implementation;
- robust atomic browser operations;
- browser-facing error mapping.

Definition of done:
- browser actions are exposed as typed primitives;
- page state is available without leaking Playwright internals across the system;
- failures are deterministic and traceable.

### Prompt Engineer

Goal:
- shape the planner prompts and structured response contract.

Responsibilities:
- planner prompt composition;
- output schema alignment;
- prompt hardening against page-content injection.

Inputs:
- runtime model contracts;
- observation format;
- safety rules;
- planner interface.

Outputs:
- system prompt sections;
- planner output contract;
- parser expectations and examples.

Definition of done:
- planner outputs can be validated against typed models;
- prompts do not encourage hardcoded task-specific execution;
- untrusted page content is properly framed.

### Safety Engineer

Goal:
- define and implement the risk model and confirmation workflow.

Responsibilities:
- action risk classification;
- destructive-action detection;
- confirmation gating;
- auditability of sensitive decisions.

Inputs:
- action schema;
- runtime rules;
- operator experience requirements.

Outputs:
- risk levels;
- guardrail policies;
- confirmation request format;
- test cases for sensitive flows.

Definition of done:
- destructive actions cannot bypass confirmation;
- safety decisions are explicit and documented;
- blocked actions are reportable.

### DX / Demo Engineer

Goal:
- make the system easy to run, inspect, and present.

Responsibilities:
- CLI UX;
- local setup flow;
- human-readable progress and final output;
- demo scenarios and supporting notes.

Inputs:
- runtime status model;
- architecture documents;
- likely demo flows.

Outputs:
- polished CLI behaviors;
- setup instructions;
- demo-ready session summaries;
- scenario notes and operator guidance.

Definition of done:
- a new developer can install and run the project quickly;
- the CLI makes system status understandable;
- the demo story is honest about current implementation depth.

### QA / Scenario Engineer

Goal:
- validate correctness of contracts and scenario readiness.

Responsibilities:
- smoke tests;
- model contract tests;
- registry tests;
- scenario gap analysis for inbox, food, and job flows.

Inputs:
- code contracts;
- rules;
- roadmap;
- product scenarios.

Outputs:
- test cases;
- risk notes;
- reproducible checks for regressions.

Definition of done:
- critical contracts are covered by tests;
- obvious regressions are caught early;
- scenario-specific assumptions are surfaced before implementation.

## Collaboration Model

The development roles collaborate through typed contracts and documents rather than implicit assumptions:

- the Architect defines seams;
- the Runtime Engineer consumes those seams;
- the Browser Engineer implements the browser-facing side;
- the Prompt Engineer implements the planner-facing side;
- the Safety Engineer guards risky actions;
- the DX / Demo Engineer shapes usability;
- the QA / Scenario Engineer verifies the foundation and scenario readiness.

This structure keeps the project scalable without turning it into an over-abstracted framework.
