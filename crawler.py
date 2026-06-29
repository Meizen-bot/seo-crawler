import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag, parse_qs, urlencode
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET
import json
import time
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Callable

DEFAULT_SKIP_EXTS = {
    "pdf", "jpg", "jpeg", "png", "gif", "svg", "webp", "ico",
    "css", "js", "woff", "woff2", "ttf", "eot", "mp4", "mp3",
    "zip", "gz", "tar", "exe", "dmg", "xml", "json",
}


NAV_SELECTORS_CSS = [
    "header", "footer", "nav", "aside",
    "[role='navigation']", "[role='banner']", "[role='contentinfo']",
    # Generic class patterns
    ".nav", ".menu", ".navigation", ".header", ".footer",
    ".sidebar", ".widget", ".breadcrumb", ".breadcrumbs",
    # ID patterns
    "#menu", "#nav", "#header", "#footer", "#sidebar",
    # WordPress / WooCommerce
    "#wpadminbar", ".wp-block-navigation", ".wp-block-template-part",
    ".site-header", ".site-footer", ".site-navigation",
    ".wp-site-blocks > header", ".wp-site-blocks > footer",
    # Elementor
    ".elementor-location-header", ".elementor-location-footer",
    # Divi
    "#main-header", "#main-footer", ".et-menu-nav",
    # WPBakery / Avada / Genesis
    ".fusion-header-wrapper", ".fusion-footer-widget-area", ".fusion-footer",
    ".genesis-nav-menu", ".genesis-skip-link",
    # Related posts / author boxes / social share (not editorial links)
    ".related-posts", ".related", ".post-related",
    ".author-bio", ".author-box", ".post-author",
    ".social-share", ".share-buttons", ".sharedaddy",
    ".tags-links", ".cat-links", ".post-tags", ".post-categories",
    # Comments
    "#comments", ".comments-area", ".comment-list",
    # Cookie / GDPR banners
    ".cookie-banner", ".cookie-notice", "#cookie-law-info-bar",
    # Popups / overlays
    ".popup", ".modal", ".overlay",
    # Pagination
    ".pagination", ".wp-pagenavi", ".nav-links",
    # Search forms
    ".search-form", ".search-widget",
]
NAV_CLASSES = {
    "nav", "menu", "navigation", "header", "footer",
    "sidebar", "widget", "breadcrumb", "breadcrumbs",
    "top-bar", "topbar", "menubar",
    # WordPress
    "site-header", "site-footer", "site-navigation",
    "wp-block-navigation",
    # Elementor
    "elementor-location-header", "elementor-location-footer",
    # Related / meta blocks
    "related-posts", "related", "author-bio", "author-box",
    "social-share", "share-buttons", "post-tags", "post-categories",
    "tags-links", "cat-links", "pagination", "nav-links",
    "comments-area", "comment-list",
}
NAV_IDS = {
    "menu", "nav", "header", "footer", "sidebar",
    "wpadminbar", "main-header", "main-footer", "comments",
}
CONTENT_SELECTORS = [
    # Semantic HTML5 — highest priority
    "article",
    "main",
    "[role='main']",
    # WordPress core & Gutenberg
    ".entry-content",
    ".post-content",
    ".page-content",
    ".wp-block-post-content",
    ".single-content",
    # Generic CMS patterns
    ".content",
    ".content-area",
    ".content-wrapper",
    ".article-content",
    ".article-body",
    ".post-body",
    ".post-entry",
    ".blog-content",
    ".page-body",
    ".main-content",
    ".main-body",
    "#content",
    "#main-content",
    "#post-content",
    "#article-content",
    # Elementor
    ".elementor-widget-theme-post-content",
    # Divi
    ".et_pb_post_content",
    # Webflow
    ".rich-text",
    ".w-richtext",
    # HubSpot
    ".blog-post__body",
    ".hb-blog-post",
    # Squarespace
    ".sqs-block-html",
    # Wix
    "[data-mesh-id$='inlineContent']",
    # Fallback: generic "post" wrapper
    ".post",
    ".hentry",
    ".type-post",
    ".type-page",
]


