# Runtime Skills

## Skill Philosophy

Skills are the runtime tools available to the agent loop. They are intentionally small, typed, and composable.

They are not scenario scripts.

The agent must solve tasks by choosing from these skills based on the current observation, not by jumping into a hidden task-specific pipeline.

## Skill Groups

- observation skills
- navigation skills
- interaction skills
- extraction skills
- safety and confirmation skills
- completion and reporting skills

## Contract Requirements

Every skill must define:

- `name`
- `description`
- `input_schema`
- `output_schema`
- `execute(...)`

Every skill execution must return structured data through a `ToolResult`.

## MVP Skill Set

### Observation Skills

#### `observe_page`

Purpose:
- capture the current page snapshot for runtime reasoning.

Input contract:
- optional `include_text_excerpt: bool`
- optional `include_interactive_elements: bool`

Output contract:
- page URL
- page title
- page summary
- optional text excerpt
- optional list of interactive elements
- optional form-field summaries and observation warnings

Constraints:
- should return a concise state representation;
- should not dump the entire DOM into the planner context by default.

Common errors:
- browser not started;
- active page unavailable;
- snapshot generation failed.

#### `get_interactive_elements`

Purpose:
- expose the actionable controls currently visible to the agent.

Input contract:
- optional `visibility_scope`
- optional `max_elements`

Output contract:
- ordered list of interactive element descriptors with labels, tags, selectors, selector candidates, and visibility hints.

Constraints:
- should prioritize user-relevant controls;
- should stay stable enough for repeated planning steps.

Common errors:
- no page context;
- extraction timed out;
- selector generation unavailable.

### Navigation Skills

#### `navigate`

Purpose:
- open or change the current browser location.

Input contract:
- `url: str`
- optional `wait_for: "load" | "domcontentloaded" | "networkidle" | "commit"`

Output contract:
- resolved URL
- page title if available
- navigation status message
- normalized page observation after navigation

Constraints:
- must respect any host restrictions configured by policy;
- should be treated as moderate risk when navigation crosses trust boundaries.

Common errors:
- invalid URL;
- blocked host;
- browser navigation failure.

### Interaction Skills

#### `click_element`

Purpose:
- click a chosen interactive element.

Input contract:
- `selector: str` or `element_id: str`
- optional `element_name: str`

Output contract:
- resolved target used
- click status
- optional resulting page observation

Constraints:
- must never bypass safety checks for destructive clicks;
- should only target one resolved element.

Common errors:
- selector not found;
- element not visible;
- click intercepted or timed out.

#### `type_text`

Purpose:
- enter text into a field or editable region.

Input contract:
- `selector: str` or `element_id: str`
- `text: str`
- optional `clear_first: bool`
- optional `submit: bool`

Output contract:
- resolved target used
- number of characters entered
- whether the field was cleared first
- status message
- optional resulting page observation

Constraints:
- secrets should not be echoed into logs;
- typing should remain atomic and traceable.

Common errors:
- selector not found;
- field not editable;
- typing failed.

### Extraction Skills

#### `extract_page_text`

Purpose:
- retrieve readable text from the current page for reasoning or reporting.

Input contract:
- optional `max_chars: int`

Output contract:
- extracted text
- truncation flag
- source metadata

Constraints:
- must cap output size for prompt safety;
- page content is untrusted input.

Common errors:
- page unavailable;
- extraction failed;
- content too large without truncation policy.

### Safety And Confirmation Skills

#### `request_confirmation`

Purpose:
- produce a formal user confirmation request for a risky planned action.

Input contract:
- `action_name: str`
- `rationale: str`
- `risk_level: str`
- optional `consequences: list[str]`

Output contract:
- `ConfirmationRequest` payload
- operator-facing prompt message

Constraints:
- must be used before destructive actions;
- should explain the risk in clear human language.

Common errors:
- missing action context;
- unsupported risk level;
- confirmation manager unavailable.

### Completion And Reporting Skills

#### `finish_task`

Purpose:
- signal task completion or controlled termination with a user-facing summary.

Input contract:
- `status: str`
- `summary: str`
- optional `next_steps: list[str]`
- optional `open_questions: list[str]`

Output contract:
- completion status
- final summary
- follow-up items

Constraints:
- should be used only when the runtime has enough evidence to stop;
- should distinguish success from safe early termination.

Common errors:
- invalid status;
- missing summary;
- report assembly failed.

## Extension Strategy

The MVP skill set is intentionally small. New skills should be added only when:

- they represent a genuinely reusable runtime capability;
- they have a clear typed contract;
- they do not embed a multi-step scenario;
- they can be explained independently from a specific user task.

Likely later additions:

- `select_option`
- `scroll_viewport`
- `upload_file`
- `download_file`
- `read_dialog`
- `capture_screenshot` as an explicit user-facing skill if bounded observation screenshots are no longer enough

## Anti-Patterns

These are explicitly not allowed:

- a skill named after a business scenario such as `delete_spam_emails`;
- a skill that hides multiple unrelated browser steps;
- an output contract that is free-form text only;
- direct planner bypass through ad hoc calls to the browser layer.
