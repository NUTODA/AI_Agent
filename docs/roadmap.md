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

**Status: COMPLETED** - The system is now demo-ready with comprehensive capabilities.

### Delivered:

**CLI Resume Flow:**
- Full interactive support for `waiting_for_confirmation` state
- User input handling for `waiting_for_user` questions
- Loop continuation after user responses
- Honest UX with no auto-confirmations or fake completions

**Extended Generic Skills (6 new atomic capabilities):**
- `select_option` - Dropdown/select element interaction
- `scroll_viewport` - Page and element scrolling
- `press_key` - Keyboard key presses
- `wait_for_element` - Conditional element waiting
- `upload_file` - File input handling
- `inspect_dialog` - Dialog/alert detection

**Controlled Demo Environment:**
- `inbox_demo.html` - Email management (spam/important marking, filtering)
- `food_demo.html` - Restaurant ordering (menu, cart, checkout flow)
- `jobs_demo.html` - Job board (filtering, application forms)
- `demos/server.py` - HTTP server for demo pages
- All demos use `data-testid` attributes and work without external dependencies

**Enhanced Trace and Reporting:**
- Demo-readable markdown trace output
- Improved final report with status indicators and visual formatting
- Clear step summaries, rationale, and progress tracking
- Better structured output for human consumption

**Documentation:**
- `docs/demo.md` - Comprehensive demo guide with example tasks
- Updated `README.md` with demo instructions
- `demos/README.md` - Demo pages documentation
- Updated `docs/skills.md` with new skill documentation

### What Was Avoided (Per Constraints):

- No task-specific scenarios in runtime logic
- No site-specific `if/else` logic
- No encoded scenario-specific knowledge in planner
- No brittle tests on external sites
- All demos work entirely locally without internet access

### Current State:

The agent can now:
1. Execute generic browser interactions across diverse page types
2. Pause for user confirmation on risky actions
3. Ask the user clarifying questions when needed
4. Produce clear, demo-ready trace and report output
5. Demonstrate real planner-based decision making

The demos prove the general architecture rather than hidden scripted flows.

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
