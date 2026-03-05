"""
Salesforce OAuth 2.0 Client Credentials authentication.

Uses the Connected App's client_id/client_secret for server-to-server auth.
No user interaction required.
"""

import logging
import requests

logger = logging.getLogger(__name__)


class SalesforceAuthError(Exception):
    """Raised when Salesforce authentication fails."""
    pass


class SalesforceClient:
    """Authenticated Salesforce REST API client."""

    def __init__(self, login_url: str, client_id: str, client_secret: str,
                 api_version: str = "v62.0"):
        self.login_url = login_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_version = api_version
        self.access_token = None
        self.instance_url = None
        self._session = requests.Session()

    def authenticate(self) -> None:
        """
        Authenticate via OAuth 2.0 Client Credentials flow.

        POST to /services/oauth2/token with grant_type=client_credentials.
        Stores access_token and instance_url for subsequent API calls.
        """
        token_url = f"{self.login_url}/services/oauth2/token"

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        logger.info("Authenticating to Salesforce at %s", self.login_url)

        try:
            resp = self._session.post(token_url, data=payload, timeout=30)
        except requests.RequestException as e:
            raise SalesforceAuthError(f"Network error during authentication: {e}")

        if resp.status_code != 200:
            error_msg = resp.json().get("error_description", resp.text) if resp.text else resp.reason
            raise SalesforceAuthError(
                f"Authentication failed (HTTP {resp.status_code}): {error_msg}"
            )

        data = resp.json()
        self.access_token = data["access_token"]
        self.instance_url = data["instance_url"].rstrip("/")

        # Set auth header for all future requests
        self._session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        })

        logger.info("Authenticated successfully. Instance: %s", self.instance_url)

    def get(self, path: str, params: dict = None) -> dict:
        """
        GET request to Salesforce REST API.

        Args:
            path: API path (e.g., /services/data/v62.0/analytics/reports/...)
            params: Optional query parameters

        Returns:
            Parsed JSON response
        """
        url = f"{self.instance_url}{path}"
        resp = self._session.get(url, params=params, timeout=120)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, body: dict = None) -> dict:
        """
        POST request to Salesforce REST API.

        Args:
            path: API path
            body: Optional JSON body

        Returns:
            Parsed JSON response
        """
        url = f"{self.instance_url}{path}"
        resp = self._session.post(url, json=body or {}, timeout=120)
        resp.raise_for_status()
        return resp.json()
