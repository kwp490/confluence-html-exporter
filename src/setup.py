"""
Interactive credential setup and validation for confluence-html-exporter.

When required environment variables are missing or invalid, this module
guides the user through entering them interactively and writes a .env file.
Credentials are never logged or echoed to the terminal.
"""

import getpass
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

REQUIRED_KEYS = ["CONFLUENCE_BASE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN"]

# Validation helpers --------------------------------------------------------

def _validate_base_url(value: str) -> str | None:
    """Returns an error message if *value* is not a valid Confluence base URL.

    Only https:// is accepted. Basic Auth credentials are sent on every
    request, so the connection must always be encrypted; plain http:// is
    rejected unconditionally with no override.
    """
    value = value.strip().rstrip("/")
    if not value:
        return "Base URL cannot be empty."
    parsed = urlparse(value)
    if parsed.scheme != "https":
        return (
            "URL must start with https://. Plain http:// is not allowed because "
            "credentials would be sent unencrypted."
        )
    if not parsed.netloc or "." not in parsed.netloc:
        return "URL does not look like a valid hostname."
    if parsed.path and parsed.path != "/":
        return "Provide the root URL only (no /wiki path). Example: https://example.atlassian.net"
    return None


def _validate_email(value: str) -> str | None:
    """Returns an error message if *value* is not plausibly an email address."""
    value = value.strip()
    if not value:
        return "Email cannot be empty."
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
        return "That does not look like a valid email address."
    return None


def _validate_api_token(value: str) -> str | None:
    """Returns an error message if *value* looks empty or implausibly short."""
    value = value.strip()
    if not value:
        return "API token cannot be empty."
    if len(value) < 8:
        return "Token seems too short. Atlassian tokens are typically 24+ characters."
    return None


VALIDATORS = {
    "CONFLUENCE_BASE_URL": _validate_base_url,
    "CONFLUENCE_EMAIL": _validate_email,
    "CONFLUENCE_API_TOKEN": _validate_api_token,
}


# Live credential test ------------------------------------------------------

def _test_credentials(base_url: str, email: str, token: str) -> str | None:
    """
    Makes a lightweight authenticated request to the Confluence API.
    Returns None on success or an error message on failure.
    """
    url = f"{base_url.rstrip('/')}/wiki/api/v2/spaces?limit=1"
    try:
        resp = requests.get(
            url,
            auth=(email, token),
            headers={
                "Accept": "application/json",
                "User-Agent": "confluence-html-exporter/1.0",
            },
            timeout=15,
        )
    except requests.ConnectionError:
        return f"Could not connect to {base_url}. Check the URL and your network."
    except requests.Timeout:
        return f"Connection to {base_url} timed out."
    except requests.RequestException as exc:
        return f"Connection error: {exc}"

    if resp.status_code == 401:
        return "Authentication failed (HTTP 401). Check your email and API token."
    if resp.status_code == 403:
        return "Access denied (HTTP 403). Your token may lack read permissions."
    if resp.status_code >= 400:
        return f"Unexpected response from Confluence (HTTP {resp.status_code})."
    return None


# .env file I/O -------------------------------------------------------------

def _read_env_file() -> dict:
    """Reads existing .env key=value pairs (if the file exists)."""
    values = {}
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip()
    return values


def _write_env_file(values: dict) -> None:
    """Writes the .env file with restrictive permissions where possible."""
    lines = [f"{k}={v}" for k, v in values.items()]
    content = "\n".join(lines) + "\n"

    ENV_FILE.write_text(content, encoding="utf-8")

    # Restrict file permissions on Unix (owner read/write only)
    try:
        ENV_FILE.chmod(0o600)
    except (OSError, AttributeError):
        pass  # Windows doesn't support Unix permissions


# Interactive prompts --------------------------------------------------------

