# Browser Agent Foundation

`browser-agent-foundation` is a Python-first project scaffold for an autonomous browser agent that can accept a natural-language task, operate inside a browser session, and keep running until the task is complete or it needs more input from the user.

The repository now includes a real typed planner layer, a real multi-step runtime loop, and a real Playwright-backed browser stack. The core architectural boundary remains the same: planner -> typed skills -> browser adapter.

## Goals

- Build an LLM-driven browser agent loop that reasons from the current page state.
- Keep runtime skills modular and registry-driven instead of task-specific.
- Enforce human confirmation before destructive or high-risk actions.
- Make the system observable through structured trace items and final reports.
- Keep the codebase easy to extend for scenarios like inbox cleanup, food ordering, and job applications.

## Non-Goals For This Stage

- Shipping a fully autonomous production agent.
- Encoding scenario-specific pipelines such as "if task is spam cleanup, execute X".
- Hiding missing implementation behind fake generic abstractions.
- Building a monolithic runtime in a single module.

## High-Level Architecture

The project is split into small modules with explicit boundaries:

- `cli`: terminal-style entrypoint and operator UX.
- `ui`: optional Rich Agent Console and runtime event types for live terminal UI.
- `runtime`: session state, trace handling, loop orchestration, final reporting.
- `llm`: planner contracts, prompts, and structured parser boundaries.
- `browser`: browser adapter interfaces and page-state models.
- `skills`: registry-driven runtime skills such as observation, navigation, interaction, safety, and reporting.
- `safety`: destructive action classification and confirmation flow.
- `docs`: architecture, runtime, skills, rules, and roadmap documents.

```mermaid
flowchart TD
    UserTask[UserTask] --> CliApp[CLIApp]
    CliApp --> RuntimeSession[RuntimeSession]
    RuntimeSession --> AgentLoop[AgentLoop]
    AgentLoop --> Planner[Planner]
    AgentLoop --> SkillRegistry[SkillRegistry]
    AgentLoop --> SafetyLayer[SafetyLayer]
    SkillRegistry --> BrowserEngine[BrowserEngine]
    AgentLoop --> TraceRecorder[TraceRecorder]
    AgentLoop --> FinalReport[FinalReport]
```

## Repository Layout

```text
docs/                  Architecture, rules, and roadmap
src/browser_agent/     Runtime, browser, safety, skills, CLI, and UI (Rich console)
tests/                 Smoke and contract tests for the foundation
```

## Quick start (pipx)

