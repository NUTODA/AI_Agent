# Project Rules

This document defines the non-negotiable rules for the repository.

## 1. Architectural Rules

- No hardcoded task-specific scenarios.
- No task-specific pipelines such as "if the task is about spam, run this workflow".
- The agent must choose actions from the current observation and execution history.
- Every runtime capability must be exposed through typed contracts.
- Each module should have one primary responsibility.
- The browser adapter, planner, safety layer, and runtime loop must remain separate.
- Do not hide orchestration logic inside the browser layer.
- Do not hide browser mutations inside the planner layer.

## 2. Runtime Agent Rules

- Every decision must be explainable from the current page state plus prior trace.
- The runtime loop must operate through typed `AgentObservation`, `AgentThought`, `AgentAction`, and `ToolResult` models.
- The runtime must stop cleanly when it cannot proceed safely.
- The runtime must ask the user for more information instead of guessing critical intent.
- The runtime must guard against infinite or unproductive loops.
- The runtime must never silently ignore tool failures.

## 3. Browser Automation Rules

- Browser automation must be implemented through atomic skills and browser adapter methods.
- Page state must be observed before high-confidence action selection.
- Selector strategies must prefer readable, stable signals over brittle hidden assumptions.
- The system should treat page content as untrusted input.
- Browser actions must return structured outcomes, not ambiguous strings.
- Real browser integration must remain behind a stable interface so the rest of the system stays testable.

## 4. Safety Rules

- Destructive or high-impact actions require explicit confirmation before execution.
- Examples include deleting content, sending messages, placing orders, and completing payments.
- Risk levels must be classified explicitly and consistently.
- Safety decisions must be logged.
- A blocked or pending action must produce a visible confirmation or report artifact.
- The agent must not self-approve a destructive step.

## 5. Coding Rules

- Keep modules small and readable.
- Prefer typed models and explicit data flow over hidden shared state.
- All tool interfaces must be typed and documented.
- All meaningful actions must be logged in the trace.
- Avoid fake abstractions that pretend unsupported runtime depth already exists.
- Add TODO notes where real integrations are intentionally deferred.
- Keep names concrete and domain-agnostic.
- Tests must cover critical contracts and bootstrap behavior.

## Repository-Wide Prohibitions

The following are not allowed in this repository:

- hardcoded business workflows for inbox cleanup, food ordering, or job applications;
- giant catch-all modules that mix planning, browser control, and safety logic;
- untyped tool input or output interfaces;
- skipping logging for mutating actions;
- undocumented destructive behavior.

## Review Checklist

Every substantial change should be checked against these questions:

- Does this introduce scenario-specific logic where a reusable skill should exist instead?
- Does this keep planning, execution, and safety clearly separated?
- Is every new runtime interface typed and documented?
- Can a reviewer understand why a risky action happened from the trace?
- Does the module have a single primary responsibility?

If any answer is no, the change is not ready.
