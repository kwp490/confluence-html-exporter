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
    <style>
        body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
        .option {{ border: 1px solid #ddd; border-radius: 8px; padding: 1rem 1.25rem; margin: 1rem 0; }}
        h2 {{ margin-top: 0; }}
        code {{ background: #f4f4f4; padding: 0.1rem 0.3rem; border-radius: 4px; }}
        .note {{ color: #555; font-size: 0.9rem; }}
        .tip {{ background: #fff8e1; border: 1px solid #ffe082; border-radius: 6px; padding: 0.75rem 1rem; }}
    </style>
</head>
<body>
    <h1>Confluence Export Package</h1>
    <p class="tip">If you are reading this from inside the zip window, first <strong>extract / unzip the package</strong> (Windows: <em>Extract All</em>; macOS: double-click the zip). Then use one of the two options below. Launchers and links cannot run while still inside the zip.</p>
    <p>Choose one of the two options below to view this exported Confluence content.</p>

    <div class="option">
        <h2>Option 1 &mdash; Auto-extract and open</h2>
        <p>Double-click the launcher for your operating system. It opens the export automatically in your browser:</p>
        <ul>
            <li>Windows: <code>Run-Export-Windows.cmd</code></li>
            <li>macOS: <code>Run-Export-Mac.command</code></li>
        </ul>
        <p class="note">Double-click the launcher file directly (in the extracted folder, or in the zip window). Depending on your browser or OS security settings, you may need to confirm a prompt, or right-click the launcher and choose <em>Open</em>.</p>
    </div>

    <div class="option">
        <h2>Option 2 &mdash; Manual</h2>
        <p>Copy the <code>{package_dir_name}</code> folder to any location on your computer, then open <code>index.html</code> inside that folder.</p>
        <p class="note">If you have already extracted this package, you can <a href="{package_index}">open the exported site</a> directly.</p>
    </div>
</body>
</html>"""


def generate_start_here_txt(package_dir_name: str) -> str:
    """
    Generates a root-level plain-text quick-start guide.
    """
    return (
        "Confluence Export - START HERE\n"
        "==============================\n\n"
        "TIP: If you are viewing this from inside the zip, extract / unzip\n"
        "the package first (Windows: 'Extract All'; macOS: double-click the\n"
        "zip). Then use one of the two options below.\n\n"
        "Choose ONE of the two options below.\n\n"
        "------------------------------------------------------------\n"
        "OPTION 1 - Auto-extract and open\n"
        "------------------------------------------------------------\n"
        "Double-click the launcher for your operating system. It opens\n"
        "index.html in your browser for you:\n"
        "   - Windows: run 'Run-Export-Windows.cmd'\n"
        "   - macOS:   run 'Run-Export-Mac.command'\n\n"
        "------------------------------------------------------------\n"
        "OPTION 2 - Manual\n"
        "------------------------------------------------------------\n"
        f"Copy the '{package_dir_name}' folder to any location on your\n"
        "computer, then open 'index.html' inside that folder.\n"
    )


def generate_windows_launcher(package_dir_name: str) -> str:
    """
    Generates a Windows launcher that opens the export from a temporary folder.

    Works both when run from an already-extracted folder (sibling export folder
    present) and when double-clicked from inside the Windows zip viewer, in which
    case only this .cmd is extracted to a temp folder. In that situation the
    launcher locates the original .zip (e.g. in Downloads/Desktop/Documents) and
    extracts it automatically.
    """
    template = r"""@echo off
setlocal EnableExtensions
set "PKG=__PKG__"
set "SCRIPTDIR=%~dp0"

echo ============================================================
echo  Confluence Export - How to open this package
echo ============================================================
echo.
echo  OPTION 1 - Auto-extract and open ^(this runner^)
echo    Extracts the export to a temporary folder and opens
echo    index.html in your browser automatically.
echo.
echo  OPTION 2 - Manual
echo    Copy the "%PKG%" folder to any location, then open
echo    index.html inside that folder.
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $pkg=$env:PKG; $scriptDir=$env:SCRIPTDIR.TrimEnd([char]92); $tempRoot=Join-Path $env:TEMP ('confluence-export-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null; $target=Join-Path $tempRoot $pkg; $siblingIndex=Join-Path (Join-Path $scriptDir $pkg) 'index.html'; if(Test-Path -LiteralPath $siblingIndex){ Copy-Item -LiteralPath (Join-Path $scriptDir $pkg) -Destination $target -Recurse -Force } else { $names=@($pkg + '.zip'); $leaf=Split-Path $scriptDir -Leaf; if($leaf -like '*.zip'){ $c=$leaf -replace '^Temp\d+_',''; $c=$c -replace '^.*\bfor ',''; if($c -and ($names -notcontains $c)){ $names += $c } } $dirs=@((Join-Path $env:USERPROFILE 'Downloads'),(Join-Path $env:USERPROFILE 'Desktop'),(Join-Path $env:USERPROFILE 'Documents'),$env:USERPROFILE,(Get-Location).Path,(Split-Path $scriptDir -Parent)); $zip=$null; foreach($d in $dirs){ if($d){ foreach($n in $names){ $p=Join-Path $d $n; if(Test-Path -LiteralPath $p){ $zip=$p; break } } }; if($zip){ break } } if(-not $zip){ Write-Host ''; Write-Host 'Could not automatically locate the export zip.'; Write-Host 'Please use OPTION 2: extract the zip, copy the folder, and open index.html.'; exit 1 } Expand-Archive -LiteralPath $zip -DestinationPath $tempRoot -Force } $index=Join-Path $target 'index.html'; if(-not (Test-Path -LiteralPath $index)){ Write-Host 'Could not find index.html after preparing the files.'; exit 1 } Start-Process $index; Write-Host ('Opened: ' + $index)"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo The auto-runner could not finish. See the message above,
    echo or use OPTION 2 to open the export manually.
    pause
)
endlocal & exit /b %RC%
"""
    return template.replace("__PKG__", package_dir_name)


def generate_mac_launcher(package_dir_name: str) -> str:
    """
    Generates a macOS launcher that opens the export from a temporary folder.

    Works when run from an already-extracted folder (sibling export folder
    present) and also falls back to locating the original .zip in common
    locations (Downloads/Desktop/Documents/home) and extracting it.
    """
    template = r"""#!/bin/bash
set -euo pipefail

PKG="__PKG__"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/confluence-export.XXXXXX")"
TARGET_DIR="${TEMP_ROOT}/${PKG}"

cat <<'EOF'
============================================================
 Confluence Export - How to open this package
============================================================

 OPTION 1 - Auto-extract and open (this runner)
   Extracts the export to a temporary folder and opens
   index.html in your browser automatically.

 OPTION 2 - Manual
   Copy the export folder to any location, then open
   index.html inside that folder.
============================================================
EOF
echo

if [[ -f "${SCRIPT_DIR}/${PKG}/index.html" ]]; then
    cp -R "${SCRIPT_DIR}/${PKG}" "${TARGET_DIR}"
else
    ZIP=""
    for d in "${HOME}/Downloads" "${HOME}/Desktop" "${HOME}/Documents" "${HOME}" "$(pwd)"; do
        if [[ -f "${d}/${PKG}.zip" ]]; then
            ZIP="${d}/${PKG}.zip"
            break
        fi
    done
    if [[ -z "${ZIP}" ]]; then
        echo "Could not automatically locate the export zip."
        echo "Please use OPTION 2: extract the zip, copy the folder, and open index.html."
        exit 1
    fi
    ditto -x -k "${ZIP}" "${TEMP_ROOT}"
fi

if [[ ! -f "${TARGET_DIR}/index.html" ]]; then
    echo "Could not find index.html after preparing the files."
    exit 1
fi

open "${TARGET_DIR}/index.html"
echo "Opened: ${TARGET_DIR}/index.html"
"""
    return template.replace("__PKG__", package_dir_name)


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
