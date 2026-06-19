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
    Generates the meta-refresh redirect index.html for the export folder root.
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


def generate_start_here_html(package_dir_name: str) -> str:
    """
    Generates a root-level guidance page shown when opening the zip directly.
    """
    package_index = f"{package_dir_name}/index.html"
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Confluence Export - Start Here</title>
</head>
<body>
    <h1>Confluence Export Package</h1>
    <p><strong>Recommended (manual):</strong> copy the <code>{package_dir_name}</code> folder to any location, then open <code>index.html</code> inside that folder.</p>
    <p><strong>Auto-runner:</strong> run <code>Run-Export-Windows.cmd</code> (Windows) or <code>Run-Export-Mac.command</code> (macOS). It extracts to a temporary folder and opens the export automatically.</p>
    <p><strong>If already extracted:</strong> <a href="{package_index}">open the exported site</a>.</p>
</body>
</html>"""


def generate_start_here_txt(package_dir_name: str) -> str:
    """
    Generates a root-level plain-text quick-start guide.
    """
    return (
        "Confluence Export - START HERE\n"
        "==============================\n\n"
        "You can use this package in either of these ways:\n"
        f"1) Manual (recommended): copy the '{package_dir_name}' folder to any location and open 'index.html' inside that folder.\n"
        "2) Auto-runner:\n"
        "   - Windows: run 'Run-Export-Windows.cmd'\n"
        "   - macOS: run 'Run-Export-Mac.command'\n\n"
        "Both runners extract/copy the export to a temporary folder and open index.html automatically.\n"
    )


def generate_windows_launcher(package_dir_name: str) -> str:
    """
    Generates a Windows launcher that opens the export from a temporary folder.
    """
    return f"""@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PACKAGE_DIR_NAME={package_dir_name}"
set "TEMP_ROOT=%TEMP%\\confluence-export-%RANDOM%%RANDOM%"
set "TARGET_DIR=%TEMP_ROOT%\\%PACKAGE_DIR_NAME%"

echo Confluence export quick start:
echo   Manual: copy "%PACKAGE_DIR_NAME%" to any folder, then open index.html.
echo   Auto-runner: this script opens it automatically from a temp folder.
echo.

if exist "%SCRIPT_DIR%%PACKAGE_DIR_NAME%\\index.html" (
    robocopy "%SCRIPT_DIR%%PACKAGE_DIR_NAME%" "%TARGET_DIR%" /E /NFL /NDL /NJH /NJS /NC /NS >nul
    goto open_site
)

set "ARCHIVE_PATH="
for %%I in ("%CD%") do (
    if /I "%%~xI"==".zip" if exist "%%~fI" set "ARCHIVE_PATH=%%~fI"
)

if not defined ARCHIVE_PATH (
    echo Could not locate the export files automatically.
    echo Please extract the zip, copy "%PACKAGE_DIR_NAME%" to any folder, and open index.html.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath '%ARCHIVE_PATH%' -DestinationPath '%TEMP_ROOT%' -Force"

if errorlevel 1 (
    echo Automatic extraction failed.
    echo Please extract manually and open "%PACKAGE_DIR_NAME%\\index.html".
    pause
    exit /b 1
)

:open_site
if not exist "%TARGET_DIR%\\index.html" (
    echo Could not find "%TARGET_DIR%\\index.html".
    echo Please extract manually and open index.html.
    pause
    exit /b 1
)

start "" "%TARGET_DIR%\\index.html"
echo Opened "%TARGET_DIR%\\index.html"
endlocal
exit /b 0
"""


def generate_mac_launcher(package_dir_name: str) -> str:
    """
    Generates a macOS launcher that opens the export from a temporary folder.
    """
    return f"""#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PACKAGE_DIR_NAME="{package_dir_name}"
TEMP_ROOT="$(mktemp -d "${{TMPDIR:-/tmp}}/confluence-export.XXXXXX")"
TARGET_DIR="${{TEMP_ROOT}}/${{PACKAGE_DIR_NAME}}"

echo "Confluence export quick start:"
echo "  Manual: copy '${{PACKAGE_DIR_NAME}}' to any folder, then open index.html."
echo "  Auto-runner: this script opens it automatically from a temp folder."
echo

if [[ -f "${{SCRIPT_DIR}}/${{PACKAGE_DIR_NAME}}/index.html" ]]; then
    cp -R "${{SCRIPT_DIR}}/${{PACKAGE_DIR_NAME}}" "${{TARGET_DIR}}"
elif [[ "${{PWD}}" == *.zip && -f "${{PWD}}" ]]; then
    ditto -x -k "${{PWD}}" "${{TEMP_ROOT}}"
else
    echo "Could not locate the export files automatically."
    echo "Please extract the zip, copy '${{PACKAGE_DIR_NAME}}' to any folder, and open index.html."
    exit 1
fi

if [[ ! -f "${{TARGET_DIR}}/index.html" ]]; then
    echo "Could not find '${{TARGET_DIR}}/index.html'."
    echo "Please extract manually and open index.html."
    exit 1
fi

open "${{TARGET_DIR}}/index.html"
echo "Opened '${{TARGET_DIR}}/index.html'"
"""


def write_executable_file(zf: zipfile.ZipFile, path: str, content: str) -> None:
    """
    Writes a text file to the zip and marks it executable (Unix mode 755).
    """
    info = zipfile.ZipInfo(path)
    info.external_attr = 0o755 << 16
    zf.writestr(info, content)


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
    package_dir_name = f"{root_slug}-{date_str}"
    folder_prefix = f"{package_dir_name}/"

    if output_path is None:
        zip_path = output_dir / zip_name
    elif output_path.suffix.lower() == ".zip":
        zip_path = output_path
    else:
        zip_path = output_path / zip_name

    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("index.html", generate_start_here_html(package_dir_name))
        zf.writestr("START-HERE.html", generate_start_here_html(package_dir_name))
        zf.writestr("START-HERE.txt", generate_start_here_txt(package_dir_name))
        zf.writestr("Run-Export-Windows.cmd", generate_windows_launcher(package_dir_name))
        write_executable_file(
            zf,
            "Run-Export-Mac.command",
            generate_mac_launcher(package_dir_name),
        )
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
    print(
        "Open the zip and use START-HERE.* for guidance: either copy the export folder "
        "and open index.html manually, or run the OS launcher."
    )


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