_PROMPTS = {
    "CONFLUENCE_BASE_URL": (
        "Confluence base URL (e.g. https://example.atlassian.net): ",
        False,
    ),
    "CONFLUENCE_EMAIL": (
        "Atlassian account email: ",
        False,
    ),
    "CONFLUENCE_API_TOKEN": (
        "Confluence API token (input hidden): ",
        True,  # Use getpass  do not echo
    ),
}

_PLACEHOLDER_PATTERNS = [
    "your_api_token_here",
    "your-instance",
    "you@example.com",
    "user@example.com",
    "example.atlassian.net",
]


def _is_placeholder(value: str) -> bool:
    """Returns True if the value looks like a template placeholder."""
    lower = value.strip().lower()
    return any(p in lower for p in _PLACEHOLDER_PATTERNS)


def _prompt_for_key(key: str, current: str | None) -> str:
    """Interactively prompts the user for a single credential value."""
    prompt_text, is_secret = _PROMPTS[key]
    validator = VALIDATORS.get(key)

    while True:
        if is_secret:
            value = getpass.getpass(prompt_text)
        else:
            value = input(prompt_text)

        value = value.strip()
        if not value:
            print("  Value cannot be empty. Please try again.", file=sys.stderr)
            continue

        if validator:
            err = validator(value)
            if err:
                print(f"  {err}", file=sys.stderr)
                continue

        return value


# Public API -----------------------------------------------------------------

def ensure_config() -> dict:
    """
    Checks that all required credentials exist and are valid.

    If any are missing, look like placeholders, or fail format validation,
    the user is prompted interactively. After collecting values, a live
    authentication test is performed against the Confluence API before
    writing the .env file.

    Returns a dict of {key: value} for all required keys.

    Raises SystemExit if stdin is not a TTY (non-interactive) and
    credentials are incomplete.
    """
    existing = _read_env_file()

    # Merge with environment (env vars take precedence over .env file values,
    # but we only persist to .env)
    config = {}
    needs_input = []
    for key in REQUIRED_KEYS:
        val = os.environ.get(key) or existing.get(key) or ""
        validator = VALIDATORS.get(key)
        if not val or _is_placeholder(val) or (validator and validator(val)):
            needs_input.append(key)
        else:
            config[key] = val

    if not needs_input:
        return config

    # Non-interactive: cannot prompt
    if not sys.stdin.isatty():
        for key in needs_input:
            print(f"ERROR: Missing or invalid: {key}", file=sys.stderr)
        print(
            "Set the variables in your .env file or environment, or run "
            "interactively to use the setup wizard.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Interactive setup
    print(
        "\n"
        "==================== Credential Setup ====================\n"
        " Some required credentials are missing or invalid.\n"
        " You will be guided through setting them now.\n"
        " Values are saved to .env (git-ignored) and never logged.\n"
        "\n"
        " To generate an API token, visit:\n"
        " https://id.atlassian.com/manage-profile/security/api-tokens\n"
        "==========================================================\n",
        file=sys.stderr,
    )

    for key in needs_input:
        current = os.environ.get(key) or existing.get(key) or None
        if current and not _is_placeholder(current):
            print(f"  {key} has a value but it failed validation.", file=sys.stderr)
        config[key] = _prompt_for_key(key, current)

    # Live test before saving
    print("\nTesting credentials against Confluence API...", file=sys.stderr)
    err = _test_credentials(
        config["CONFLUENCE_BASE_URL"],
        config["CONFLUENCE_EMAIL"],
        config["CONFLUENCE_API_TOKEN"],
    )
    if err:
        print(f"\n  ERROR: {err}", file=sys.stderr)
        print(
            "  Credentials were NOT saved. Fix the issue and try again.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("  Authentication successful!\n", file=sys.stderr)

    # Persist to .env
    env_values = _read_env_file()
    env_values.update(config)
    _write_env_file(env_values)
    print(f"  Credentials saved to {ENV_FILE}", file=sys.stderr)

    # Also inject into current process environment
    for key, val in config.items():
        os.environ[key] = val

    return config
