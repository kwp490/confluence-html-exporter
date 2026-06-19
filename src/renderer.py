import base64
import html
import logging
import mimetypes
import re
from urllib.parse import urlparse, urljoin, unquote

from bs4 import BeautifulSoup

from .utils import sanitize_attachment_filename


# Attributes and URL schemes that can execute script or leak data are removed
# from exported Confluence HTML before it is written into the offline package.
_DANGEROUS_TAGS = ("script", "iframe", "object", "embed", "link", "meta", "base", "form")
_DANGEROUS_URL_ATTRS = ("href", "src", "xlink:href", "action", "formaction")

# Attributes whose only purpose is to trigger an outbound network request for a
# resource. The offline package embeds Confluence-hosted images as base64 data
# URIs (see _embed_images), so these attributes would only ever point at
# external/third-party hosts when the document is opened. They are stripped
# entirely to prevent the exported HTML from "phoning home" or leaking the
# reader's IP/referrer to a tracker the moment the file is opened.
_RESOURCE_LOADING_ATTRS = (
    "srcset",
    "background",
    "poster",
    "lowsrc",
    "dynsrc",
    "data-src",
    "data-srcset",
    "data-background",
    "data-original",
    "data-lazy-src",
)

# Matches a CSS url(...) reference inside an inline style attribute.
_CSS_URL_RE = re.compile(r"url\s*\([^)]*\)", re.IGNORECASE)


def _is_dangerous_url(value: str) -> bool:
    if not value:
        return False
    stripped = value.strip().lower().replace("\t", "").replace("\n", "").replace("\r", "")
    return stripped.startswith(("javascript:", "vbscript:", "data:text/html"))


def _sanitize_style(value: str) -> str | None:
    """
    Neutralizes an inline ``style`` attribute. Any ``url(...)`` reference (which
    would load an external image/font and leak a request) and any CSS
    ``expression(...)`` (legacy IE script execution) are removed. Returns the
    cleaned style string, or None if nothing meaningful remains.
    """
    cleaned = _CSS_URL_RE.sub("", value)
    if "expression" in cleaned.lower():
        # Drop the whole declaration rather than risk a partial bypass.
        return None
    cleaned = cleaned.strip().strip(";").strip()
    return cleaned or None


def sanitize_html(soup: BeautifulSoup) -> BeautifulSoup:
    """
    Removes script-bearing tags, inline event handlers, dangerous URL schemes,
    and outbound resource-loading attributes from untrusted Confluence-exported
    HTML so the offline package cannot execute arbitrary JavaScript or silently
    contact external/tracking hosts when opened in a browser.
    """
    for tag_name in _DANGEROUS_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            attr_lower = attr.lower()
            if attr_lower.startswith("on"):
                del tag.attrs[attr]
                continue
            if attr_lower in _RESOURCE_LOADING_ATTRS:
                # Strip resource-loading attributes that would fetch from an
                # external host (srcset, poster, CSS-less background, etc.).
                del tag.attrs[attr]
                continue
            if attr_lower in _DANGEROUS_URL_ATTRS and _is_dangerous_url(str(tag.attrs.get(attr, ""))):
                del tag.attrs[attr]
            elif attr_lower == "style":
                cleaned = _sanitize_style(str(tag.attrs.get(attr, "")))
                if cleaned is None:
                    del tag.attrs[attr]
                else:
                    tag.attrs[attr] = cleaned
    return soup



