# Browser Agent Demo Guide

This guide explains how to run and understand the controlled demos for the browser agent system.

## Fast path (pipx)

1. Install **Python 3.10+** and [pipx](https://pypa.github.io/pipx/).
2. `pipx install browser-agent-foundation` (or install from this repo / a future PyPI name).
3. `browser-agent setup` — installs Chromium via `python -m playwright install chromium`, writes `~/.browser-agent/config.yaml`.
4. `browser-agent doctor` — verify Playwright, config, and LLM (best effort).
5. `browser-agent demo food --ui` (or `jobs`, `spam`) — **local pages only**; a small server is started on `127.0.0.1` if needed.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Demo 1: Inbox Management](#demo-1-inbox-management)
- [Demo 2: Food Ordering](#demo-2-food-ordering)
- [Demo 3: Job Applications](#demo-3-job-applications)
- [Understanding Agent Behavior](#understanding-agent-behavior)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### 1. Install the Browser Agent

Ensure the browser agent is installed and configured:

```bash
# Editable install from a checkout
pip install -e .

# Or pipx (see Fast path above)
pipx install browser-agent-foundation
```

Verify: `browser-agent --version`

### 2. Configure LLM Provider

Use **`browser-agent setup`** (writes `~/.browser-agent/config.yaml`) or set environment variables (see repository `.env.example`):

- `BROWSER_AGENT_PLANNER_ENABLED=true`
- `BROWSER_AGENT_PLANNER_PROVIDER` — `openai_compatible` or `google_compatible`
- `BROWSER_AGENT_PLANNER_BASE_URL`, `BROWSER_AGENT_PLANNER_MODEL`, `BROWSER_AGENT_PLANNER_API_KEY`

### 3. Start the Demo Server

**Packaged demos** (no manual server):

```bash
browser-agent demo spam --ui
```

**Development tree** — manual server:

```bash
python demos/server.py
```

The server starts on `http://localhost:8765/` by default.

### Optional: Interactive terminal UI

For live step-by-step output, token totals, and Rich confirmation prompts during demos:

```bash
browser-agent demo food --ui
# or, with a running server:
browser-agent --ui --start-url http://localhost:8765/inbox_demo.html "Your task here"
```

See **Agent Console UI (`--ui`)** in the repository `README.md` for panel descriptions, phases, and a sample final summary. `--ui` is not compatible with `--json`.

## Demo 1: Inbox Management

### Page Overview

The inbox demo simulates an email client with:
- 5 sample emails (mix of legitimate and spam)
- Spam/Important marking actions
- Filter tabs (All, Spam, Important)
- Persistent state via localStorage

**URL:** `http://localhost:8765/inbox_demo.html`

### Example Tasks

#### Task 1: Mark Suspicious Emails as Spam

```bash
browser-agent --start-url http://localhost:8765/inbox_demo.html \
  "Mark the suspicious emails as spam. Look for obvious spam indicators like suspicious sender names or unrealistic offers."
```

**Expected Agent Behavior:**
1. Observe the page and identify email list
2. Read sender names and subject lines
3. Identify PrinceNigeria and GetRichQuick as suspicious
4. Click "Mark Spam" buttons for these emails
5. Verify emails move to spam filter view

**Skills Demonstrated:**
- `observe_page` - Read page content
- `click_element` - Mark emails as spam
- Navigation between filter views

#### Task 2: Mark Important Emails

```bash
browser-agent --start-url http://localhost:8765/inbox_demo.html \
  "Mark the email from Sarah in HR as important, and also the email from Mom"
```

**Expected Agent Behavior:**
1. Identify emails from Sarah and Mom
2. Click "Mark Important" for each
3. Verify emails show important badge

#### Task 3: Filter Views

```bash
browser-agent --start-url http://localhost:8765/inbox_demo.html \
  "First mark some emails as spam, then view only the spam folder to confirm they were moved"
```

**Expected Agent Behavior:**
1. Mark spam emails
2. Click "Spam" filter tab
3. Verify marked emails appear in spam view

### What This Demo Shows

- **Generic interaction**: No email-specific code - uses generic `click_element` skill
- **Planner decision-making**: Agent decides which emails to mark based on content
- **State observation**: Agent reads email content to make decisions
- **Visual feedback**: UI updates confirm actions worked

## Demo 2: Food Ordering

### Page Overview

The food demo simulates a restaurant ordering system with:
- Menu with 6 items (Burger, Pizza, Pasta, Salad, Drink, Dessert)
- Shopping cart sidebar
- Multi-step checkout flow
- Payment form with validation
- Order confirmation page

**URL:** `http://localhost:8765/food_demo.html`

### Example Tasks

#### Task 1: Simple Order

```bash
browser-agent --start-url http://localhost:8765/food_demo.html \
  "Order a Classic Burger and a Soft Drink"
```

**Expected Agent Behavior:**
1. Observe menu items
2. Click "Add to Cart" for burger
3. Click "Add to Cart" for drink
4. Verify cart shows 2 items
5. Display final cart state

**Skills Demonstrated:**
- `observe_page` - Read menu
- `click_element` - Add items to cart
- Reading dynamic cart state

#### Task 2: Full Checkout Flow

```bash
browser-agent --start-url http://localhost:8765/food_demo.html \
  "Order a Margherita Pizza and Chocolate Cake, then proceed to checkout and complete the payment with name John Doe, email john@example.com, and card details"
```

**Expected Agent Behavior:**
1. Add pizza and cake to cart
2. Click "Proceed to Checkout"
3. Fill in name, email, phone fields
4. Fill in card number, expiry, CVV
5. Click "Complete Payment"
6. Verify confirmation page appears

**Skills Demonstrated:**
- `click_element` - Add items, proceed to checkout
- `type_text` - Fill form fields
- Multi-step navigation
- Form submission

#### Task 3: Modify Cart

```bash
browser-agent --start-url http://localhost:8765/food_demo.html \
  "Add a burger to the cart, then increase the quantity to 2, then remove it"
```

**Expected Agent Behavior:**
1. Add burger to cart
2. Click quantity increase (+) button
3. Verify quantity shows 2
4. Click remove (×) button
5. Verify cart is empty

### What This Demo Shows

- **Multi-step workflows**: Agent handles sequential page state changes
- **Form interaction**: Fills multiple form fields accurately
- **Dynamic content**: Reacts to cart updates
- **Navigation**: Handles transitions between menu, checkout, and confirmation

## Demo 3: Job Applications

### Page Overview

The jobs demo simulates a job board with:
- 6 job listings with different types/levels/locations
- Filter sidebar (Job Type, Experience, Location)
- Application modal with form
- File upload simulation
- Application confirmation

**URL:** `http://localhost:8765/jobs_demo.html`

### Example Tasks

#### Task 1: Filter and Find

```bash
browser-agent --start-url http://localhost:8765/jobs_demo.html \
  "Filter for remote full-time jobs and show me the Senior Frontend Developer listing"
```

**Expected Agent Behavior:**
1. Check "Full-time" checkbox
2. Check "Remote" checkbox
3. Observe filtered results
4. Identify Senior Frontend Developer job card
5. Report job details

**Skills Demonstrated:**
- `click_element` - Check filter boxes
- `observe_page` - Read filtered results
- Information extraction

#### Task 2: Complete Application

```bash
browser-agent --start-url http://localhost:8765/jobs_demo.html \
  "Apply for the Backend Engineer position at DataSystems. Fill in the application with name Jane Smith, email jane@example.com, and any other required information."
```

**Expected Agent Behavior:**
1. Find Backend Engineer job card
2. Click "Apply Now" button
3. Fill name field
4. Fill email field
5. Fill phone (optional but provided)
6. Handle file upload field
7. Submit application
8. Verify confirmation appears

**Skills Demonstrated:**
- `click_element` - Apply button, submit
- `type_text` - Form fields
- `upload_file` - Resume upload
- Modal dialog handling

#### Task 3: Compare Multiple Jobs

```bash
browser-agent --start-url http://localhost:8765/jobs_demo.html \
  "Show me all the jobs that are either senior level or have a salary above $150k"
```

**Expected Agent Behavior:**
1. Observe all job listings
2. Extract salary and level information
3. Filter based on criteria
4. Report matching jobs

### What This Demo Shows

- **Complex filtering**: Multiple filter criteria interaction
- **Modal handling**: Opening/closing application forms
- **Data extraction**: Reading job details from cards
- **File handling**: Upload interaction
- **Conditional logic**: Filtering and comparing data

## Understanding Agent Behavior

### Observation Phase

The agent always starts by observing the current page state:

1. **Page snapshot**: Captures DOM structure, visible text, interactive elements
2. **Element extraction**: Identifies buttons, links, form fields, etc.
3. **State assessment**: Determines what's available on the current page

### Planning Phase

The LLM planner decides the next action based on:

1. **Task goal**: What the user asked for
2. **Current state**: What's visible on the page
3. **History**: What actions have already been taken
4. **Available skills**: What capabilities are registered

### Action Phase

The chosen skill is executed:

1. **Skill execution**: Performs the browser action
2. **Result capture**: Records success/failure
3. **State update**: Page may change after action
4. **Trace recording**: Logs the step for reporting

### Loop Until Done

The agent continues the observe-plan-act cycle until:

- Task is completed successfully
- Confirmation is required (pauses for user)
- User question needs answering (pauses for user)
- Maximum steps reached
- Unrecoverable error occurs

## Expected Agent Output

### Trace Output

During execution, the CLI shows:

```
Step 1: observe_page 
  ├─ Rationale: First, I need to see what's on the page...
  ├─ Observation: Email inbox with 5 messages...
  └─ Progress: Initial page observation

Step 2: click_element (mark-spam-2)
  ├─ Rationale: PrinceNigeria email is clearly spam...
  ├─ Result: Email marked as spam, moved to spam folder
  └─ Progress: Successfully marked first spam email
```

### Final Report

When complete, the agent outputs a structured report:

```
╔══════════════════════════════════════════════════════════════╗
║                    BROWSER AGENT RESULT                      ║
╚══════════════════════════════════════════════════════════════╝

Status:    COMPLETED
Outcome:   Completed
Steps:     4

─ SUMMARY ─
Successfully marked 2 suspicious emails as spam: PrinceNigeria and GetRichQuick

─ ORIGINAL TASK ─
Mark the suspicious emails as spam...

─ ACTIONS TAKEN ─
  1. observe_page
  2. click_element (mark-spam-2)
  3. click_element (mark-spam-4)
  4. observe_page (verification)

─ EXECUTION TRACE ─
  Step 1: observe_page
    └─ Observed email inbox with 5 messages...
  Step 2: click_element ✓
    └─ Identified PrinceNigeria as spam...
  ...
```

## Troubleshooting

### "Element not found" errors

**Cause**: The agent is trying to click an element that doesn't exist or has a different selector.

**Solution**:
- Check the demo page has loaded correctly
- Verify `data-testid` attributes exist in the HTML
- The agent may need to scroll or wait for dynamic content

### "Confirmation required" pauses

**Cause**: The safety layer detected a potentially risky action (like form submission).

**Solution**:
- This is expected behavior! The agent is asking for your approval.
- Type `yes` or `no` to continue or stop.
- The safety system prevents accidental destructive actions.

### "Stuck in a loop"

**Cause**: The agent keeps trying the same actions without making progress.

**Solution**:
- The progress detector should catch this after a few iterations
- Check if the page state is actually changing after actions
- The demo pages should provide visual feedback (button changes, messages, etc.)

### Page not loading

**Cause**: Demo server not running or wrong URL.

**Solution**:
```bash
# Verify server is running
python demos/server.py

# Check URL in browser
curl http://localhost:8765/inbox_demo.html
```

### LLM not responding

**Cause**: API key not set or provider unavailable.

**Solution**:
```bash
# Check environment variables
echo $OPENAI_API_KEY
echo $GOOGLE_API_KEY

# Test with a simple task
browser-agent --dry-run "test"
```

## Advanced Usage

### JSON Output Mode

For programmatic use:

```bash
browser-agent --json --start-url http://localhost:8765/inbox_demo.html \
  "Mark suspicious emails as spam"
```

### With Custom Provider

```bash
browser-agent \
  --provider openrouter \
  --model anthropic/claude-3.5-sonnet \
  --start-url http://localhost:8765/food_demo.html \
  "Order a burger"
```

### Recording Traces

Traces are automatically saved to the configured trace directory:

```bash
# Default location
cat traces/*.jsonl

# Or as markdown
cat traces/*.md
```

## Tips for Effective Demos

1. **Start simple**: Begin with basic tasks like "click this button" before complex multi-step workflows
2. **Be specific**: Clear task descriptions help the agent understand goals
3. **Watch the trace**: The step-by-step trace shows what the agent is thinking
4. **Check confirmations**: Risky actions will pause - this shows the safety system working
5. **Verify outcomes**: After completion, manually check the demo page state
6. **Iterate**: If the agent struggles, try rephrasing the task or breaking it into smaller steps

## Summary

These demos showcase:

- **Real browser automation** via Playwright
- **Planner-based decision making** with LLM reasoning
- **Safety confirmation flow** for risky actions
- **User interaction handling** for questions and confirmations
- **Clear reporting and traceability** with step-by-step logs
- **Generic skills** that work across any website, not just these demos

The demos work entirely locally without external internet access, making them perfect for presentations, testing, and development.
