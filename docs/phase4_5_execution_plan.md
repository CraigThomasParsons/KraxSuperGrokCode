# Piper Phase 4.5: Controlled Execution

## Goal

Enable Piper to execute shell commands specified by the LLM. This transforms it from a "File Writer" to a "General Purpose Agent".

## Protocol

A new block type:
===RUN: bash===
npm install
ls -la
===END===

## Security Model

Allowing arbitrary execution is dangerous.
**Rules:**

1. **Block List**: `rm -rf /`, `sudo`, `su`, `ssh` (basic protection).
2. **CWD**: All commands run in the *Root of the Job's Scratchpad* (`scratchpad/`).
3. **Non-Interactive**: stdin is closed. 5s timeout.

## Implementation Steps

### 1. `bin/lib/parser.py`

- Add regex for `===RUN: ...===`.
- Return execution blocks in the parsed list.

### 2. `bin/piper_server.py`

- Iterate over parsed blocks.
- If `type == "file"`: Write file (existing logic).
- If `type == "run"`: Execute command via `subprocess.run`.
- **Critical**: Capture stdout/stderr and append to `execution.log`.

## Verification Test

**Job**: `driver_test_run`
**Task**:

1. Write `hello.py`.
2. Run `python3 hello.py`.
**Expected**: `execution.log` contains "Hello...".
