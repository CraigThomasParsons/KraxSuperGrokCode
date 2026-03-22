# Piper Development Thoughts

## Current State (2026-01-28)

### What We Have Built

**Phase 1**: Initial job folder structure (inbox/outbox/runs/archive/failed)
**Phase 2**: X11 automation attempted but abandoned due to focus-stealing issues
**Phase 3**: Chrome Extension architecture - WORKING

- `chrome_extension/` - Background polling + content script injection
- `bin/piper_server.py` - HTTP server serving jobs at :3000
**Phase 4**: File extraction from LLM responses - WORKING
- Parser extracts `===FILE: path===` blocks
- Files written to `scratchpad/` (sandboxed)
**Phase 4.5**: Command execution - IMPLEMENTED, NEEDS VERIFICATION
- Parser now extracts `===RUN: bash===` blocks
- Allowlist security (python3, pip, ls, etc.)
- Subprocess execution with timeout and capture

### Architecture Decision: Why Chrome Extension Over X11

**What**: We pivoted from X11/Wayland desktop automation to a Chrome Extension.

**Why**:

1. X11 automation (xdotool/ydotool) caused focus-stealing conflicts with IDE
2. Clipboard operations were unreliable across display servers
3. Chrome Extension runs isolated in browser context - no interference
4. Direct DOM access means reliable text injection and scraping
5. Works identically on any OS with Chrome

### Current Verification Pending

**Job**: `driver_test_run`
**Test**: Write a Python file, then execute it
**Expected**: `execution.log` contains script output

### Security Model (Phase 4.5)

**Allowlist commands**:

- python, python3, pip, pip3
- node, npm
- ls, cat, echo, pwd, mkdir, cp, mv

**Blocked by design**:

- sudo, su, ssh
- rm -rf, dd, mkfs
- Any command not in allowlist

**Sandboxing**:

- All file writes confined to `scratchpad/`
- Subprocess cwd forced to scratchpad
- stdin closed, 5s timeout

### Next Steps

1. Verify Phase 4.5 test passes
2. Document in walkthrough
3. Phase 5: Feedback loop (send execution results back to ChatGPT)
