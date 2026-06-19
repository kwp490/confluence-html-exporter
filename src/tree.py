import logging

from .utils import slugify

SKIP_KEYWORDS = ['deprecated', 'internal']


class PageTreeBuilder:
    """
    Builds a filtered tree of page nodes from Confluence starting at a root page.
    """

    def __init__(self, client) -> None:
        self.client = client

    def build(self, root_page_id: str) -> list:
        """
        Entry point. Fetches the root page, checks filter, then recursively
        fetches and filters all descendants.
        Returns a flat list of page node dicts in depth-first order.
        """
        nodes = self._fetch_node(root_page_id, depth=0, parent_id=None)
        nodes = self._ensure_unique_slugs(nodes)
        return nodes

    def _should_skip(self, title: str) -> bool:
        """
        Returns True if the title contains any keyword in SKIP_KEYWORDS (case-insensitive).
        """
        lower = (title or "").lower()
        return any(kw in lower for kw in SKIP_KEYWORDS)

    def _fetch_node(self, page_id: str, depth: int, parent_id) -> list:
        """
        Fetches a single page and recursively fetches its children.
        Applies _should_skip before fetching children of any node.
        """
        try:
            page = self.client.get_page(page_id)
        except Exception as exc:
            logging.error(f"Failed to fetch page {page_id}: {exc}")
            return []

        title = page.get("title", "")
        if self._should_skip(title):
            logging.info(f"Skipping filtered node: {title}")
            return []

        node_type = page.get("type", "page")

        if node_type == "folder":
            body_html = ""
        else:
            body_html = (
                page.get("body", {})
                .get("export_view", {})
                .get("value", "")
            ) or ""

        version_date = page.get("version", {}).get("createdAt", "")
        webui = page.get("_links", {}).get("webui", "")
        confluence_url = ""
        if webui:
            confluence_url = self.client.base_url + webui

        try:
            attachments = self.client.get_attachments(page_id)
        except Exception as exc:
            logging.warning(f"Failed to fetch attachments for {title} ({page_id}): {exc}")
            attachments = []

        try:
            children = self.client.get_children(page_id)
        except Exception as exc:
            logging.warning(f"Failed to fetch children for {title} ({page_id}): {exc}")
            children = []

        valid_children = [
            c for c in children if c.get("status", "current") == "current"
        ]

        slug = slugify(title)
        node = {
            "id": str(page.get("id", page_id)),
            "title": title,
            "type": node_type,
            "slug": slug,
            "depth": depth,
            "parent_id": str(parent_id) if parent_id is not None else None,
            "html_filename": f"{slug}.html",
            "body_html": body_html,
            "version_date": version_date,
            "confluence_url": confluence_url,
            "attachments": attachments,
            "children_ids": [],
        }

        result = [node]

        for child in valid_children:
            child_id = str(child["id"])
            child_title = child.get("title", "")
            if self._should_skip(child_title):
                logging.info(f"Skipping filtered node: {child_title}")
                continue
            child_nodes = self._fetch_node(child_id, depth + 1, node["id"])
            if child_nodes:
                node["children_ids"].append(child_nodes[0]["id"])
                result.extend(child_nodes)

        return result

    def _ensure_unique_slugs(self, nodes: list) -> list:
        """
        If two pages have the same slug, appends -{n} to disambiguate.
        """
        seen = {}
        for node in nodes:
            slug = node["slug"]
            if slug in seen:
                seen[slug] += 1
                new_slug = f"{slug}-{seen[slug]}"
                node["slug"] = new_slug
                node["html_filename"] = f"{new_slug}.html"
            else:
                seen[slug] = 1
        return nodes
