# Multi-Agent Implementation Plan: Vera & Krax

## Goal Description
Establish two distinct but complementary automation agents:
1. **Krax (KraxSuperGrokCode)**: An agent that automatically generates code by interfacing with Grok.com (mirroring the Auralis/ChatGPT architecture).
2. **Vera**: A visual QA agent that uses `ydotool`/`xdotool`, captures visual desktop evidence (screenshots), and leverages Vision LLMs to verify that Krax's UI code behaves and looks correctly.

## User Review Required
> [!IMPORTANT]
> The plan below proposes repurposing the Auralis conduit architecture for Krax, and integrating the Piper Phase 2 desktop automation into Vera.
> Please review the architecture and testing flows below. Are there any specific Vision LLMs (e.g. GPT-4o, Claude) you want Vera to default to?

---

## 1. Krax: The Coding Agent (Grok Integration)

**Objective**: Krax will take coding jobs from a queue, use a Chrome Extension to drive Grok.com, and extract the generated code.

### Proposed Changes

#### [MODIFY] `chrome_extension/` (Krax Extension)
- Adapt the existing Auralis Chrome Extension logic to interact with the Grok UI (`grok.com`) instead of ChatGPT.
- **Content Script (`content.js`)**: 
  - Locate the Grok input textarea and inject the briefing prompt.
  - Implement a DOM observer to detect when Grok finishes generating its response.
  - Extract the text and markdown code blocks accurately from Grok’s specific DOM structure.
- **Background Script (`background.js`)**: 
  - Poll the local Krax server (`http://localhost:3001/job`) for new coding assignments.
  - Coordinate the routing between the Grok tab and the server API.

#### [NEW/MODIFY] `bin/krax_server.py`
- Implement the local job queue server for Krax (similar to [auralis_server.py](file:///home/craigpar/Code/Auralis/bin/auralis_server.py) but on port 3001).
- Integrate the newly developed standard regex snippet extractor (from Auralis) to reliably parse out Grok's code responses into individual files inside `runs/<job_id>/extracted/`.

---

## 2. Vera: The Visual QA Agent

**Objective**: Vera will act as an autonomous "pair of eyes and hands" that executes compiled UI code from Krax, screenshots the results, and evaluates them with a Vision LLM.

### Proposed Changes

#### [MODIFY] `bin/test_executor.py` (Desktop Automation)
- Integrate the "Blind Click" and keyboard typing architecture seen in the `Piper Phase 2` instructions.
- Implement explicit `ydotool` (Wayland/X11) and `xdotool` (X11 fallback) commands to mechanically move the mouse, click specific coordinates, and type text.
- Develop a standardized method to focus a sandbox browser to interact with local Krax-generated HTML/JS components.

#### [MODIFY] `bin/evidence_capture.py` (Visual Processing)
- Implement screenshot mechanisms capable of targeting the active window or specific screen regions based on the current display server (`grim` for Wayland, `scrot` for X11).
- Add functionality to stitch, crop, or format screenshots to prepare them for the Vision LLM.

#### [MODIFY] `bin/ai_evaluator.py` (Vision LLM Evaluation)
- Connect Vera to a Vision-capable LLM API (e.g. OpenAI Vision).
- Develop evaluation prompts that instruct the Vision LLM to compare the screenshot of the UI against the provided Acceptance Criteria (from the QA Queue).
- Parse the LLM's assessment into definitive `PASS` or `FAIL` states to route to `verdicts/` and back to Krax.

---

## Verification Plan

### Manual Integration Test
1. **Krax Phase**: Drop a prompt in Krax's `inbox/` asking for a simple "Red Login Button with rounded corners". Ensure Krax routes it through Grok.com and extracts the resulting HTML/CSS files.
2. **Server Phase**: Host the extracted Krax code on a local static server.
3. **Vera Phase**: Provide Vera with the task to "Verify the login button is red and rounded". Vera uses `ydotool` to open the local component in a browser, snaps a screenshot using `evidence_capture.py`, and sends it to the AI Evaluator. We will then verify Vera's generated markdown report correctly identifies a `PASS`.
