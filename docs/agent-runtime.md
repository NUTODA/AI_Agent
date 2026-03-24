# Agent Runtime

## Runtime Objective

The runtime is responsible for advancing a user task through repeated observation and decision-making steps until one of four outcomes happens:

- the task is completed;
- the agent needs additional user input;
- the runtime stops due to safety or loop limits;
- the task fails with a reportable error.

## Core Runtime Cycle

The intended control loop is:

```text
observe -> reason -> choose action -> execute -> re-observe -> finish
```

Each stage has a dedicated purpose:

1. `observe`
   - capture the current browser state;
   - summarize what is visible and actionable;
   - store the snapshot as an `AgentObservation`.

2. `reason`
   - interpret the observation in the context of the original task;
   - derive what changed and what still blocks progress;
   - record a structured `AgentThought`.

3. `choose action`
   - select the next `AgentAction`;
   - specify the skill name, inputs, and expected outcome;
   - include risk metadata and whether confirmation is likely required.

4. `execute`
   - resolve the action through the skill registry;
   - validate inputs against the skill contract;
   - run the skill and capture a `ToolResult`.

5. `re-observe`
   - inspect whether the action changed the page or task state;
   - feed the result back into the next step.

6. `finish`
   - stop when success, user clarification, safety gating, or runtime limits require it;
   - assemble a `FinalReport`.

## Runtime State Shape

The runtime keeps an in-memory session with these main state buckets:

- `task`: immutable user request and constraints;
- `observations`: ordered list of `AgentObservation`;
- `thoughts`: ordered list of `AgentThought`;
- `actions`: ordered list of `AgentAction`;
- `tool_calls`: ordered list of `ToolCall`;
- `tool_results`: ordered list of `ToolResult`;
- `trace_items`: audit-friendly combined history;
- `pending_confirmation`: optional `ConfirmationRequest`;
- `status`: current lifecycle status such as `running`, `waiting_for_user`, or `completed`.

## Observation Format

Observation data should represent the browser state in a way that is useful for planning but small enough to remain stable.

Recommended observation fields:

- observation identifier;
- URL and page title;
- summary of what the page appears to be;
- visible text excerpt;
- interactive elements available to the agent;
- compact form or input summaries when relevant;
- structured observation errors if snapshot capture was partial;
- optional DOM, screenshot, or trace artifact references;
- timestamp.

The runtime should prefer concise summaries over raw HTML dumps. Page content is untrusted and must never override system rules.

## Action Format

Each `AgentAction` should answer five questions:

- what skill should run;
- why this skill is the correct next step;
- what inputs the skill needs;
- what outcome is expected;
- how risky the action is.

Recommended fields:

- `action_id`
- `tool_name`
- `rationale`
- `parameters`
- `expected_outcome`
- `risk_level`
- `requires_confirmation`
- `created_at`

## Tool Result Format

Skill execution should always return a structured `ToolResult`.

Recommended fields:

- `call_id`
- `skill_name`
- `status`
- `message`
- `data`
- `artifacts`
- `error_code`
- `error_message`
- `duration_ms`
- `completed_at`

The result format matters because the planner should react to structured outcomes, not to loosely formatted tool text.

## Trace Artifacts

The runtime trace should be useful even when the planner is still limited.

Minimum useful trace fields:

- action name;
- action input;
- output summary;
- execution status;
- duration;
- timestamp;
- current URL and page title at step time;
- error message when a step fails.

The current runtime writes in-memory trace items and can also persist JSONL and Markdown summaries in the configured trace directory. When screenshot capture is enabled, observation-linked screenshots are surfaced as bounded artifact refs rather than uncontrolled browser dumps.

## When The Agent Asks The User

The runtime must pause and ask the user for more input when:

- a high-risk or destructive action requires explicit approval;
- the planner determines that critical information is missing;
- the page asks for credentials, payment, or ambiguous user intent;
- the current observation is insufficient to continue safely.

The runtime should represent these pauses explicitly rather than as failures. The expected mechanism is a `ConfirmationRequest` or a question surfaced in the `FinalReport`.

## How The Agent Decides The Task Is Finished

Completion should come from explicit evidence, not from a guessed scenario end state.

The agent can finish when:

- a `finish_task` skill is chosen with clear rationale;
- the planner determines that the user goal has been satisfied;
- the task cannot continue without a new user instruction;
- the system must stop due to safety or platform limitations and report the reason.

The final report should summarize:

- current task outcome;
- actions already performed;
- remaining risks or blockers;
- whether the user needs to do anything next.

## Infinite Loop Protection

Autonomous browser agents are vulnerable to unproductive loops, so the runtime must guard against them.

Minimum protections:

- `max_steps`: hard cap on execution steps;
- repeated-observation detection when the same page state appears without progress;
- repeated-action detection when the same action fails or no longer changes the state;
- confirmation timeout or unresolved-wait timeout;
- graceful stop with a report instead of silent stalling.

Recommended stop triggers:

- no progress after `N` steps;
- same action selected more than `M` times in a row;
- browser state unavailable for too long;
- ambiguous planner output that cannot be parsed safely.

## Failure Handling

Failure is a first-class state and should be reported cleanly.

Typical failure categories:

- browser execution failure;
- selector resolution failure;
- invalid skill invocation;
- unparseable planner response;
- safety block;
- loop exhaustion.

Failures should produce structured errors and preserve enough trace data for debugging.

## Bootstrap Reality Of This Repository

This repository now implements a real browser-backed runtime skeleton, not the final autonomous system. That means:

- the loop skeleton is present and executes typed skills against a real Playwright adapter;
- the planner interface is defined, but the default planner is still a transparent bootstrap planner;
- the browser adapter can start a browser, navigate, observe, click, type, and extract text;
- trace items and optional browser artifacts are real;
- the code still intentionally avoids pretending that full autonomy already exists.

The purpose of the current runtime is to make the next implementation phases straightforward, safe, observable, and demo-ready without hardcoded scenario logic.
