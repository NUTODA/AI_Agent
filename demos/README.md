# Demo Pages

This directory contains controlled demo pages for testing and demonstrating the browser agent's capabilities.

## Overview

These demo pages are designed to simulate real-world web interactions in a controlled, reproducible environment. They are intentionally simple, self-contained HTML files that work without external dependencies.

## Demo Pages

### 1. Inbox Demo (`pages/inbox_demo.html`)

A simulated email inbox interface demonstrating:
- Email list management
- Spam marking and filtering
- Important marking
- State persistence via localStorage
- Interactive confirmation workflows

**Example Agent Task:**
> "Mark all suspicious emails as spam. The emails from PrinceNigeria and GetRichQuick are clearly spam."

### 2. Food Demo (`pages/food_demo.html`)

A food ordering interface demonstrating:
- Menu navigation and item selection
- Shopping cart management
- Form filling for checkout
- Payment flow simulation
- Multi-step transaction process

**Example Agent Task:**
> "Order a Classic Burger and a Soft Drink, then proceed to checkout and fill in the payment details."

### 3. Jobs Demo (`pages/jobs_demo.html`)

A job board interface demonstrating:
- Job listing filtering by type, level, and location
- Detailed job view navigation
- Application form submission
- File upload simulation
- Modal dialog interactions

**Example Agent Task:**
> "Filter for remote full-time jobs and apply to the Senior Frontend Developer position at TechCorp."

## Running the Demos

### Option 1: Using the Demo Server

The easiest way to run the demos is using the included server:

```bash
# From the project root
python demos/server.py

# Or specify a custom port
python demos/server.py --port 8080
```

The server will start and print URLs for accessing the demo pages.

### Option 2: Opening Files Directly

You can also open the HTML files directly in a browser:

```bash
# On macOS
open demos/pages/inbox_demo.html

# On Linux
xdg-open demos/pages/inbox_demo.html

# On Windows
start demos/pages/inbox_demo.html
```

Note: Some features (like localStorage) may work slightly differently when opening files directly vs. serving them via HTTP.

### Option 3: Using Python's Built-in Server

```bash
cd demos/pages
python -m http.server 8765
```

Then open http://localhost:8765/ in your browser.

## Using with the Browser Agent

Once the demo server is running, you can use the browser agent CLI to interact with the demo pages:

```bash
# Inbox demo - mark spam emails
browser-agent --start-url http://localhost:8765/inbox_demo.html "Mark the suspicious emails as spam"

# Food demo - place an order
browser-agent --start-url http://localhost:8765/food_demo.html "Order a burger and drink, then checkout"

# Jobs demo - apply for a job
browser-agent --start-url http://localhost:8765/jobs_demo.html "Filter for remote jobs and apply to the frontend position"
```

## Demo Page Features

All demo pages include:

- **Data attributes**: Elements have `data-testid` attributes for stable selector targeting
- **Visual feedback**: Clear visual states for interactions (hover, active, selected)
- **State persistence**: localStorage keeps state between page reloads
- **No external dependencies**: All CSS and JavaScript are inline
- **Responsive design**: Works on different screen sizes
- **Accessibility**: Proper labels and ARIA attributes where appropriate

## Design Principles

These demo pages follow the same principles as the browser agent itself:

1. **No hidden complexity**: Everything is visible in the source code
2. **Real interactions**: Buttons actually do things, forms validate input
3. **Deterministic behavior**: Same inputs produce same outputs
4. **Clean selectors**: data-testid attributes provide stable targeting
5. **Realistic scenarios**: Simulate genuine user workflows

## Extending the Demos

To add a new demo page:

1. Create a new HTML file in `pages/`
2. Include inline CSS and JavaScript (no external dependencies)
3. Add `data-testid` attributes to interactive elements
4. Update this README with the new demo description
5. Update `docs/demo.md` with example agent tasks

## Troubleshooting

### Pages not loading
- Ensure the server is running on the correct port
- Check that there are no firewall issues blocking the port
- Try opening the file directly to verify the HTML is valid

### State not persisting
- localStorage requires the page to be served over HTTP/HTTPS
- Opening files directly with `file://` protocol may have storage restrictions
- Use the demo server for full functionality

### Selectors not working
- Check that `data-testid` attributes are present in the HTML
- Verify the browser agent is using the correct selector strategy
- Try using browser dev tools to inspect element selectors
