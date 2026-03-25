# Runtime Skills

## Skill Philosophy

Skills are the runtime tools available to the agent loop. They are intentionally small, typed, and composable.

They are not scenario scripts.

The agent must solve tasks by choosing from these skills based on the current observation, not by jumping into a hidden task-specific pipeline.

The planner is only allowed to choose skills that exist in the registry. Unknown tools, ad hoc browser commands, and generated code are outside the allowed action space.

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

The runtime also uses `observe_page` as an internal observation step before planning and after actions that do not naturally return a fresh observation.

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

Notes:
- the planner may propose a click, but the safety layer still decides whether confirmation is required before execution.

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

### Advanced Observation Skills

#### `wait_for_element`

Purpose:
- pause execution until an element reaches a specific state (visible, hidden, attached, detached).

Input contract:
- `selector: str`
- optional `timeout_ms: int` (default 5000)
- optional `state: str` ("visible" | "hidden" | "attached" | "detached", default "visible")

Output contract:
- `found: bool`
- `selector: str`
- `waited_ms: int`
- `state: str`
- status message

Constraints:
- should respect timeout limits;
- not a permanent wait - should fail gracefully after timeout.

Common errors:
- element never reached desired state;
- invalid state parameter;
- selector not found.

### Navigation Extension Skills

#### `scroll_viewport`

Purpose:
- scroll the page viewport or a specific element in any direction.

Input contract:
- `direction: str` ("up" | "down" | "left" | "right", default "down")
- optional `amount: int` (pixels, default 500)
- optional `selector: str` (if omitted, scrolls main viewport)

Output contract:
- `direction: str`
- `amount: int`
- `target: str | None`
- `scroll_x: int`
- `scroll_y: int`
- status message

Constraints:
- scroll amount should be reasonable for typical pages;
- should report final scroll position.

Common errors:
- invalid direction;
- element not scrollable;
- scroll execution failed.

### Interaction Extension Skills

#### `select_option`

Purpose:
- select an option from a dropdown/select element by value or visible text.

Input contract:
- `selector: str` or `element_id: str`
- optional `option_value: str` (the value attribute)
- optional `option_text: str` (the visible text)

Output contract:
- `target: str`
- `selected_value: str | None`
- `selected_text: str | None`
- status message

Constraints:
- one of `option_value` or `option_text` must be provided;
- should verify the selection was successful.

Common errors:
- selector not found;
- option not found in dropdown;
- element is not a select input.

#### `press_key`

Purpose:
- press a keyboard key like Enter, Escape, Tab, etc.

Input contract:
- `key: str` (e.g., "Enter", "Escape", "Tab", "ArrowDown")
- optional `selector: str` or `element_id: str` (if targeting a specific element)

Output contract:
- `key: str`
- `target: str | None`
- status message

Constraints:
- should support common navigation and form keys;
- if no target, sends to active element or page.

Common errors:
- invalid key name;
- target element not focusable;
- key press failed.

### File Handling Skills

#### `upload_file`

Purpose:
- upload a file to a file input element.

Input contract:
- `selector: str` or `element_id: str`
- `file_path: str` (path to local file)

Output contract:
- `target: str`
- `file_name: str`
- `file_path: str`
- status message

Constraints:
- file must exist at the provided path;
- target must be a file input element;
- file path should be validated before upload.

Common errors:
- file not found;
- target not a file input;
- upload failed (size limits, etc.).

### Dialog Skills

#### `inspect_dialog`

Purpose:
- check for and read the content of any active dialog, alert, confirm, or prompt.

Input contract:
- optional `timeout_ms: int` (default 100)

Output contract:
- `visible: bool`
- `dialog_type: str | None` (alert, confirm, prompt, dialog, modal)
- `message: str | None` (the dialog text content)
- `default_value: str | None` (for prompt dialogs)

Constraints:
- should detect both native dialogs and HTML modal dialogs;
- quick check - not a blocking wait.

Common errors:
- dialog inspection failed;
- ambiguous dialog detection.

### Safety And Confirmation Skills

#### `request_confirmation`

Purpose:
- produce a formal user confirmation request for a risky planned action.

Current runtime note:
- the main loop can now create confirmation requests directly from planner decisions or safety guardrails;
- this helper skill remains available as a typed contract, but the planner should not select it as a substitute for the risky target action itself.

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

Current runtime note:
- the planner emits `decision_type=finish`;
- the runtime then routes that decision through the typed `finish_task` skill instead of allowing the planner to finalize the session with free-form text.

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

Recently added:

- `select_option` - select from dropdowns
- `scroll_viewport` - page and element scrolling
- `press_key` - keyboard interaction
- `wait_for_element` - conditional waiting
- `upload_file` - file input handling
- `inspect_dialog` - dialog detection

Potential future additions:

- `download_file` - handle file downloads
- `capture_screenshot` as an explicit user-facing skill if bounded observation screenshots are no longer enough
- `hover_element` - mouse hover actions
- `drag_and_drop` - drag-drop interactions

## Anti-Patterns

These are explicitly not allowed:

- a skill named after a business scenario such as `delete_spam_emails`;
- a skill that hides multiple unrelated browser steps;
- an output contract that is free-form text only;
- direct planner bypass through ad hoc calls to the browser layer;
- planner output that references a skill that is not registered;
- site-specific `if/else` logic embedded inside a generic skill.
