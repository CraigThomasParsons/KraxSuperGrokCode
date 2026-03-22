# Piper Phase 3: The Browser Bridge (Extension)

## Promblem

OS-level automation (`xdotool`, `click`, `focus`) is fundamentally flaky on modern Linux (Wayland/Hybrid) because scripts cannot reliably "steal" focus or execute input without explicit user intervention.

## Solution

Move the automation **inside** the browser using a local Chrome Extension.

## Architecture

1. **Piper Host (`piper_proxy.py` becomes `piper_server.py`)**:
    - Runs a lightweight HTTP server (Flask or simple `http.server`).
    - Host serves the "Current Job" JSON.
    - Host accepts "Job Complete" signals (screenshots/text).

2. **Piper Client (Chrome Extension)**:
    - **Permissions**: `activeTab`, `scripting`, `host_permissions` for ChatGPT.
    - **Content Script**: Injected into `chatgpt.com`.
    - **Logic**:
        - Polls `localhost:PORT/job`.
        - If job exists:
            - Finds the `<textarea>` (reliably, via DOM).
            - Inserts text directly.
            - Clicks Send.
            - Waits for response.
            - Scrapes response text (BONUS: No OCR needed!).
            - POSTs result back to Piper Host.

## Why this wins

- **Zero Focus Issues**: It runs in the background tab. You can use your PC normally.
- **Zero Coordinate Guessing**: It finds the DOM element by ID/Selector.
- **Structured Data**: We get the actual text response back, not just a screenshot.

## Implementation Steps

1. **Server**: Create `bin/piper_server.py` (The new "Proxy").
2. **Extension**: Create `chrome_extension/manifest.json`, `background.js`, `content.js`.
3. **Install**: Load Unpacked extension in Chrome.

## User Action Required

- "Load Unpacked" the extension once.
- Run `piper_server.py`.

Shall we build this?