CSS = """
/* Reset */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

/* Layout */
html, body { height: 100%; }
#layout { display: flex; height: 100vh; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1a1a2e; }

/* Sidebar */
#sidebar { width: 260px; min-width: 260px; background: #1e1e2e; color: #cdd6f4; display: flex; flex-direction: column; overflow: hidden; }
#sidebar-header { padding: 1.2rem 1rem 0.8rem 1rem; border-bottom: 1px solid #313244; flex-shrink: 0; }
#sidebar-title { font-size: 0.8rem; font-weight: 700; color: #89b4fa; text-transform: uppercase; letter-spacing: 0.04em; }
#export-date { font-size: 0.7rem; color: #6c7086; margin-top: 0.3rem; }
#nav-scroll { overflow-y: auto; flex: 1; padding: 0.75rem 0.5rem; }

/* Nav items */
.nav-list { list-style: none; padding: 0; margin: 0; }
.nav-children { padding-left: 0.9rem; }
.nav-item { margin: 1px 0; }
.nav-link { display: block; padding: 0.28rem 0.6rem; border-radius: 4px; color: #cdd6f4; text-decoration: none; font-size: 0.82rem; line-height: 1.4; transition: background 0.1s; }
.nav-link:hover { background: #313244; color: #fff; }
.nav-link.active { background: #45475a; color: #89b4fa; font-weight: 600; }
.nav-toggle { display: block; padding: 0.28rem 0.6rem; border-radius: 4px; color: #a6adc8; font-size: 0.82rem; cursor: pointer; user-select: none; }
.nav-toggle:hover { background: #313244; color: #cdd6f4; }
.nav-folder-label { display: block; padding: 0.4rem 0.6rem 0.2rem 0.6rem; color: #6c7086; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }

/* Main content area */
#main { flex: 1; overflow-y: auto; display: flex; flex-direction: column; }
#content-header { padding: 2rem 3rem 1rem 3rem; border-bottom: 1px solid #e8e8ef; background: #fafafa; flex-shrink: 0; }
#page-title { font-size: 1.7rem; font-weight: 700; color: #1a1a2e; }
#page-meta { margin-top: 0.4rem; font-size: 0.8rem; color: #888; }
#page-body { padding: 2rem 3rem 3rem 3rem; max-width: 860px; line-height: 1.7; }

/* Typography */
#page-body h1 { font-size: 1.5rem; margin: 1.8rem 0 0.6rem 0; color: #1a1a2e; }
#page-body h2 { font-size: 1.25rem; margin: 1.5rem 0 0.5rem 0; color: #1a1a2e; }
#page-body h3 { font-size: 1.05rem; margin: 1.2rem 0 0.4rem 0; color: #1a1a2e; }
#page-body p { margin: 0.6rem 0; }
#page-body ul, #page-body ol { margin: 0.6rem 0 0.6rem 1.4rem; }
#page-body li { margin: 0.25rem 0; }
#page-body hr { border: none; border-top: 1px solid #e0e0e0; margin: 1.5rem 0; }
#page-body blockquote { border-left: 3px solid #89b4fa; margin: 1rem 0; padding: 0.5rem 1rem; background: #f0f4ff; border-radius: 0 4px 4px 0; }

/* Links */
#page-body a { color: #0055cc; text-decoration: none; }
#page-body a:hover { text-decoration: underline; }
a.external::after { content: ' \\2197'; font-size: 0.75em; color: #888; }

/* Tables */
#page-body table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.9rem; }
#page-body th { background: #f0f4ff; font-weight: 600; text-align: left; padding: 0.5rem 0.75rem; border: 1px solid #d0d8f0; }
#page-body td { padding: 0.5rem 0.75rem; border: 1px solid #e0e4f0; vertical-align: top; }
#page-body tr:nth-child(even) td { background: #f9faff; }

/* Code */
#page-body pre { background: #f4f4f8; border: 1px solid #e0e0e0; border-radius: 4px; padding: 1rem; overflow-x: auto; margin: 0.8rem 0; font-size: 0.85rem; }
#page-body code { font-family: 'Courier New', 'Consolas', monospace; font-size: 0.88em; background: #f0f0f5; padding: 0.1em 0.3em; border-radius: 3px; }
#page-body pre code { background: none; padding: 0; }

/* Images */
#page-body img { max-width: 100%; height: auto; border-radius: 4px; margin: 0.5rem 0; }
.img-unavailable { display: inline-block; padding: 0.3rem 0.6rem; background: #fff3cd; border: 1px solid #ffc107; border-radius: 3px; font-size: 0.8rem; color: #856404; }

/* Confluence info/warning panels (common macro output) */
.confluence-information-macro { border-radius: 4px; padding: 0.75rem 1rem; margin: 0.75rem 0; border-left: 4px solid #0055cc; background: #f0f4ff; }
.confluence-information-macro-warning { border-left-color: #cc5500; background: #fff4f0; }
.confluence-information-macro-note { border-left-color: #cc9900; background: #fffbf0; }
.confluence-information-macro-tip { border-left-color: #006633; background: #f0fff4; }
"""

JS = """
(function() {
    // Highlight active page and expand ancestor nodes
    var currentFile = window.location.pathname.split('/').pop() || 'index.html';
    document.querySelectorAll('.nav-link').forEach(function(link) {
        if (link.getAttribute('href') === currentFile) {
            link.classList.add('active');
            // Expand all ancestor nav-children lists
            var parent = link.parentElement;
            while (parent) {
                if (parent.classList && parent.classList.contains('nav-children')) {
                    parent.style.display = 'block';
                }
                parent = parent.parentElement;
            }
        }
    });

    // Toggle child lists on click
    document.querySelectorAll('.nav-toggle').forEach(function(toggle) {
        toggle.addEventListener('click', function() {
            var children = toggle.parentElement.querySelector('.nav-children');
            if (children) {
                var isHidden = children.style.display === 'none' || children.style.display === '';
                children.style.display = isHidden ? 'block' : 'none';
                toggle.textContent = toggle.textContent.replace(
                    isHidden ? '\\u25b6' : '\\u25bc',
                    isHidden ? '\\u25bc' : '\\u25b6'
                );
            }
        });
    });
})();
"""


