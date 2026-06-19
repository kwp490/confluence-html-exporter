import requests
import time
import logging
from urllib.parse import urljoin, urlparse


class ConfluenceClient:
    """
    Authenticated Confluence REST API v2 client.
    Handles retries, pagination, and binary downloads.
    """

    def __init__(self, base_url: str, email: str, api_token: str) -> None:
        self.base_url = base_url.rstrip('/')
        self.email = email
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "confluence-html-exporter/1.0",
        })

    def get_page(self, page_id: str) -> dict:
        """
        Fetches a single page with rendered HTML body.
        """
        url = f"{self.base_url}/wiki/api/v2/pages/{page_id}?body-format=export_view"
        response = self._request_with_retry("GET", url)
        return response.json()

    def get_children(self, page_id: str) -> list:
        """
        Fetches all direct children of a page or folder, handling pagination.
        """
        results = []
        url = f"{self.base_url}/wiki/api/v2/pages/{page_id}/children?limit=250"
        while url:
            response = self._request_with_retry("GET", url)
            data = response.json()
            results.extend(data.get("results", []))
            next_link = data.get("_links", {}).get("next")
            if next_link:
                url = urljoin(self.base_url, next_link)
            else:
                url = None
        return results

    def get_attachments(self, page_id: str) -> list:
        """
        Fetches all attachments for a page, handling pagination.
        """
        results = []
        url = f"{self.base_url}/wiki/api/v2/pages/{page_id}/attachments?limit=250"
        while url:
            response = self._request_with_retry("GET", url)
            data = response.json()
            results.extend(data.get("results", []))
            next_link = data.get("_links", {}).get("next")
            if next_link:
                url = urljoin(self.base_url, next_link)
            else:
                url = None
        return results

    def download_attachment(self, download_link: str) -> bytes:
        """
        Downloads an attachment using a Confluence REST ``_links.download`` path.

        These links (e.g. ``/rest/api/content/{id}/child/attachment/{att}/download``)
        are returned relative to the Confluence context root, which on Confluence
        Cloud is ``/wiki``. The raw image ``src`` values found in exported page HTML
        (``/wiki/download/attachments/...``) reject API-token authentication with a
        401, whereas these REST download links authenticate correctly, so the
        context prefix is restored here when it is missing.
        """
        if download_link.startswith("http"):
            url = download_link
        else:
            link = "/" + download_link.lstrip("/")
            if not link.startswith("/wiki/"):
                link = "/wiki" + link
            url = self.base_url + link
        return self.download_binary(url)

    def download_binary(self, path_or_url: str) -> bytes:
        """
        Downloads a binary resource (image or file).

        Credentials (HTTP Basic Auth) are only ever sent to the configured
        Confluence host. Absolute URLs pointing at any other host are fetched
        without authentication so the API token can never leak to a third party.
        """
        if path_or_url.startswith("http"):
            url = path_or_url
        else:
            url = urljoin(self.base_url + "/", path_or_url.lstrip("/"))

        if self._is_confluence_host(url):
            response = self._request_with_retry("GET", url)
            return response.content

        logging.warning(
            f"Downloading from non-Confluence host without authentication: {url}"
        )
        response = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "confluence-html-exporter/1.0"},
        )
        response.raise_for_status()
        return response.content

    def _is_confluence_host(self, url: str) -> bool:
        """
        Returns True if the URL targets the configured Confluence instance.
        """
        return urlparse(url).netloc == urlparse(self.base_url).netloc

    def _request_with_retry(
        self,
        method: str,
        url: str,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        **kwargs
    ) -> requests.Response:
        """
        Wraps requests.Session.request with retry logic.
        """
        for attempt in range(max_retries + 1):
            response = self.session.request(method, url, timeout=30, **kwargs)
            if response.status_code == 429:
                wait = int(response.headers.get('Retry-After', 10))
                logging.warning(
                    f"Rate limited. Waiting {wait}s before retry {attempt + 1}/{max_retries}."
                )
                time.sleep(wait)
                continue
            if response.status_code in (500, 502, 503, 504) and attempt < max_retries:
                wait = backoff_factor ** attempt
                logging.warning(
                    f"Server error {response.status_code}. Retrying in {wait}s."
                )
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response
        raise requests.HTTPError(
            f"Request to {url} failed after {max_retries} retries."
        )