@dataclass
class PageData:
    url: str
    title: str = ""
    meta_description: str = ""
    status_code: int = 0
    depth: int = 0
    inlinks: list = field(default_factory=list)
    outlinks: list = field(default_factory=list)
    content_links: list = field(default_factory=list)
    word_count: int = 0
    h1: list = field(default_factory=list)
    error: str = ""


class SEOCrawler:
    def __init__(
        self,
        start_url: str,
        max_urls: int = 2000,
        delay: float = 0.5,
        on_progress: Optional[Callable] = None,
        config: Optional[dict] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        self.start_url = start_url.rstrip("/")
        self.parsed_start = urlparse(self.start_url)
        self.base_domain = self.parsed_start.netloc
        self.max_urls = max_urls
        self.delay = delay
        self.on_progress = on_progress
        self.config = config or {}
        self.stop_event = stop_event or threading.Event()

        self.visited: dict[str, PageData] = {}
        self.queue: deque = deque()
        self.robots_blocked = 0
        self.sitemap_blacklist: set = set()
        self.sitemap_seeds: list = []

        self.robots = RobotFileParser()
        if self.config.get("respect_robots", True):
            self._setup_robots()

        sitemap_mode = self.config.get("sitemap_mode", "discover")
        if sitemap_mode == "exclude":
            self._load_sitemap(blacklist=True)
        elif sitemap_mode == "discover":
            self._load_sitemap(blacklist=False)

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "SEOCrawlerBot/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr,en-US;q=0.7,en;q=0.3",
        })

    # ── ROBOTS ────────────────────────────────────────────────────────────────

    def _setup_robots(self):
        robots_url = f"{self.parsed_start.scheme}://{self.base_domain}/robots.txt"
        self.robots.set_url(robots_url)
        try:
            self.robots.read()
        except Exception:
            pass

    def _is_allowed(self, url: str) -> bool:
        if not self.config.get("respect_robots", True):
            return True
        allowed = self.robots.can_fetch("*", url)
        if not allowed:
            self.robots_blocked += 1
        return allowed

    # ── SITEMAP ───────────────────────────────────────────────────────────────

    def _load_sitemap(self, blacklist: bool):
        sitemap_url = f"{self.parsed_start.scheme}://{self.base_domain}/sitemap.xml"
        urls = self._parse_sitemap(sitemap_url, visited=set())
        if blacklist:
            self.sitemap_blacklist = set(urls)
        else:
            self.sitemap_seeds = [u for u in urls if self._is_same_domain(u)]

    def _parse_sitemap(self, url: str, visited: set, depth: int = 0) -> list:
        if depth > 3 or url in visited:
            return []
        visited.add(url)
        urls = []
        try:
            r = self.session.get(url, timeout=8)
            if r.status_code != 200:
                return []
            root = ET.fromstring(r.text)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            # Sitemap index
            for loc in root.findall(".//sm:sitemap/sm:loc", ns):
                urls += self._parse_sitemap(loc.text.strip(), visited, depth + 1)
            # URL set
            for loc in root.findall(".//sm:url/sm:loc", ns):
                urls.append(loc.text.strip())
        except Exception:
            pass
        return urls

    # ── URL FILTERING ─────────────────────────────────────────────────────────

    def _normalize_url(self, url: str) -> str:
        url, _ = urldefrag(url)
        parsed = urlparse(url)
        if self.config.get("strip_params", False):
            parsed = parsed._replace(query="")
        path = parsed.path.rstrip("/") or "/"
        return parsed._replace(path=path).geturl()

    def _is_same_domain(self, url: str) -> bool:
        return urlparse(url).netloc == self.base_domain

    def _is_crawlable(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False

        # Extension filter
        if self.config.get("filter_extensions", True):
            ext = parsed.path.lower().rsplit(".", 1)[-1] if "." in parsed.path else ""
            custom_exts = set(self.config.get("skip_extensions", []))
            skip = DEFAULT_SKIP_EXTS | custom_exts
            if ext in skip:
                return False

        # Sitemap blacklist
        if url in self.sitemap_blacklist:
            return False

        path = parsed.path
        full = url

        # Prefix exclusions
        for prefix in self.config.get("exclude_prefixes", []):
            prefix = prefix.strip()
            if prefix and path.startswith(prefix):
                return False

        # Keyword exclusions
        for kw in self.config.get("exclude_keywords", []):
            kw = kw.strip()
            if kw and kw in full:
                return False

        return True

    # ── PAGE EXTRACTION ───────────────────────────────────────────────────────

    def _extract_page_data(self, url: str, depth: int) -> PageData:
        page = PageData(url=url, depth=depth)
        try:
            resp = self.session.get(url, timeout=10, allow_redirects=True)
            page.status_code = resp.status_code
            if resp.status_code != 200:
                return page

            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return page

            soup = BeautifulSoup(resp.text, "html.parser")

            title_tag = soup.find("title")
            page.title = title_tag.get_text(strip=True) if title_tag else ""

            meta_desc = soup.find("meta", attrs={"name": re.compile("description", re.I)})
            if meta_desc:
                page.meta_description = meta_desc.get("content", "")

            page.h1 = [h.get_text(strip=True) for h in soup.find_all("h1")]

            body = soup.find("body")
            if body:
                page.word_count = len(body.get_text(separator=" ").split())

            if self.config.get("exclude_nav_footer", False):
                # Re-parse fresh to safely mutate the tree
                link_soup = BeautifulSoup(resp.text, "html.parser")
                # Semantic elements
                for tag in link_soup.find_all(["nav", "header", "footer"]):
                    tag.decompose()
                # ARIA roles
                for role in ("navigation", "banner", "contentinfo"):
                    for tag in link_soup.find_all(attrs={"role": role}):
                        tag.decompose()
                # Class-based (BS4 returns class as a list)
                NAV_CLASSES = {"menu", "nav", "navigation", "header", "footer",
                               "sidebar", "breadcrumb", "top-bar", "topbar", "menubar"}
                for tag in link_soup.find_all(class_=True):
                    tag_classes = {c.lower() for c in tag.get("class", [])}
                    if tag_classes & NAV_CLASSES:
                        try:
                            tag.decompose()
                        except Exception:
                            pass
            else:
                link_soup = soup

            links = set()
            for a in link_soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue
                abs_url = self._normalize_url(urljoin(url, href))
                if self._is_same_domain(abs_url) and self._is_crawlable(abs_url):
                    links.add(abs_url)

            page.outlinks = list(links)
            page.content_links = self._extract_content_links(resp.text, url)

        except requests.exceptions.Timeout:
            page.status_code = 0
            page.error = "Timeout"
        except requests.exceptions.ConnectionError:
            page.status_code = 0
            page.error = "Connection error"
        except Exception as e:
            page.status_code = 0
            page.error = str(e)

        return page

    # ── CONTENT LINKS ─────────────────────────────────────────────────────────

    def _extract_content_links(self, html: str, base_url: str) -> list:
        content_soup = BeautifulSoup(html, "html.parser")

        # Remove structural nav blocks by tag/role
        for sel in NAV_SELECTORS_CSS:
            for tag in content_soup.select(sel):
                try:
                    tag.decompose()
                except Exception:
                    pass

        # Remove class/id based nav elements
        for tag in content_soup.find_all(True):
            try:
                classes = {c.lower() for c in tag.get("class", [])}
                tag_id = (tag.get("id") or "").lower()
                if (classes & NAV_CLASSES) or tag_id in NAV_IDS:
                    tag.decompose()
            except Exception:
                pass

        # Find editorial content area
        content_area = None
        for sel in CONTENT_SELECTORS:
            content_area = content_soup.select_one(sel)
            if content_area:
                break
        if not content_area:
            content_area = content_soup.find("body") or content_soup

        links = set()
        for a in content_area.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            abs_url = self._normalize_url(urljoin(base_url, href))
            if self._is_same_domain(abs_url) and self._is_crawlable(abs_url):
                links.add(abs_url)

        return list(links)

    # ── CRAWL LOOP ────────────────────────────────────────────────────────────

    def crawl(self) -> dict:
        self.visited = {}
        start = self._normalize_url(self.start_url)
        queued = {start}

        # Seed from sitemap first for discovery mode
        for seed_url in self.sitemap_seeds[:500]:
            norm = self._normalize_url(seed_url)
            if norm not in queued:
                self.queue.append((norm, 1))
                queued.add(norm)

        self.queue.appendleft((start, 0))

        while self.queue and len(self.visited) < self.max_urls:
            if self.stop_event.is_set():
                break

            url, depth = self.queue.popleft()
            if url in self.visited:
                continue
            if not self._is_allowed(url):
                continue

            page = self._extract_page_data(url, depth)
            self.visited[url] = page

            if self.on_progress:
                self.on_progress(
                    crawled=len(self.visited),
                    total_queued=len(self.visited) + len(self.queue),
                    current_url=url,
                    robots_blocked=self.robots_blocked,
                    stopped=self.stop_event.is_set(),
                )

            for outlink in page.outlinks:
                if outlink not in self.visited and outlink not in queued:
                    self.queue.append((outlink, depth + 1))
                    queued.add(outlink)
                if outlink in self.visited:
                    if url not in self.visited[outlink].inlinks:
                        self.visited[outlink].inlinks.append(url)

            if self.delay > 0 and not self.stop_event.is_set():
                time.sleep(self.delay)

        # Build inlinks
        for url, page in self.visited.items():
            for outlink in page.outlinks:
                if outlink in self.visited:
                    if url not in self.visited[outlink].inlinks:
                        self.visited[outlink].inlinks.append(url)

        return self.export_json()

    def stop(self):
        self.stop_event.set()

    # ── EXPORT ────────────────────────────────────────────────────────────────

    def export_json(self) -> dict:
        nodes = []
        edges = []
        url_index = {url: i for i, url in enumerate(self.visited)}

        for url, page in self.visited.items():
            content_link_ids = [url_index[u] for u in page.content_links if u in url_index]
            nodes.append({
                "id": url_index[url],
                "url": url,
                "title": page.title,
                "meta_description": page.meta_description,
                "status_code": page.status_code,
                "depth": page.depth,
                "inlinks_count": len(page.inlinks),
                "outlinks_count": len(page.outlinks),
                "content_link_ids": content_link_ids,
                "content_link_count": len(content_link_ids),
                "word_count": page.word_count,
                "h1": page.h1,
                "error": page.error,
            })
            for outlink in page.outlinks:
                if outlink in url_index:
                    edges.append({"source": url_index[url], "target": url_index[outlink]})

        return {
            "meta": {
                "start_url": self.start_url,
                "total_pages": len(nodes),
                "total_edges": len(edges),
                "max_depth": max((n["depth"] for n in nodes), default=0),
                "robots_blocked": self.robots_blocked,
                "stopped": self.stop_event.is_set(),
            },
            "nodes": nodes,
            "edges": edges,
        }


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    max_urls = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    def progress(crawled, total_queued, current_url, robots_blocked=0, stopped=False):
        print(f"[{crawled}/{min(total_queued, max_urls)}] {current_url}")

    crawler = SEOCrawler(url, max_urls=max_urls, delay=0.5, on_progress=progress)
    data = crawler.crawl()

    with open("data/crawl.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nTerminé : {data['meta']['total_pages']} pages")