Requires **Python 3.10+** on your PATH. Install [pipx](https://pypa.github.io/pipx/) first, then:

```bash
pipx install browser-agent-foundation
browser-agent setup
browser-agent doctor
browser-agent demo food --ui
```

- Global config is written to `~/.browser-agent/config.yaml` (API key is never printed after save).
- Demos use **bundled local HTML** and start a small HTTP server on `127.0.0.1` automatically; **no internet** is required for the pages (the LLM still needs your configured API).
- To publish under the name `browser-agent` on PyPI, rename the distribution in `pyproject.toml` and release separately.

Other commands: `browser-agent status`, `browser-agent reset`, `browser-agent --version`.

## Running The Runtime

1. Create a virtual environment.
2. Install the package with development dependencies.
3. Install Playwright browser binaries.
4. Configure the planner (or run `browser-agent setup`).
5. Run the CLI.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m playwright install chromium
browser-agent "Review my inbox for spam"
```

You can also pass flags. The default step cap is **80** (suited to multi-page research); use `--max-steps` for shorter smoke tests:

```bash
browser-agent run --headed --start-url https://example.com --max-steps 12 "Inspect the page"
browser-agent --capture-screenshots --start-url https://example.com --json "Observe the current page"
```

Bare task text is still supported (`browser-agent "task"`) and is treated as `browser-agent run`.

### Agent Console UI (`--ui`)

For a demo-ready **terminal operator console** (Rich live layout), use `--ui`:

```bash
browser-agent --ui --headed --start-url https://example.com "Inspect the page and summarize"
```

On startup you’ll see a short banner (`Starting Agent Console…`), then a live layout. When the run finishes, a **Run summary** panel is printed (suitable for screenshots), plus a one-line outcome and a reminder where trace artifacts live.

**Phases (top bar, color-coded):** `OBSERVE`, `PLAN`, `GUARDRAIL`, `ACT`, `WAITING_CONFIRMATION`, `WAITING_USER`, and terminal `FINISHED` / `FAILED`. A short **human-readable** line explains what the agent is doing (from planner rationale / expected outcome / current skill — never raw chain-of-thought).

**Panels:**

| Area | Contents |
|------|-----------|
| **Top** | Task, status, step counter, model/provider, **phase chip**, narrative line |
| **Left — Status & tokens** | URL/title; model; LLM request count; prompt / completion / total tokens; estimated cost; average LLM latency; duration. Token/cost lines show **(estimated)** when usage is approximate or missing from the provider. |
| **Center — Issue** (when needed) | Red **ERROR** block for tool failures, ambiguous targets, blocked actions, planner failures, or confirmation context |
| **Center — Steps** | Last ~10 steps: step number, **phase**, short reason, humanized skill name (e.g. `Click Element`), target, expected outcome, result, progress |
| **Right — Current state** | Observation snippet, interactive element count, warnings, last decision |
| **Bottom** | Confirmation (`Y`/`N`) or blocking user question + answer prompt (same resume flow as non-UI CLI) |

**Example final summary (illustrative):**

```text
╞════════════ Run summary ════════════╡
RUN COMPLETED

Task: Inspect the page and summarize
Outcome: Completed
Steps: 4
LLM calls: 5
Tokens (total): 12,450
  Prompt: 11,000
  Completion: 1,450
Est. cost: $0.0234
Avg LLM latency: 890 ms
Duration: 02:14

Summary: …

Key actions:
  • Navigate — …
  • Click Element — …

Visited URLs:
  • https://example.com/…

Artifacts (traces & files):
  • traces/session_….md
  • traces/session_….jsonl
```

`--ui` cannot be combined with `--json`.

If the `playwright` shell command is unavailable in your environment, run the browser install step through Python instead:

```bash
python -m playwright install chromium
```

The multi-step planner is not enabled by default. Configure it through environment variables or a `.env` file:

1. Copy `.env.example` to `.env` or `.env.browser-agent`:
   ```bash
   cp .env.example .env.browser-agent
   ```

2. Edit the file and set your API key and provider.

3. Run:
   ```bash
   browser-agent --start-url https://example.com "Inspect the current page"
   ```

### Provider: OpenAI-compatible

```bash
BROWSER_AGENT_PLANNER_ENABLED=true
BROWSER_AGENT_PLANNER_PROVIDER=openai_compatible
BROWSER_AGENT_PLANNER_BASE_URL=https://api.openai.com/v1
BROWSER_AGENT_PLANNER_MODEL=gpt-4o-mini
BROWSER_AGENT_PLANNER_API_KEY=sk-...
```

### Provider: Google Gemini

```bash
BROWSER_AGENT_PLANNER_ENABLED=true
BROWSER_AGENT_PLANNER_PROVIDER=google_compatible
BROWSER_AGENT_PLANNER_BASE_URL=https://generativelanguage.googleapis.com/v1beta
BROWSER_AGENT_PLANNER_MODEL=gemini-flash-latest
BROWSER_AGENT_PLANNER_API_KEY=AIza...
```

- For Google AI Studio, get your API key at https://aistudio.google.com/app/apikey
- The `BASE_URL` can be just the host (e.g. `https://generativelanguage.googleapis.com/v1beta`) — the model ID and `:generateContent` are appended automatically.

If the planner is not configured, the CLI now says so explicitly instead of falling back to fake autonomy.

## Current Status

Current stage: real multi-step planner/runtime integration.

What already exists:

- architecture documents and project rules;
- typed runtime models for the agent loop and tool contracts;
- a strict planner decision contract with structured `act`, `ask_user`, `request_confirmation`, `finish`, and `fail` outcomes;
- a minimal OpenAI-compatible planner provider abstraction plus fake provider support for tests;
- a strict planner parser that validates JSON, skill names, and skill arguments before runtime execution;
- a modular skill system with a default registry;
- a safety layer for confirmation gating;
- a real Playwright-backed browser adapter with lifecycle management;
- real page observation, interactive element extraction, navigation, clicking, typing, and text extraction;
- a real multi-step observe -> plan -> guardrail -> execute -> re-observe loop;
- deterministic progress detection and stagnation protection;
- structured execution trace artifacts with planner decisions, progress outcomes, and optional screenshots;
- smoke, parser, contract, selector, runtime, and local browser integration tests.

What is intentionally not implemented yet:

- full conversational resume UX in the CLI after confirmation or user-question pauses;
- persistent memory beyond the current process and trace artifacts;
- multiple LLM provider adapters beyond the current OpenAI-compatible transport;
- scenario execution depth for inbox, food, or job workflows.

## Demo Reality

The CLI now runs a real multi-step browser session when the planner is configured. The current demo flow is intentionally honest:

- the runtime performs a real observation before each planning step;
- the planner chooses one typed atomic next step at a time;
- the runtime executes only registered skills and re-observes after execution;
- risky actions pause for explicit confirmation;
- blocking ambiguity pauses for a user answer;
- the loop stops with a final report, a confirmation request, or a blocking user question.

This repository still does not claim unrestricted general autonomy. The loop is real, but it remains bounded, typed, safety-gated, and intentionally provider-minimal.

## Key Design Principles

- No hardcoded task-specific pipelines.
- No destructive action without explicit confirmation.
- No large ambiguous modules with mixed responsibilities.
- No undocumented or untyped runtime tool interfaces.
- Every decision should be explainable from observation plus trace history.

## Documentation

- `docs/architecture.md`
- `docs/agent-runtime.md`
- `docs/subagents.md`
- `docs/skills.md`
- `docs/rules.md`
- `docs/roadmap.md`

## Running Controlled Demos

The repository includes controlled demo pages for reproducible testing and demonstrations.

### Packaged command (recommended)

After install, scenarios start the local server automatically:

```bash
browser-agent demo food --ui
browser-agent demo jobs --ui
browser-agent demo spam --ui
```

### Start the Demo Server (development tree)

```bash
python demos/server.py
```

The server will start on port 8765 and print URLs for all demo pages. The same pages are bundled under `src/browser_agent/demos/pages/` for pip installs.

### Available Demos

1. **Inbox Management** (`http://localhost:8765/inbox_demo.html`)
   - Demonstrates email list interaction, spam marking, filtering
   - Shows confirmation flow for destructive actions

2. **Food Ordering** (`http://localhost:8765/food_demo.html`)
   - Demonstrates cart management, form filling, multi-step checkout
   - Shows navigation between different page states

3. **Job Applications** (`http://localhost:8765/jobs_demo.html`)
   - Demonstrates filtering, form submission, file upload
   - Shows modal dialog interactions

### Example CLI Commands for Demos

```bash
# Demo 1: Inbox - mark spam emails
browser-agent --start-url http://localhost:8765/inbox_demo.html \
  "Mark the suspicious emails as spam"

# Demo 2: Food - place an order
browser-agent --start-url http://localhost:8765/food_demo.html \
  "Order a Classic Burger and Soft Drink, then proceed to checkout"

# Demo 3: Jobs - apply for a position
browser-agent --start-url http://localhost:8765/jobs_demo.html \
  "Filter for remote jobs and apply to the Senior Frontend Developer position"
```

### What the Demos Show

- **Generic browser interaction**: All actions use generic skills (click, type, observe, scroll)
- **Planner-based decisions**: The agent observes and plans each step based on current page state
- **Confirmation flow**: Risky actions pause for user approval
- **Interactive resume**: CLI prompts for user input when the agent needs clarification
- **Clear reporting**: Final reports show all steps, actions, and outcomes

See `docs/demo.md` for comprehensive demo documentation.

## Next Steps

The project is now demo-ready with CLI resume flow, expanded generic skills, and controlled demo pages. The remaining work is focused on:

- Polish and edge-case handling
- Additional provider integrations
- Performance optimizations
- Extended test coverage
