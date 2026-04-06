import os
import json
import requests
from typing import Dict, Any, List, Optional


# Path to config.yaml relative to this module (bin/lib/ -> project root).
_CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml"))

# Local registry of workspace IDs we've created. The Grok /rest/workspaces
# list endpoint always returns empty, so we track our own workspace mappings
# to prevent duplicate creation on subsequent sync runs.
_WORKSPACE_REGISTRY_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "grok_sync", "workspace_registry.json")
)


def _load_config() -> dict:
    """Read key-value pairs from config.yaml, skipping comments and blank lines."""
    config = {}

    if not os.path.exists(_CONFIG_PATH):
        return config

    with open(_CONFIG_PATH, "r", encoding="utf-8") as config_file:
        for raw_line in config_file:
            line = raw_line.strip()
            # Skip comment lines and empty lines.
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            config[key.strip()] = value.strip()

    return config


def _bootstrap_from_browser() -> Dict[str, str]:
    """
    One-time bootstrap: read Grok session cookies directly from Chrome's
    on-disk cookie database using browser_cookie3.

    This handles the cold-start scenario where the Chrome Extension hasn't
    pushed a cookie yet (e.g., first run, or extension not loaded). Once the
    extension starts its 1-minute refresh cycle, this function is never needed
    again — the extension keeps config.yaml fresh automatically.

    Returns a dict with 'cookie_string' and optionally 'device_id', or empty
    dict if the bootstrap fails (browser_cookie3 not installed, Chrome not
    found, no cookies, etc.).
    """
    try:
        import browser_cookie3
    except ImportError:
        # browser_cookie3 is an optional dependency — if it's not installed,
        # skip the bootstrap silently and let the health check report the issue.
        return {}

    try:
        # Read Chrome's SQLite cookie store for grok.com and x.com domains.
        # browser_cookie3 handles the decryption of Chrome's encrypted cookie values.
        cookie_jar = browser_cookie3.chrome(domain_name=".x.com")

        sso_value = ""
        sso_rw_value = ""

        for cookie in cookie_jar:
            if cookie.name == "sso":
                sso_value = cookie.value
            elif cookie.name == "sso-rw":
                sso_rw_value = cookie.value

        # Build the cookie string in the same format the Chrome Extension produces.
        cookie_parts = []
        if sso_value:
            cookie_parts.append(f"sso={sso_value}")
        if sso_rw_value:
            cookie_parts.append(f"sso-rw={sso_rw_value}")

        if not cookie_parts:
            # Also try grok.com domain in case cookies are set there directly.
            cookie_jar = browser_cookie3.chrome(domain_name="grok.com")
            for cookie in cookie_jar:
                if cookie.name == "sso":
                    cookie_parts.append(f"sso={cookie.value}")
                elif cookie.name == "sso-rw":
                    cookie_parts.append(f"sso-rw={cookie.value}")

        if cookie_parts:
            return {"cookie_string": "; ".join(cookie_parts)}

    except Exception as bootstrap_error:
        # Catch all browser_cookie3 errors (Chrome locked, permissions, etc.)
        # and fail silently — the Extension will take over once it's loaded.
        print(f"[GrokApiClient] browser_cookie3 bootstrap failed: {bootstrap_error}")

    return {}


