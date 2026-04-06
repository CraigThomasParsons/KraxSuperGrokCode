import os
import requests
from typing import Dict, Any, List, Optional

def _load_config() -> dict:
    config = {}
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml"))
    
    if not os.path.exists(config_path):
        return config
    
    with open(config_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            config[key.strip()] = value.strip()
            
    return config

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
        
        # NOTE: Actual endpoint URLs may require manual updating by intercepting Network requests
        self.base_url = "https://grok.com/rest/app-chat"

        self.session = requests.Session()
        self._setup_headers()

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
        return bool(self.session_cookie) and self.session_cookie != "YOUR_SSO_COOKIE_HERE"

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
        Verifies connectivity to the Grok API by attempting to list projects.

        Returns False on authentication failures (401/403), network errors,
        or expired session cookies. Call this before any stage operations to
        provide a clear "cookie expired" message rather than cryptic HTTP
        errors mid-pipeline.
        """
        if not self.is_configured():
            return False

        try:
            self.list_projects()
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            return False
        except RuntimeError:
            # RuntimeError is raised by list_projects on HTTP errors (401, 403, etc.)
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
