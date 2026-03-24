# Roadmap

## Current Snapshot

- Stage 1 foundation work is complete.
- Stage 2 browser layer now has a real Playwright-backed implementation.
- Stage 4 agent loop now has a real typed multi-step planner/runtime implementation.
- The next major gaps are better pause/resume UX, broader reusable skills, and more runtime hardening on dynamic pages.

## Stage 1: Foundation Skeleton

Deliverables:

- repository layout with runtime, browser, skills, safety, CLI, and tests;
- architecture, runtime, skills, rules, and roadmap documentation;
- typed runtime models and baseline contracts.

Risks:

- creating empty placeholders without useful contracts;
- over-engineering before real browser integration.

Readiness criteria:

- repository structure is coherent;
- code and docs agree on boundaries;
- the CLI and tests run in bootstrap mode.

## Stage 2: Browser Layer

Deliverables:

- Playwright-backed browser engine;
- compact page snapshot extraction;
- navigation and interaction primitives;
- selector strategy helpers;
- trace-ready browser results and optional screenshot artifacts.

Risks:

- brittle selectors;
- hidden browser-specific behavior leaking into runtime logic;
- insufficient observability for browser failures.

Readiness criteria:

- the browser engine can start, navigate, observe, click, and type through typed methods;
- failures are surfaced as structured results;
- trace data is produced for browser actions.

Status:

- delivered in the current repository state.

## Stage 3: Skill Registry

Deliverables:

- default skill bootstrap;
- validated input and output contracts;
- clear mapping from agent action to skill invocation.

Risks:

- too many skills too early;
- weak contracts that allow ambiguous execution;
- accidental scenario-specific skill design.

Readiness criteria:

- skills are discoverable through the registry;
- duplicate registrations are prevented;
- default runtime skills cover MVP observation, navigation, interaction, safety, and reporting.

Status:

- foundation-complete; the current runtime now executes the existing skill registry against a real browser adapter.

## Stage 4: Agent Loop

Deliverables:

- real planner integration;
- repeated observe/reason/execute cycle;
- runtime stop conditions and progress tracking.

Risks:

- planner output drift from typed contracts;
- infinite loops with no progress;
- poor distinction between thought and action.

Readiness criteria:

- the loop can execute multiple steps safely;
- planner output is parsed and validated;
- the runtime can explain why it chose each action.

Status:

- delivered in the current repository state.

## Stage 5: Security Layer

Deliverables:

- explicit action risk classification;
- confirmation workflow for destructive actions;
- audit-friendly logs for sensitive operations.

Risks:

- incomplete destructive-action coverage;
- confirmation logic coupled to CLI only;
- unsafe defaults.

Readiness criteria:

- destructive actions cannot execute without confirmation;
- confirmation requests are human-readable and typed;
- the runtime reports blocked or deferred actions clearly.

Status:

- core flow delivered in the current repository state; resume UX is still partial.

## Stage 6: Demo Scenarios

Deliverables:

- scenario validation for inbox cleanup, food ordering, and job workflows;
- demo scripts and operator guidance;
- scenario-level readiness notes and known gaps.

Risks:

- accidentally encoding scenario-specific logic into the core runtime;
- poor handling of login, captchas, or dynamic site states;
- demo instability caused by external sites.

Readiness criteria:

- demos prove the general architecture rather than a hidden scripted flow;
- the agent can pause for confirmation or clarification naturally;
- scenario notes document assumptions and limits.

Current note:

- the core runtime now supports multi-step planning and pause states without task-specific code, but scenario depth still depends on the current generic skill set.

## Stage 7: Polishing

Deliverables:

- better developer experience;
- improved tracing and reporting;
- broader tests and cleanup of rough edges.

Risks:

- spending time on polish before runtime reliability exists;
- adding nice-looking output without improving observability.

Readiness criteria:

- setup and execution are smooth for new contributors;
- reports are clear enough for demos and debugging;
- the codebase remains small, readable, and modular.
