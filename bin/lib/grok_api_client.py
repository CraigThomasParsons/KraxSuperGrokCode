import os
import requests
from typing import Dict, Any, List, Optional


# Path to config.yaml relative to this module (bin/lib/ -> project root).
_CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml"))


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

        # Actual endpoint URLs may require manual updating by intercepting Network requests.
        self.base_url = "https://grok.com/rest/app-chat"

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

    def create_project(self, name: str, description: str = "") -> Dict[str, Any]:
        """
        Submits physical creation parameters to Grok.
        Returns the parsed JSON response including the project ID payload.
        """
        if not self.is_configured():
            raise ValueError("grok_session_cookie is unconfigured in config.yaml.")
            
        url = f"{self.base_url}/projects/create"
        payload = {
            "name": name,
            "description": description
        }

        # NOTE: This endpoint may change depending on Grok's internal GraphQL or REST topology 
        print(f"[GrokApiClient] Issuing project creation POST to {url}...")
        res = self.session.post(url, json=payload, timeout=10)
        
        try:
            res.raise_for_status()
            return res.json()
        except requests.exceptions.HTTPError as e:
            text = res.text
            raise RuntimeError(f"Grok API HTTP Error {res.status_code} during project creation: {text}") from e

    def list_projects(self) -> List[Dict[str, Any]]:
        """
        Retrieves existing projects to prevent blind duplicates.
        """
        if not self.is_configured():
            raise ValueError("grok_session_cookie is unconfigured in config.yaml.")
            
        url = f"{self.base_url}/projects"
        print(f"[GrokApiClient] Issuing project listing GET to {url}...")
        res = self.session.get(url, timeout=10)
        
        try:
            res.raise_for_status()
            data = res.json()
            # Depending on Grok's schema, it could be a raw array or nested inside 'data' or 'projects'
            return data.get("projects", data) if isinstance(data, dict) else data
        except requests.exceptions.HTTPError as e:
            text = res.text
            raise RuntimeError(f"Grok API HTTP Error {res.status_code} during project listing: {text}") from e

    def delete_project(self, project_id: str) -> bool:
        """
        Physically deletes or halts the specified workspace context.
        """
        if not self.is_configured():
            raise ValueError("grok_session_cookie is unconfigured in config.yaml.")
            
        url = f"{self.base_url}/projects/{project_id}"
        print(f"[GrokApiClient] Issuing project deletion DELETE to {url}...")
        res = self.session.delete(url, timeout=10)
        
        try:
            res.raise_for_status()
            return True
        except requests.exceptions.HTTPError as e:
            text = res.text
            raise RuntimeError(f"Grok API HTTP Error {res.status_code} during project deletion: {text}") from e

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
        Search existing Grok projects for a case-insensitive name match.

        Returns the first project dict whose name matches, or None if no
        match is found. Used by Stage 1 to prevent duplicate project creation
        when re-running the pipeline against the same Bridgit package.
        """
        existing_projects = self.list_projects()

        # Normalize the target name for comparison — Grok project names
        # may have been created with different casing than what Bridgit uses.
        normalized_target = project_name.strip().lower()

        for project_entry in existing_projects:
            # Grok's project response schema may use 'name' or 'title' — handle both.
            entry_name = project_entry.get("name", "") or project_entry.get("title", "")
            if entry_name.strip().lower() == normalized_target:
                return project_entry

        return None
