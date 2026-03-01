---
name: ui_control
description: Run CLI commands, control desktop UI, take screenshots, and automate repetitive tasks on Windows (5090) or Linux/Jetson.
version: "0.1.0"
llm_provider: null

actions:
  run_script:
    description: Execute a CLI command and return stdout/stderr.
    parameters:
      command:
        type: string
        required: true
        description: Shell command to execute (e.g. "git status", "python script.py").
      working_dir:
        type: string
        description: Working directory for the command. Defaults to project root.
      timeout_sec:
        type: integer
        default: 30
        description: Max execution time in seconds before the process is killed.

  screenshot:
    description: Capture the current screen content.
    parameters:
      analyze:
        type: boolean
        default: false
        description: >
          If true, pass the screenshot to a vision model (e.g. Ollama qwen2-vl)
          and return a text description.
      question:
        type: string
        description: Question to ask the vision model about the screenshot.

  click:
    description: Move the mouse and click at a screen position or on a UI element.
    parameters:
      x:
        type: integer
        description: X pixel coordinate (mutually exclusive with element_text).
      y:
        type: integer
        description: Y pixel coordinate (mutually exclusive with element_text).
      element_text:
        type: string
        description: >
          Text label of a UI element to find and click (uses vision model to locate).
      button:
        type: string
        default: left
        description: "Mouse button: left | right | middle"

  type_text:
    description: Type text into the currently focused input field.
    parameters:
      text:
        type: string
        required: true
        description: Text to type.
      press_enter:
        type: boolean
        default: false
        description: Press Enter after typing.

  browser_open:
    description: Open a URL in a headless browser and return page content or a screenshot.
    parameters:
      url:
        type: string
        required: true
      wait_for:
        type: string
        description: CSS selector to wait for before capturing content.
      return_html:
        type: boolean
        default: false
        description: If true, return raw HTML. Otherwise return text content.
---

# UI Control Skill  *(not yet implemented)*

Controls the local computer's UI and CLI. Works on both the Windows 5090 desktop
and on Jetson (Linux). Enables automation of tasks that don't have an API.

## Planned use cases

- **CLI automation**: "Run the build script and tell me if it fails"
- **GUI automation**: "Open the game launcher and click Start"
- **Vision-guided interaction**: "Take a screenshot and tell me what's on the screen"
- **Web scraping**: "Open this page and extract the table data"
- **Robot-side automation** (Jetson): "Check the camera feed and report if anything moves"

## When to use *(once implemented)*

- User wants to run a command or script
- User wants to automate a desktop action
- Another skill needs to take a screenshot for vision analysis

## Security policy

- **Whitelist approach**: `run_script` should only execute pre-approved commands or
  commands explicitly confirmed by the user. Never pass raw user input to shell.
- **Sandboxing**: Use subprocess with limited permissions; never run as root.
- **Confirmation**: For destructive commands (rm, format, etc.), always ask the user first.

## Implementation notes (for developers)

- CLI: `asyncio.create_subprocess_exec` (never `shell=True`)
- Mouse/keyboard: `pyautogui` on Windows/Linux
- Screenshots: `pyautogui.screenshot()` or `mss` library (faster)
- Vision analysis: send screenshot bytes to Ollama `qwen2-vl` or `llava`
- Browser: `playwright` (async API) — install via `playwright install chromium`
- On Jetson: same approach works; use Xvfb for headless display if no monitor attached