class GrokApiClient:
    """
    Reverse-engineered Python driver for the internal grok.com backend API.
    Used for creating and managing Project environments autonomously so
    we do not have to rely on brittle UI DOM scraping.
    """
    def __init__(self):
        self.config = _load_config()
        self.session_cookie = self.config.get("grok_session_cookie", "").strip()
        self.device_id = self.config.get("grok_device_id", "").strip()

        # If no cookie is configured, attempt a one-time bootstrap from Chrome's
        # cookie store. This handles cold starts before the Extension is loaded.
        if not self._has_valid_cookie():
            bootstrap_result = _bootstrap_from_browser()
            if bootstrap_result.get("cookie_string"):
                self.session_cookie = bootstrap_result["cookie_string"]
                print(f"[GrokApiClient] Bootstrapped cookie from Chrome ({len(self.session_cookie)} chars)")
                # Persist the bootstrapped cookie to config.yaml so subsequent
                # GrokApiClient instances don't need to hit Chrome's DB again.
                self._save_cookie_to_config()

        # Grok Code Projects are "workspaces" in the REST API.
        # The base_url is used for conversations; workspaces have their own path.
        self.base_url = "https://grok.com/rest/app-chat"
        self.workspaces_url = "https://grok.com/rest/workspaces"

        self.session = requests.Session()
        self._setup_headers()

    def _has_valid_cookie(self) -> bool:
        """Check if the current cookie value is a real credential, not a placeholder."""
        return bool(self.session_cookie) and self.session_cookie != "YOUR_SSO_COOKIE_HERE"

    def _save_cookie_to_config(self) -> None:
        """
        Persist the current in-memory cookie to config.yaml.

        Used after browser_cookie3 bootstrap to save the extracted cookie so
        it survives across GrokApiClient instantiations.
        """
        if not os.path.exists(_CONFIG_PATH):
            return

        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as config_file:
                lines = config_file.readlines()

            updated = False
            output_lines = []
            for line in lines:
                if line.strip().startswith("grok_session_cookie:"):
                    output_lines.append(f"grok_session_cookie: {self.session_cookie}\n")
                    updated = True
                else:
                    output_lines.append(line)

            if not updated:
                output_lines.append(f"grok_session_cookie: {self.session_cookie}\n")

            temp_path = _CONFIG_PATH + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as temp_file:
                temp_file.writelines(output_lines)
            os.replace(temp_path, _CONFIG_PATH)

        except (OSError, IOError) as write_error:
            print(f"[GrokApiClient] Failed to save cookie to config: {write_error}")

    def _setup_headers(self):
        """Build the spoofed browser headers required to authorize internally."""
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": self.session_cookie,
            "x-device-id": self.device_id,
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/"
        })

    def is_configured(self) -> bool:
        """Safely checks if the user provided the physical auth tokens."""
        return self._has_valid_cookie()

    def reload_config(self) -> bool:
        """
        Hot-reload credentials from config.yaml without restarting the server.

        Called by the /api/cookie/update endpoint after the Chrome Extension
        pushes fresh cookies. Returns True if the cookie actually changed,
        False if the config was already up-to-date.
        """
        fresh_config = _load_config()
        new_cookie = fresh_config.get("grok_session_cookie", "").strip()
        new_device_id = fresh_config.get("grok_device_id", "").strip()

        # Check if anything actually changed to avoid unnecessary header rebuilds.
        cookie_changed = new_cookie != self.session_cookie
        device_changed = new_device_id != self.device_id

        if cookie_changed or device_changed:
            self.config = fresh_config
            self.session_cookie = new_cookie
            self.device_id = new_device_id
            # Rebuild the session headers with the fresh credentials.
            self._setup_headers()
            return True

        return False

    def create_project(self, name: str, instructions: str = "") -> Dict[str, Any]:
        """
        Create a new Grok Code Project (workspace) via the REST API.

        Returns the parsed JSON response including the workspaceId. Also saves
        the workspace ID to the local registry so find_project_by_name() can
        locate it on subsequent runs (the Grok list endpoint always returns empty).

        The 'instructions' parameter maps to Grok's 'customPersonality' field,
        which is what the UI shows as "Instructions" in the project settings.
        """
        if not self.is_configured():
            raise ValueError("grok_session_cookie is unconfigured in config.yaml.")

        # Grok Code Projects are "workspaces" in the REST API.
        # The 'customPersonality' field is the Instructions text shown in the UI.
        url = self.workspaces_url
        payload = {"name": name}

        # Attach the Instructions content if provided by the pipeline.
        if instructions:
            payload["customPersonality"] = instructions

        print(f"[GrokApiClient] Creating workspace '{name}' via POST {url}...")
        res = self.session.post(url, json=payload, timeout=10)

        try:
            res.raise_for_status()
            workspace_data = res.json()

            # Save the mapping to our local registry since the Grok list
            # endpoint doesn't return user-created workspaces.
            workspace_id = workspace_data.get("workspaceId", "")
            if workspace_id:
                self._save_to_registry(name, workspace_id)

            return workspace_data
        except requests.exceptions.HTTPError as http_error:
            response_text = res.text
            raise RuntimeError(
                f"Grok API HTTP Error {res.status_code} during workspace creation: {response_text}"
            ) from http_error

    def get_project(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single workspace by its ID.

        Returns the workspace dict if it exists, or None if the ID is invalid
        or the workspace has been deleted. This is the primary way to verify
        a workspace still exists since the list endpoint is unreliable.
        """
        if not self.is_configured():
            raise ValueError("grok_session_cookie is unconfigured in config.yaml.")

        url = f"{self.workspaces_url}/{workspace_id}"
        print(f"[GrokApiClient] Fetching workspace {workspace_id}...")
        res = self.session.get(url, timeout=10)

        if res.status_code == 404:
            return None

        try:
            res.raise_for_status()
            return res.json()
        except requests.exceptions.HTTPError as http_error:
            response_text = res.text
            raise RuntimeError(
                f"Grok API HTTP Error {res.status_code} fetching workspace: {response_text}"
            ) from http_error

    def list_projects(self) -> List[Dict[str, Any]]:
        """
        List known Grok workspaces from the local registry.

        The Grok /rest/workspaces GET endpoint always returns empty for
        user-created workspaces, so we maintain a local registry that maps
        project names to workspace IDs. Each entry is verified by GET to
        confirm the workspace still exists before being returned.
        """
        if not self.is_configured():
            raise ValueError("grok_session_cookie is unconfigured in config.yaml.")

        # Load the local registry of workspaces we've created.
        registry = self._load_registry()
        verified_workspaces = []

        # Verify each registered workspace still exists on Grok's side.
        for project_name, workspace_id in registry.items():
            workspace_data = self.get_project(workspace_id)
            if workspace_data is not None:
                verified_workspaces.append(workspace_data)

        return verified_workspaces

    def delete_project(self, workspace_id: str) -> bool:
        """
        Delete a Grok workspace by its ID.

        Also removes the entry from the local registry to keep it clean.
        """
        if not self.is_configured():
            raise ValueError("grok_session_cookie is unconfigured in config.yaml.")

        url = f"{self.workspaces_url}/{workspace_id}"
        print(f"[GrokApiClient] Deleting workspace {workspace_id}...")
        res = self.session.delete(url, timeout=10)

        try:
            res.raise_for_status()
            # Remove from local registry.
            self._remove_from_registry(workspace_id)
            return True
        except requests.exceptions.HTTPError as http_error:
            response_text = res.text
            raise RuntimeError(
                f"Grok API HTTP Error {res.status_code} during workspace deletion: {response_text}"
            ) from http_error

    def update_instructions(self, workspace_id: str, instructions: str, name: str = "") -> Dict[str, Any]:
        """
        Update the Instructions (customPersonality) on an existing workspace.

        Grok's PUT endpoint requires the workspace name to be included in every
        update, so we fetch the current workspace data first to preserve the
        existing name unless a new one is explicitly provided.

        Returns the updated workspace dict from the API.
        """
        if not self.is_configured():
            raise ValueError("grok_session_cookie is unconfigured in config.yaml.")

        # Fetch current workspace data to preserve the name field.
        # Grok's PUT replaces all editable fields, so we must include the name.
        if not name:
            current_data = self.get_project(workspace_id)
            if current_data is None:
                raise RuntimeError(f"Workspace {workspace_id} not found — cannot update instructions.")
            name = current_data.get("name", "")

        url = f"{self.workspaces_url}/{workspace_id}"
        payload = {
            "name": name,
            "customPersonality": instructions,
        }

        print(f"[GrokApiClient] Updating instructions on workspace {workspace_id} ({len(instructions)} chars)...")
        res = self.session.put(url, json=payload, timeout=15)

        try:
            res.raise_for_status()
            return res.json()
        except requests.exceptions.HTTPError as http_error:
            response_text = res.text
            raise RuntimeError(
                f"Grok API HTTP Error {res.status_code} during instructions update: {response_text}"
            ) from http_error

    def health_check(self) -> bool:
        """
        Verifies connectivity to the Grok API by attempting to list conversations.

        Returns False on authentication failures (401/403), network errors,
        or expired session cookies. Call this before any stage operations to
        provide a clear "cookie expired" message rather than cryptic HTTP
        errors mid-pipeline.

        Uses the /conversations endpoint rather than /projects because the
        project API endpoints haven't been fully discovered yet, but the
        conversations endpoint is known to work with cookie auth.
        """
        if not self.is_configured():
            return False

        try:
            # Use conversations endpoint for health check since it's confirmed working.
            url = f"{self.base_url}/conversations"
            res = self.session.get(url, timeout=10)
            res.raise_for_status()
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            return False
        except requests.exceptions.HTTPError:
            return False

    def find_project_by_name(self, project_name: str) -> Optional[Dict[str, Any]]:
        """
        Search for an existing Grok workspace by project name.

        First checks the local registry (fast, no API call), then verifies
        the workspace still exists on Grok's side via GET. Returns the
        workspace dict if found, or None if no match exists.

        Also handles the case where the user manually created a project in
        the Grok UI and added it to the registry via config or prior sync.
        """
        # Check the local registry first — this is the primary lookup path
        # since Grok's list endpoint doesn't return user-created workspaces.
        registry = self._load_registry()
        normalized_target = project_name.strip().lower()

        for registered_name, workspace_id in registry.items():
            if registered_name.strip().lower() == normalized_target:
                # Verify the workspace still exists on Grok's side.
                workspace_data = self.get_project(workspace_id)
                if workspace_data is not None:
                    return workspace_data
                else:
                    # Workspace was deleted on Grok's side — remove stale entry.
                    print(f"[GrokApiClient] Stale registry entry for '{registered_name}' — removing.")
                    self._remove_from_registry(workspace_id)

        return None

    # ─────────────────────────────────────────────────────
    # Local workspace registry — tracks name→ID mappings
    # ─────────────────────────────────────────────────────

    def _load_registry(self) -> Dict[str, str]:
        """
        Load the workspace registry from grok_sync/workspace_registry.json.

        Returns a dict mapping project names to workspace IDs. Returns empty
        dict if the file doesn't exist or is corrupted.
        """
        if not os.path.isfile(_WORKSPACE_REGISTRY_PATH):
            return {}

        try:
            with open(_WORKSPACE_REGISTRY_PATH, "r", encoding="utf-8") as registry_file:
                data = json.load(registry_file)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_registry(self, registry: Dict[str, str]) -> None:
        """
        Persist the workspace registry to grok_sync/workspace_registry.json.

        Uses atomic write (write to .tmp then rename) to prevent corruption
        if the process is interrupted mid-write.
        """
        # Ensure the parent directory exists.
        registry_dir = os.path.dirname(_WORKSPACE_REGISTRY_PATH)
        os.makedirs(registry_dir, exist_ok=True)

        temp_path = _WORKSPACE_REGISTRY_PATH + ".tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as temp_file:
                json.dump(registry, temp_file, indent=2)
            os.replace(temp_path, _WORKSPACE_REGISTRY_PATH)
        except (OSError, IOError) as write_error:
            print(f"[GrokApiClient] Failed to save workspace registry: {write_error}")

    def _save_to_registry(self, project_name: str, workspace_id: str) -> None:
        """Add or update a project→workspace mapping in the local registry."""
        registry = self._load_registry()
        registry[project_name] = workspace_id
        self._save_registry(registry)
        print(f"[GrokApiClient] Registered workspace: {project_name} -> {workspace_id}")

    def _remove_from_registry(self, workspace_id: str) -> None:
        """Remove a workspace from the registry by its ID."""
        registry = self._load_registry()
        # Find and remove the entry with matching workspace ID.
        updated_registry = {
            name: wid for name, wid in registry.items() if wid != workspace_id
        }
        if len(updated_registry) < len(registry):
            self._save_registry(updated_registry)
