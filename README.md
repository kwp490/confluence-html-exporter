# confluence-html-exporter

A command-line Python tool that exports a Confluence page and all of its child pages into a self-contained, navigable HTML package delivered as a `.zip` file. Inline images are base64-embedded in each HTML file. File attachments are packaged into an `/attachments/` folder inside the zip. Pages and folders whose titles contain the words `deprecated` or `internal` (case-insensitive) are skipped along with all their children.

Designed to share Confluence documentation with external stakeholders who do not have Confluence access. The zip can be emailed, unzipped, and navigated entirely offline in any web browser.

---

## Features

- Accepts any Confluence page URL as input
- Recursively exports the page and all child pages and folders
- Skips any page or folder whose title contains `deprecated` or `internal` (case-insensitive); also skips all descendants of filtered nodes
- Downloads all images found in page content and embeds them as base64 `data:` URIs directly in each HTML file
- Downloads non-image file attachments and packages them in `/attachments/` inside the zip with updated relative links
- Generates a left-sidebar navigation tree present on every page with the current page highlighted
- Converts internal Confluence links to relative links within the zip; external links open in a new tab
- Outputs a single `.zip` named `{root-page-slug}-{YYYY-MM-DD}.zip`
- Runs on macOS and Windows (Python 3.8+)
- All credentials are stored in a `.env` file; nothing is hardcoded

---

## Prerequisites

- Python 3.8 or higher
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

Copy `.env.example` to `.env` and fill in your credentials (see Configuration).

---

## Configuration

All credentials are loaded from a `.env` file in the project root. The script will not run without all three variables set.

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

Unzip and open `index.html` in any browser to navigate the exported content. No internet connection is required after unzipping.

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
    ├── tree.py                   # Page tree traversal and filter logic
    ├── renderer.py               # HTML page generation
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
  [`Secret Scan`](.github/workflows/secret-scan.yml) GitHub Actions workflow
  (gitleaks), which also scans the full git history. Custom rules and
  placeholder allowlists live in [`.gitleaks.toml`](.gitleaks.toml).
- GitHub-native **secret scanning** and **push protection** are also enabled on
  this repository.
- Never commit a real `.env`; it is git-ignored. Only `.env.example` with
  placeholder values is tracked.

---

## License

MIT License. See [LICENSE](LICENSE).
