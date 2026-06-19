#!/usr/bin/env python3
"""
confluence-html-exporter

Exports a Confluence page and all of its child pages into a self-contained,
navigable HTML package delivered as a .zip file.
"""

import argparse
import datetime
import logging
import os
import sys
import zipfile
from pathlib import Path

import requests
from dotenv import load_dotenv

from src.api import ConfluenceClient
from src.renderer import HTMLRenderer
from src.tree import PageTreeBuilder
from src.setup import ensure_config
from src.utils import parse_confluence_url, setup_logging




def confirm_export(assume_yes: bool = False) -> None:
    """
    Warns the user that the export may include confidential pages and file
    attachments, and requires explicit confirmation before proceeding.
    """
    warning = (
        "\n"
        "============================ WARNING ============================\n"
        " This tool exports Confluence pages AND their file attachments into\n"
        " a self-contained, shareable .zip with NO access controls.\n"
        "\n"
        " The export may contain CONFIDENTIAL or SENSITIVE information.\n"
        " Title-based filtering (skipping 'deprecated'/'internal') is NOT a\n"
        " security control and may miss restricted content.\n"
        "\n"
        " Review the generated package before sharing it with anyone who\n"
        " does not already have access to this Confluence content.\n"
        "================================================================\n"
    )
    # Printed to stdout (not stderr) so shells like PowerShell don't render
    # this informational banner as a red "error".
    print(warning, file=sys.stdout)

    if assume_yes:
        return

    if not sys.stdin.isatty():
        print(
            "Refusing to export without confirmation. Re-run with --yes to proceed "
            "non-interactively.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        response = input("Type 'yes' to continue with the export: ").strip().lower()
    except EOFError:
        response = ""
    if response not in ("y", "yes"):
        print("Export cancelled.", file=sys.stdout)
        raise SystemExit(1)


def generate_index_html(root_page: dict) -> str:
    """
    Generates the meta-refresh redirect index.html for the zip root.
    """
    target = root_page["html_filename"]
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="0;url={target}">
    <title>Redirecting...</title>
</head>
<body>
    <p>Loading... <a href="{target}">Click here if not redirected.</a></p>
</body>
</html>"""


def build_zip(pages: list, root_slug: str, output_dir: Path, output_path: Path = None) -> Path:
    """
    Assembles the final zip file from rendered HTML pages and attachments.

    output_path (optional): a user-specified destination. It may be either:
        - a directory: the zip is written inside it using the default name.
        - a full file path ending in .zip: used verbatim as the output file.
    If output_path is None, the zip is written to output_dir using the default name.
    Any missing parent directories are created.
    """
    date_str = datetime.date.today().strftime('%Y-%m-%d')
    zip_name = f"{root_slug}-{date_str}.zip"
    folder_prefix = f"{root_slug}-{date_str}/"

    if output_path is None:
        zip_path = output_dir / zip_name
    elif output_path.suffix.lower() == ".zip":
        zip_path = output_path
    else:
        zip_path = output_path / zip_name

    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(folder_prefix + "index.html", generate_index_html(pages[0]))

        for page in pages:
            zf.writestr(
                folder_prefix + page["html_filename"],
                page["rendered_html"],
            )

        written_attachments = set()
        for page in pages:
            for filename, file_bytes in page.get("attachment_files", {}).items():
                if filename not in written_attachments:
                    zf.writestr(folder_prefix + f"attachments/{filename}", file_bytes)
                    written_attachments.add(filename)

    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a Confluence page tree to a self-contained HTML zip."
    )
    parser.add_argument("url", help="Confluence page URL to export")
    parser.add_argument(
        "-o",
        "--output",
        help=(
            "Where to save the .zip file. May be a directory (the zip is saved "
            "inside it using the default name) or a full file path ending in .zip. "
            "Missing directories are created. Defaults to the current directory."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the confidential-data confirmation prompt (for non-interactive use).",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)
    load_dotenv()

    confirm_export(args.yes)

    config = ensure_config()

    try:
        base_url, root_page_id = parse_confluence_url(args.url)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

    # base_url from env takes precedence for API calls; fall back to URL-derived
    api_base_url = config["CONFLUENCE_BASE_URL"].rstrip('/') or base_url

    client = ConfluenceClient(
        api_base_url,
        config["CONFLUENCE_EMAIL"],
        config["CONFLUENCE_API_TOKEN"],
    )

    builder = PageTreeBuilder(client)

    try:
        pages = builder.build(root_page_id)
    except requests.HTTPError as exc:
        _handle_http_error(exc, root_page_id)
        raise SystemExit(1)

    if not pages:
        print(
            "No exportable pages found after filtering. Check the URL and filter rules.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print(f"Found {len(pages)} pages to export (after filtering)")

    renderer = HTMLRenderer(client, api_base_url)
    pages = renderer.render_all(pages)

    root_slug = pages[0]["slug"]
    output_path = Path(args.output).expanduser() if args.output else None
    zip_path = build_zip(pages, root_slug, Path.cwd(), output_path)

    print(f"Export complete: {zip_path}")


def _handle_http_error(exc: requests.HTTPError, page_id: str) -> None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status == 401:
        print(
            "Authentication failed. Check CONFLUENCE_EMAIL and CONFLUENCE_API_TOKEN.",
            file=sys.stderr,
        )
    elif status == 404:
        print(f"Page {page_id} not found or you do not have access.", file=sys.stderr)
    else:
        print(f"Request failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
