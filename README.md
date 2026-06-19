# confluence-html-exporter

Confluence pages are not universally visible outside your organization, but opening a Confluence space publicly can create security, governance, and confidentiality risks.

This command-line Python tool solves that by exporting a Confluence page and all of its child pages into a self-contained, navigable HTML package delivered as a `.zip` file for private sharing. Inline images are base64-embedded in each HTML file, file attachments are packaged into an `/attachments/` folder inside the zip, and pages/folders whose titles contain `deprecated` or `internal` (case-insensitive) are skipped along with all their children.

Use it to send existing Confluence content privately (for example, by email or secure file transfer) to people who do not have Confluence access, while keeping the original site private.

---

## Features

- Accepts any Confluence page URL as input
- Recursively exports the page and all child pages and folders
- Skips any page or folder whose title contains `deprecated` or `internal` (case-insensitive); also skips all descendants of filtered nodes
- Downloads all images found in page content and embeds them as base64 `data:` URIs directly in each HTML file
- Downloads non-image file attachments and packages them in `/attachments/` inside the zip with updated relative links
- Generates a left-sidebar navigation tree present on every page with the current page highlighted
- Converts internal Confluence links to relative links within the zip; external links open in a new tab with `rel="noopener noreferrer"`
- Outputs a single `.zip` named `{root-page-slug}-{YYYY-MM-DD}.zip`
- Adds root-level startup guidance (`START-HERE.txt` / `START-HERE.html`) explaining both manual and auto-run options
- Includes cross-platform launchers in the zip root:
  - `Run-Export-Windows.cmd` (Windows)
  - `Run-Export-Mac.command` (macOS)
  These launchers copy/extract the export to a temporary folder and open `index.html` automatically.
- Runs on macOS and Windows (Python 3.10+)
- All credentials are stored in a `.env` file; nothing is hardcoded
- Interactive setup wizard guides first-time users through credential configuration with live validation

---

## Prerequisites

- Python 3.10 or higher
- pip
- A Confluence Cloud account with read access to the target space
- A Confluence API token (see Configuration section)

---

## Installation

```bash
git clone https://github.com/<owner>/confluence-html-exporter.git
cd confluence-html-exporter
pip install -r requirements.txt
```

On first run, the script will walk you through setting up your `.env` credentials interactively (see Configuration). You can also copy `.env.example` to `.env` and fill it in manually.

---

## Configuration

All credentials are loaded from a `.env` file in the project root.

If any credentials are missing, invalid, or still set to placeholder values, the script will automatically launch an **interactive setup wizard** that:

1. Prompts for each missing value (the API token is entered securely without echoing)
2. Validates the format of each field before accepting it
3. Tests the credentials against the Confluence API
4. Saves them to `.env` (with restricted file permissions) only after a successful authentication test

In non-interactive environments (e.g. CI), the script exits with an error if credentials are incomplete  set them via environment variables or `.env` beforehand.

> HTTPS required: The Confluence base URL must use `https://` so your email and API token are never sent over an unencrypted connection. Plain `http://` is always rejected and there is no override.

### `.env.example`

```
CONFLUENCE_BASE_URL=https://your-instance.atlassian.net
CONFLUENCE_EMAIL=you@example.com
CONFLUENCE_API_TOKEN=your_api_token_here
```

### Variable Reference

| Variable | Description | Example |
|---|---|---|
| `CONFLUENCE_BASE_URL` | Base URL of your Confluence instance | `https://example.atlassian.net` |
| `CONFLUENCE_EMAIL` | Your Atlassian account email address | `user@example.com` |
| `CONFLUENCE_API_TOKEN` | Your Confluence API token | `ATATTxxx...` |

### Generating an API Token

1. Go to `https://id.atlassian.com/manage-profile/security/api-tokens`
2. Click **Create API token**
3. Give it a label (e.g., `confluence-html-exporter`)
4. Copy the token immediately and paste it into `.env` as `CONFLUENCE_API_TOKEN`

The token authenticates using HTTP Basic Auth: username is your email, password is the token.

---

## Usage

```bash
python confluence_exporter.py <confluence_page_url> [-o OUTPUT] [-v] [-y]
```

| Option | Description |
|---|---|
| `-o`, `--output` | Where to save the `.zip`. May be a **directory** (the zip is saved inside it using the default name) or a **full file path** ending in `.zip`. Missing directories are created automatically. Defaults to the current directory. |
| `-v`, `--verbose` | Enable debug logging. |
| `-y`, `--yes` | Skip the confidential-data confirmation prompt (for non-interactive/automated use). |

