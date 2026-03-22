# Piper Phase 4: Closing the Loop

## Goal

Now that the Browser Extension ("Piper Client") can reliably type prompts and retrieve responses, we must connect it to the **Execution Engine** (`bin/agent.py` logic) so Piper can actually *do* work.

## Current State

- `inbox/JOB` -> `piper_server.py` -> Extension -> ChatGPT -> Extension -> `piper_server.py` -> `runs/JOB/response.txt`.
- The process stops there.

## Proposed Flow ("The Dream")

1. **Response Received**: Server receives JSON from Extension.
2. **Parsing**: Server extracts Code Blocks from the markdown response.
3. **Execution**: Server interprets the code blocks:
    - `===FILE: path=== ... ===END===`: Writes files.
    - `sh`: Executes shell commands.
    - `python`: Executes python scripts.
4. **Feedback Loop**:
    - If execution succeeds: Post "Success" back to ChatGPT? (Phase 5).
    - For now: Just save the results in `runs/JOB/execution.log`.

## Implementation Steps

### 1. `bin/lib/parser.py` (New)

- Function `parse_response(text)`:
  - Regex to find `===FILE: path===` blocks.
  - Regex or logic to find execution blocks (optional for now, let's focus on File Writing first as requested in prompts).

### 2. Update `bin/piper_server.py`

- On `/job/complete`:
  - Call `parser.parse_response(result_text)`.
  - For each file found:
    - Validate path (must be within Piper repo).
    - Write content to disk.
  - Log actions to `runs/JOB/activity.log`.

## Verification

- Create job: "Create a file named hello_piper.py that prints hello".
- Run Server & Extension.
- **Check**: Does `Piper/hello_piper.py` exist?

## Risks

- **Security**: Piper will write files based on ChatGPT output.
- **Mitigation**: **Sandboxing**. We will enforce that files can ONLY be written inside `/home/craigpar/Code/Piper/scratchpad/` for this phase.

Shall we begin?
