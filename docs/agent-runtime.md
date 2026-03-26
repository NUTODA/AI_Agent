# Agent Runtime

## Runtime Objective

The runtime is responsible for advancing a user task through repeated observation and decision-making steps until one of four outcomes happens:

- the task is completed;
- the agent needs additional user input;
- the runtime stops due to safety or loop limits;
- the task fails with a reportable error.

## Core Runtime Cycle

The runtime now implements the following control loop:

```text
observe -> plan -> maybe confirm/ask user -> execute -> re-observe -> finish
```

Each stage has a dedicated purpose:

1. `observe`
   - capture the current browser state;
   - summarize what is visible and actionable;
   - store the snapshot as an `AgentObservation`.

2. `plan`
   - build a typed planner context from the task, latest observation, recent trace summary, available skills, and session state;
   - request one structured planner decision from the configured LLM provider;
   - validate the response through the strict parser before the runtime touches any skill.

3. `maybe confirm / ask user`
   - pause if the planner asks a blocking question;
   - pause if the planner or guardrails require confirmation for a risky action;
   - store the pending state explicitly in the session.

4. `execute`
   - resolve the action through the skill registry;
   - validate inputs against the skill contract;
   - run the skill and capture a `ToolResult`.

5. `re-observe`
   - inspect whether the action changed the page or task state;
   - feed the result back into the next step;
   - update deterministic progress signals and loop-protection counters.

6. `finish`
   - stop when success, user clarification, safety gating, or runtime limits require it;
   - assemble a `FinalReport`.

## Runtime State Shape

The runtime keeps an in-memory session with these main state buckets:

- `task`: immutable user request and constraints;
- `step_count`: planner-step counter;
- `no_progress_streak`: deterministic stagnation counter;
- `observations`: ordered list of `AgentObservation`;
- `thoughts`: ordered list of `AgentThought`;
- `actions`: ordered list of `AgentAction`;
- `tool_calls`: ordered list of `ToolCall`;
- `tool_results`: ordered list of `ToolResult`;
- `trace_items`: audit-friendly combined history;
- `pending_confirmation`: optional `ConfirmationRequest`;
- `pending_action`: optional risky action waiting for approval;
- `pending_user_question`: optional blocking question from the planner;
- `user_responses`: stored answers for resume flows;
- `execution_history_summary`: compact planner-facing trace summary;
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

Current planner decision fields:

- `decision_type`
- `rationale`
- `chosen_skill`
- `skill_input`
- `expected_outcome`
- `risk_level`
- `destructive`
- `completion_confidence`
- `progress_assessment`
- `requires_confirmation`
- `user_question`
- `finish_reason`
- `failure_reason`

The runtime converts acting planner decisions into typed `AgentAction` instances only after validation succeeds.

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

The runtime trace should stay useful even when the planner is wrong or blocked.

Minimum useful trace fields:

- observation summary;
- planner decision type;
- rationale summary;
- action name;
- action input;
- output summary;
- execution status;
- progress outcome;
- state transition;
- duration;
- timestamp;
- current URL and page title at step time;
- error message when a step fails.

The current runtime writes in-memory trace items and can also persist JSONL and Markdown summaries in the configured trace directory. When screenshot capture is enabled, observation-linked screenshots are surfaced as bounded artifact refs rather than uncontrolled browser dumps.

## When The Agent Asks The User

The runtime pauses and asks the user for more input when:

- a high-risk or destructive action requires explicit approval;
- the planner determines that critical information is missing;
- the page asks for credentials, payment, or ambiguous user intent;
- the current observation is insufficient to continue safely.

The runtime represents these pauses explicitly rather than as hidden failures. The current contracts support internal resume entrypoints for:

- continue after confirmation approval or rejection;
- continue after a user answer to a pending question.

Full conversational CLI resume is still a later stage.

## How The Agent Decides The Task Is Finished

Completion should come from explicit evidence, not from a guessed scenario end state.

The agent can finish when:

- the planner emits a `finish` decision with clear rationale and enough evidence;
- the runtime turns that decision into the typed `finish_task` skill;
- the task cannot continue without a new user instruction;
- the system must stop due to safety or platform limitations and report the reason.

The final report should summarize:

- current task outcome;
- actions already performed;
- remaining risks or blockers;
- whether the user needs to do anything next.

## Infinite Loop Protection

Autonomous browser agents are vulnerable to unproductive loops, so the runtime must guard against them.

Current protections:

- `max_steps`: hard cap on execution steps (default **80**, overridable via `BROWSER_AGENT_MAX_STEPS` / `--max-steps`);
- `max_no_progress_steps`: stop after this many consecutive steps with no observable progress (default **10**);
- deterministic progress detection from URL/title/text/interactive-element changes;
- repeated-action detection when the same action is selected without progress;
- planner-failure degradation into a controlled failure state;
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

Failures produce structured errors and preserve enough trace data for debugging.

## Current Reality Of This Repository

This repository now implements a real typed multi-step agent loop. That means:

- the runtime performs a real observation before planner decisions;
- the planner produces a strict structured decision instead of free-form text;
- malformed planner output degrades into a controlled failure instead of a crash;
- the browser adapter can start a browser, navigate, observe, click, type, and extract text;
- risky actions pause in `waiting_for_confirmation`;
- missing information pauses in `waiting_for_user`;
- trace items and optional browser artifacts are real;
- the code still intentionally avoids pretending that unrestricted autonomy already exists.

Remaining limitations:

- the CLI does not yet provide a full interactive resume flow after pauses;
- persistence is still limited to the current process plus trace artifacts;
- only one provider adapter is currently implemented;
- the runtime still depends on the current reusable skill set and does not invent new capabilities on demand.
