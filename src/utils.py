import re
import logging
import datetime
from urllib.parse import urlparse


def parse_confluence_url(url: str) -> tuple:
    """
    Parses a Confluence page URL and extracts the base URL and page ID.

    Supports:
        https://instance.atlassian.net/wiki/spaces/SPACE/pages/{pageId}/Title
        https://instance.atlassian.net/wiki/spaces/SPACE/pages/{pageId}

    Returns: (base_url, page_id)
    Raises ValueError if the page ID cannot be extracted.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(
            "ERROR: Could not extract a page ID from the URL.\n"
            "Expected format: https://instance.atlassian.net/wiki/spaces/SPACE/pages/{pageId}/Title\n"
            f"Received: {url}"
        )
    match = re.search(r'/pages/(\d+)', parsed.path)
    if not match:
        raise ValueError(
            "ERROR: Could not extract a page ID from the URL.\n"
            "Expected format: https://instance.atlassian.net/wiki/spaces/SPACE/pages/{pageId}/Title\n"
            f"Received: {url}"
        )
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    page_id = match.group(1)
    return base_url, page_id


def sanitize_attachment_filename(name: str) -> str:
    """
    Returns a safe, flat filename for use inside the export zip.

    Strips any directory components and rejects path traversal so a malicious
    attachment title (e.g. "../../evil" or "a/b") cannot escape the
    attachments/ folder or overwrite arbitrary files on extraction.
    """
    name = (name or "").strip()
    name = name.replace("\\", "/")
    name = name.split("/")[-1]
    name = "".join(ch for ch in name if ord(ch) >= 32 and ch not in '<>:"|?*')
    name = name.strip(". ")
    if not name or name in (".", ".."):
        name = "attachment"
    return name[:200]


def slugify(title: str) -> str:
    """
    Converts a page title to a URL-safe filename slug.
    """
    slug = title.lower()
    slug = slug.replace('&', 'and')
    slug = re.sub(r'[^a-z0-9\s\-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    slug = slug[:80].strip('-')
    if not slug:
        slug = 'page'
    return slug


def setup_logging(verbose: bool = False) -> None:
    """
    Configures the root logger.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def make_zip_name(root_title: str) -> str:
    """
    Generates the output zip filename: {slug}-{YYYY-MM-DD}.zip
    """
    date_str = datetime.date.today().strftime('%Y-%m-%d')
    return f"{slugify(root_title)}-{date_str}.zip"