def _format_date(iso_date: str) -> str:
    if not iso_date:
        return ""
    try:
        import datetime
        dt = datetime.datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y")
    except Exception:
        return iso_date


class HTMLRenderer:
    """
    Converts a flat list of page nodes into rendered, self-contained HTML files
    and collects attachment binary data.
    """

    def __init__(self, client, base_url: str) -> None:
        self.client = client
        self.base_url = base_url.rstrip('/')

    def render_all(self, pages: list) -> list:
        total = len(pages)
        for i, page in enumerate(pages, 1):
            logging.info(f"Rendering {i}/{total}: {page['title']}")
            rendered_html, attachment_files = self.render_page(page, pages)
            page["rendered_html"] = rendered_html
            page["attachment_files"] = attachment_files
        return pages

    def render_page(self, page: dict, all_pages: list) -> tuple:
        attachment_files = {}

        if page["body_html"] == "":
            content_html = self._render_folder_index(page, all_pages)
        else:
            soup = BeautifulSoup(page["body_html"], "lxml")
            sanitize_html(soup)
            self._embed_images(soup, page)
            attachment_files = self._collect_attachments(page)
            self._rewrite_links(soup, page, all_pages)
            body_tag = soup.body
            if body_tag is not None:
                content_html = body_tag.decode_contents()
            else:
                content_html = str(soup)

        nav_html = self._build_nav_tree(all_pages, page["id"])
        root_title = all_pages[0]["title"] if all_pages else page["title"]
        document = self._build_html_document(page, content_html, nav_html, attachment_files, root_title)
        return document, attachment_files

    def _is_confluence_hosted(self, src: str) -> bool:
        if src.startswith("/"):
            return True
        netloc = urlparse(src).netloc
        return netloc == urlparse(self.base_url).netloc

    def _attachment_download_links(self, page: dict) -> dict:
        """
        Maps attachment filename -> REST download link for the given page.

        Exported page HTML references images by a ``/wiki/download/attachments``
        ``src`` URL that rejects API-token authentication (401). The attachments
        REST API instead exposes an authenticated ``downloadLink`` per file, so
        images are resolved to those links by matching on filename.
        """
        mapping = {}
        for att in page.get("attachments", []):
            title = att.get("title")
            link = att.get("downloadLink") or att.get("_links", {}).get("download")
            if title and link:
                mapping[title] = link
        return mapping

    def _embed_images(self, soup: BeautifulSoup, page: dict) -> BeautifulSoup:
        download_links = self._attachment_download_links(page)
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if not src or src.startswith("data:"):
                continue
            if not self._is_confluence_hosted(src):
                continue
            abs_url = src if src.startswith("http") else urljoin(self.base_url + "/", src.lstrip("/"))
            filename = unquote(src.split("?")[0].split("/")[-1])
            download_link = download_links.get(filename)
            try:
                if download_link:
                    img_bytes = self.client.download_attachment(download_link)
                else:
                    img_bytes = self.client.download_binary(abs_url)
                mime_type = mimetypes.guess_type(filename)[0] or "image/png"
                encoded = base64.b64encode(img_bytes).decode("ascii")
                img["src"] = f"data:{mime_type};base64,{encoded}"
            except Exception as exc:
                logging.warning(
                    f"Image download failed [{page['title']}]: {src} ({exc})"
                )
                span = soup.new_tag("span")
                span["class"] = "img-unavailable"
                span.string = f"[Image unavailable: {src}]"
                img.replace_with(span)
        return soup

    def _collect_attachments(self, page: dict) -> dict:
        files = {}
        for att in page.get("attachments", []):
            media_type = att.get("mediaType", "") or ""
            if media_type.startswith("image/"):
                continue
            download = att.get("downloadLink") or att.get("_links", {}).get("download")
            if not download:
                continue
            try:
                data = self.client.download_attachment(download)
                files[sanitize_attachment_filename(att["title"])] = data
            except Exception as exc:
                logging.warning(
                    f"Attachment download failed [{page['title']}]: {att.get('title')} ({exc})"
                )
        return files

    def _classify_link(self, href: str, id_to_file: dict) -> tuple:
        if not href or href.startswith("#") or href.startswith("mailto:"):
            return href, ""

        page_id_match = re.search(r'/pages/(\d+)', href)
        if page_id_match:
            pid = page_id_match.group(1)
            if pid in id_to_file:
                return id_to_file[pid], ""
            abs_href = urljoin(self.base_url, href) if href.startswith("/") else href
            return abs_href, "external"

        if "/download/attachments/" in href:
            filename = href.split("/")[-1].split("?")[0]
            filename = sanitize_attachment_filename(filename)
            return f"./attachments/{filename}", ""

        if href.startswith("/") or urlparse(href).netloc == urlparse(self.base_url).netloc:
            abs_href = urljoin(self.base_url, href) if href.startswith("/") else href
            return abs_href, "external"

        return href, "external"

    def _rewrite_links(self, soup: BeautifulSoup, current_page: dict, all_pages: list) -> BeautifulSoup:
        id_to_file = {p["id"]: p["html_filename"] for p in all_pages}
        for a in soup.find_all("a"):
            href = a.get("href", "")
            new_href, link_class = self._classify_link(href, id_to_file)
            a["href"] = new_href
            if link_class == "external":
                a["target"] = "_blank"
                a["rel"] = "noopener noreferrer"
                classes = a.get("class", [])
                if isinstance(classes, str):
                    classes = classes.split()
                if "external" not in classes:
                    classes.append("external")
                a["class"] = classes
        return soup

    def _build_nav_tree(self, all_pages: list, current_page_id: str) -> str:
        by_id = {p["id"]: p for p in all_pages}
        root = all_pages[0] if all_pages else None
        if root is None:
            return ""

        def render_node(node):
            children = [by_id[cid] for cid in node["children_ids"] if cid in by_id]
            active = ' active' if node["id"] == current_page_id else ''
            title = html.escape(node["title"])
            filename = html.escape(node["html_filename"], quote=True)

            if node["type"] == "folder":
                label = f'<span class="nav-folder-label">{title}</span>'
                if children:
                    inner = "".join(render_node(c) for c in children)
                    return (
                        f'<li class="nav-item has-children">{label}'
                        f'<ul class="nav-list nav-children">{inner}</ul></li>'
                    )
                return f'<li class="nav-item">{label}</li>'

            link = f'<a class="nav-link{active}" href="{filename}">{title}</a>'
            if children:
                inner = "".join(render_node(c) for c in children)
                toggle = f'<span class="nav-toggle">\u25b6 {title}</span>'
                return (
                    f'<li class="nav-item has-children">{link}'
                    f'<ul class="nav-list nav-children" style="display:none;">{inner}</ul></li>'
                )
            return f'<li class="nav-item">{link}</li>'

        return f'<ul class="nav-list nav-root">{render_node(root)}</ul>'

    def _build_html_document(self, page: dict, content_html: str, nav_html: str, attachment_files: dict, root_title: str = None) -> str:
        import datetime
        export_date = datetime.date.today().strftime("%Y-%m-%d")
        if root_title is None:
            root_title = page["title"]
        meta_parts = []
        formatted = _format_date(page.get("version_date", ""))
        if formatted:
            meta_parts.append(f"Last updated: {formatted}")
        if page.get("confluence_url"):
            safe_url = html.escape(page["confluence_url"], quote=True)
            link = (
                f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" class="external">'
                f'View in Confluence \u2197</a>'
            )
            if meta_parts:
                meta_parts.append("&nbsp;\u00b7&nbsp;")
            meta_parts.append(link)
        meta_html = "".join(meta_parts)

        safe_title = html.escape(page["title"])
        safe_root_title = html.escape(root_title)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_title}</title>
    <style>{CSS}</style>
</head>
<body>
    <div id="layout">
        <nav id="sidebar">
            <div id="sidebar-header">
                <div id="sidebar-title">{safe_root_title}</div>
                <div id="export-date">Exported {export_date}</div>
            </div>
            <div id="nav-scroll">
                {nav_html}
            </div>
        </nav>
        <main id="main">
            <div id="content-header">
                <h1 id="page-title">{safe_title}</h1>
                <div id="page-meta">
                    {meta_html}
                </div>
            </div>
            <article id="page-body">
                {content_html}
            </article>
        </main>
    </div>
    <script>{JS}</script>
</body>
</html>"""

    def _render_folder_index(self, page: dict, all_pages: list) -> str:
        by_id = {p["id"]: p for p in all_pages}
        items = []
        for cid in page["children_ids"]:
            child = by_id.get(cid)
            if child:
                items.append(
                    f'<li><a href="{html.escape(child["html_filename"], quote=True)}">'
                    f'{html.escape(child["title"])}</a></li>'
                )
        list_html = "".join(items)
        return (
            "<p>This section contains the following pages:</p>"
            f"<ul>{list_html}</ul>"
        )