> ⚠️ **Confidential data warning:** This tool exports Confluence pages **and their file attachments** into an unprotected, shareable `.zip`. The title-based filtering (skipping `deprecated`/`internal`) is **not** a security control and may miss restricted content. You will be prompted to confirm before each export. Always review the generated package before sharing it.

### Examples

```bash
# Export a page and all child pages to the current directory
python confluence_exporter.py "https://example.atlassian.net/wiki/spaces/SPACE/pages/123456789/Page+Title"

# Save into a specific directory (default filename is used)
python confluence_exporter.py "https://example.atlassian.net/wiki/spaces/SPACE/pages/123456789/Page+Title" -o "C:\Exports"

# Save to an explicit file path
python confluence_exporter.py "https://example.atlassian.net/wiki/spaces/SPACE/pages/123456789/Page+Title" -o "C:\Exports\export.zip"
```

### Output

By default the script writes a zip file to the current working directory:

```
page-title-2025-06-19.zip
```

When `-o`/`--output` is supplied, the zip is written to the directory or file path you specify (creating any missing folders). The final location is printed as `Export complete: {path}`.

When you open the zip, choose one of two options:

**Option 1 — Auto-extract and open.** Run the launcher for your OS from the zip root; it extracts the export to a temporary folder and opens `index.html` automatically:

- Windows: `Run-Export-Windows.cmd`
- macOS: `Run-Export-Mac.command`

The launchers work even if you run them directly from inside the zip viewer: if only the launcher file is extracted, it locates the original `.zip` (in the current folder, Downloads, Desktop, Documents, or your home folder) and extracts it for you. Depending on browser/OS security settings you may need to confirm a prompt or right-click → **Open**.

**Option 2 — Manual.** Copy the dated export folder (for example `page-title-2025-06-19\`) to any location and open its `index.html`.

`START-HERE.txt` and `START-HERE.html` in the zip root present these same two options. Note: open `START-HERE.html` only **after** extracting the zip — when opened from inside the Windows/macOS zip viewer, only that single file is unpacked to a temporary folder, so links to sibling files won't resolve. The most reliable action straight from the zip window is to double-click the launcher file itself.

---

## Repository Structure

```
confluence-html-exporter/
├── README.md
├── LICENSE
├── .gitignore
├── requirements.txt
├── .env.example
├── confluence_exporter.py        # CLI entry point and orchestration
└── src/
    ├── __init__.py
    ├── api.py                    # Confluence REST API client
    ├── setup.py                  # Interactive credential setup wizard
    ├── tree.py                   # Page tree traversal and filter logic
    ├── renderer.py               # HTML generation + sanitization
    └── utils.py                  # URL parsing, slugification, logging helpers
```

---

## Known Limitations

- Images served by third-party services embedded in Confluence (e.g., external Lucidchart diagrams, Figma embeds) will not be downloadable and will appear as unavailable placeholders.
- Confluence macros that render dynamic content (Jira issue lists, live charts) will appear as static HTML snapshots from the time of export.
- The export reflects the state of Confluence at the time the script is run. Re-run the script to update the export.
- Very large page trees (500+ pages) may take several minutes due to API rate limits.

---

## Security

- **Automated secret scanning** runs on every push and pull request via the
  [`Secret Scan`](.github/workflows/secret-scan.yml) GitHub Actions workflow.
  It installs the gitleaks CLI and runs `gitleaks detect --log-opts=--all`,
  which walks every commit on all refs (full history), so secrets that were
  committed and later removed are still caught. Custom rules and placeholder
  allowlists live in [`.gitleaks.toml`](.gitleaks.toml).
- GitHub-native **secret scanning** and **push protection** are also enabled on
  this repository.
- **Credentials are only ever transmitted over HTTPS.** Plain `http://` base
  URLs are always rejected (no override), so your API token cannot be
  intercepted.
- **Exported HTML is sanitized** before packaging: script-bearing tags, inline
  event handlers, dangerous URL schemes, and outbound resource-loading
  attributes (`srcset`, `poster`, CSS `url(...)`, etc.) are stripped so the
  offline package cannot run scripts or silently contact tracking hosts.
- Never commit a real `.env`; it is git-ignored. Only `.env.example` with
  placeholder values is tracked.

---

## License

MIT License. See [LICENSE](LICENSE).
