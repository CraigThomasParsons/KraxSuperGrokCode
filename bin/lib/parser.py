import re
import os
from dataclasses import dataclass

# Fenced code block regex setup
# This matches triple backticks at the beginning of a line.
# It captures the language identifier and the code contained within.
FENCED_BLOCK_RE = re.compile(
    r"(?ms)^```(?P<lang>[A-Za-z0-9_+\-\.#]*)[ \t]*\r?\n(?P<code>.*?)(?:\r?\n```)[ \t]*$"
)

# Header filename patterns
# These regexes attempt to locate typical inline comment structures
# that specify the filename directly within the top lines of code.
HEADER_FILENAME_PATTERNS = [
    re.compile(r"^\s*(?://|/\*+)\s*(?:file|filename|path)\s*:\s*(?P<filename>[\w./-]+\.[A-Za-z0-9]+)", re.I),
    re.compile(r"^\s*#\s*(?:file|filename|path)\s*:\s*(?P<filename>[\w./-]+\.[A-Za-z0-9]+)", re.I),
    re.compile(r"^\s*<!--\s*(?:file|filename|path)\s*:\s*(?P<filename>[\w./-]+\.[A-Za-z0-9]+)\s*-->", re.I),
]

# Supported language extensions
# Maps common markdown language identifiers to known file extensions
# to allow for graceful fallback when no explicit filename is found.
LANGUAGE_EXTENSION_MAP = {
    "js": ".js", "javascript": ".js", "ts": ".ts", "typescript": ".ts",
    "py": ".py", "python": ".py", "php": ".php", "html": ".html",
    "css": ".css", "json": ".json", "yaml": ".yaml", "yml": ".yaml",
    "md": ".md", "markdown": ".md", "bash": ".sh", "sh": ".sh",
    "zsh": ".zsh", "sql": ".sql", "txt": ".txt", "text": ".txt",
    "jsx": ".jsx", "tsx": ".tsx", "c": ".c", "cpp": ".cpp",
}


@dataclass
class ExtractedSnippet:
    """
    Data structure representing a parsed markdown code snippet.
    Holds metadata like language, confidence, and exactly how it was found.
    """
    index: int
    language: str
    code: str
    filename: str
    detection_method: str
    confidence: str


def map_language_to_extension(language: str | None) -> str:
    """
    Maps a raw language string to a specific file extension.
    Defaults to '.txt' if the language is unknown or missing.
    """
    # If no language is provided, fallback to text format
    if not language:
        return ".txt"
        
    # Standardize the language token for lookup
    normalized_language = language.strip().lower()
    
    # Check map for extension and return it
    return LANGUAGE_EXTENSION_MAP.get(normalized_language, ".txt")


def detect_filename_from_code_header(code: str) -> str | None:
    """
    Trims the code to the top lines and checks for comments declaring a filename.
    Returns the mapped filename if found, otherwise None.
    """
    # Read the first 8 lines of the provided code block
    header_lines = code.splitlines()[:8]
    
    # Iterate over the lines to test our regex patterns
    for line in header_lines:
        
        # Test each possible comment pattern on the current line
        for pattern in HEADER_FILENAME_PATTERNS:
            match = pattern.search(line)
            
            # If a match is found, immediately return the captured filename
            if match:
                return match.group("filename")
                
    # Exhausted all lines and patterns with no success
    return None


def detect_filename_from_surrounding_text(surrounding_text: str) -> str | None:
    """
    Checks the trailing text immediately before a snippet for conversational
    cues that specify what the code block represents (e.g. "Here's app.js").
    """
    # Define conversational patterns indicating an impending code block
    explicit_patterns = [
        re.compile(r"(?:here(?:'s| is)|create|save as|write to|filename:|file:)\s+`?(?P<filename>[\w./-]+\.[A-Za-z0-9]+)`?", re.I),
        re.compile(r"`(?P<filename>[\w./-]+\.[A-Za-z0-9]+)`"),
        re.compile(r"(?P<filename>(?:[\w-]+/)*[\w.-]+\.[A-Za-z0-9]+)"),
    ]
    
    # Iterate through patterns to see if any hit the contextual string
    for pattern in explicit_patterns:
        match = pattern.search(surrounding_text)
        
        # We assume the first detected match is the closest intention
        if match:
            return match.group("filename")
            
    # Return None if no suitable filename indicators are found before the block
    return None


def extract_fenced_code_blocks(response_text: str) -> list:
    """
    Simple wrapper to find all fenced blocks inside the raw response.
    Returns a list of Regex Matches.
    """
    # Use our pre-compiled block matcher to locate fences
    return list(FENCED_BLOCK_RE.finditer(response_text))


def extract_snippet_files(response_text: str) -> list[ExtractedSnippet]:
    """
    Core engine that identifies all fenced blocks and builds ExtractedSnippet
    objects for each, making its best effort to determine names and extensions.
    """
    # Prepare list for output snippets
    snippets: list[ExtractedSnippet] = []
    
    # Discover all blocks first
    matches = extract_fenced_code_blocks(response_text)
    
    # Enumerate the matches starting from 1 for default snippet numbering
    for index, match in enumerate(matches, start=1):
        
        # Capture standard properties from the block regex
        language = (match.group("lang") or "").strip().lower()
        code = match.group("code")
        
        # Capture 300 characters prior to the block as context
        start_index = match.start()
        pre_context = response_text[max(0, start_index - 300):start_index]
        
        # First attempt: Try extracting from within the code header itself
        filename = detect_filename_from_code_header(code)
        detection_method = "inline_comment"
        confidence = "high"
        
        # Second attempt: Look at the contextual text preceding the block
        if not filename:
            filename = detect_filename_from_surrounding_text(pre_context)
            detection_method = "surrounding_text"
            
            # If found, confidence is medium; else we maintain low confidence
            confidence = "medium" if filename else "low"
            
        # Try to resolve a file extension from the raw language string
        extension = map_language_to_extension(language)
        
        # Third attempt: No clue what it's named, build a fallback name
        if not filename:
            
            # Avoid prefixing dockerfiles or makefiles incorrectly
            if extension in {"Dockerfile", "Makefile"}:
                filename = f"{extension}"
            else:
                
                # Format fallback with standard numbering
                filename = f"snippet_{index:02d}{extension}"
                
            # Log exact reason for fallback choice
            detection_method = "language_fallback" if extension != ".txt" else "plain_txt_fallback"
            
        # Build strict payload item representing this snippet
        snippets.append(
            ExtractedSnippet(
                index=index,
                language=language,
                code=code,
                filename=filename,
                detection_method=detection_method,
                confidence=confidence,
            )
        )
        
    # Provide the finished list of well-formed snippet structures
    return snippets
