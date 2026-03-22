# Piper Refactor: Direct Typing Mode

## Goal

Switch from "Copy to Clipboard -> Ctrl+V" to "Directly Type Characters" to improve reliability of text entry into ChatGPT, bypassing potential clipboard or paste-blocker issues.

## Proposed Changes

### 1. `Piper/bin/lib/input.py`

- **New Function**: `type_text_slowly(text, delay_ms=4)`
- **Logic**:
  - Iterates through the string.
  - Sends individual keystrokes via `ydotool type` (which handles strings, but we might want to chunk it if it's huge, though `ydotool type` is usually fine for one block).
  - *Actually*, `ydotool type "string"` is standard. The user requested "type_text_slowly", implying we might need to throttle it or just use the standard type command which is naturally slower than a paste.
  - **Correction**: The user screenshot explicitly suggests: `type_text_slowly(briefing_text, delay_ms=4)`.
  - To implement "slowly" with `ydotool type`, we typically just call it once. Breaking it into chars `ydotool type "c"`, `sleep`, `ydotool type "h"` is very slow and spammy on processes.
  - **Plan**: Use `ydotool type <content>`. If `ydotool` supports a delay flag using it, otherwise relying on its natural speed. (ydotool's `type` has a `--key-delay` arg in some versions, or we just trust `type` command).
  - *Refinement*: `ydotool type` takes the whole string. We will just wrap it.

### 2. `Piper/bin/piper_proxy.py`

- **Remove**: `clipboard` import and usage.
- **Replace**: `clipboard.copy_to_clipboard(...)` + `Ctrl+v`
- **With**: `input.type_text(briefing)` directly.

### 3. Verification

- Rerun `intro_test`.
- User manually focuses window.
- Watch text appear character by character (or block by block).
