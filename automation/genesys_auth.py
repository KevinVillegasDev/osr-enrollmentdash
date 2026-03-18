"""
Genesys Cloud OAuth 2.0 Client Credentials authentication.

Uses the OAuth client's client_id/client_secret for server-to-server auth.
No user interaction required — same pattern as Salesforce auth.
"""

import logging
import requests
from base64 import b64encode

logger = logging.getLogger(__name__)


class GenesysAuthError(Exception):
    """Raised when Genesys Cloud authentication fails."""
    pass


class GenesysClient:
    """Authenticated Genesys Cloud REST API client."""

    def __init__(self, region: str, client_id: str, client_secret: str):
        """
        Args:
            region: Genesys Cloud region domain (e.g., 'usw2.pure.cloud')
            client_id: OAuth Client ID
            client_secret: OAuth Client Secret
        """
        self.region = region.strip().rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self._session = requests.Session()

    @property
    def login_url(self) -> str:
        return f"https://login.{self.region}"

    @property
    def api_url(self) -> str:
        return f"https://api.{self.region}"

    def authenticate(self) -> None:
        """
        Authenticate via OAuth 2.0 Client Credentials flow.

        POST to /oauth/token with grant_type=client_credentials.
        Uses HTTP Basic Auth (base64-encoded client_id:client_secret).
        """
        token_url = f"{self.login_url}/oauth/token"

        # Genesys requires Basic auth header with base64(client_id:client_secret)
        credentials = b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        payload = {
            "grant_type": "client_credentials",
        }

        logger.info("Authenticating to Genesys Cloud at %s", self.login_url)

        try:
            resp = self._session.post(
                token_url, data=payload, headers=headers, timeout=30
            )
        except requests.RequestException as e:
            raise GenesysAuthError(f"Network error during authentication: {e}")

        if resp.status_code != 200:
            error_msg = resp.text[:500] if resp.text else resp.reason
            raise GenesysAuthError(
                f"Authentication failed (HTTP {resp.status_code}): {error_msg}"
            )

        data = resp.json()
        self.access_token = data["access_token"]

        # Set auth header for all future requests
        self._session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        })

        logger.info("Genesys Cloud authenticated successfully (region: %s)", self.region)

    def get(self, path: str, params: dict = None) -> dict:
        """GET request to Genesys Cloud API."""
        url = f"{self.api_url}{path}"
        logger.debug("GET %s params=%s", url, params)
        resp = self._session.get(url, params=params, timeout=60)
        if not resp.ok:
            logger.error("GET %s failed (%d): %s", path, resp.status_code, resp.text[:500])
            resp.raise_for_status()
        return resp.json()

    def post(self, path: str, body: dict = None) -> dict:
        """POST request to Genesys Cloud API."""
        url = f"{self.api_url}{path}"
        logger.debug("POST %s", url)
        resp = self._session.post(url, json=body or {}, timeout=60)
        if not resp.ok:
            logger.error("POST %s failed (%d): %s", path, resp.status_code, resp.text[:500])
            resp.raise_for_status()
        return resp.json()
