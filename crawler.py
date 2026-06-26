import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser
import json
import time
import re
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable


@dataclass
class PageData:
    url: str
    title: str = ""
    meta_description: str = ""
    status_code: int = 0
    depth: int = 0
    inlinks: list = field(default_factory=list)
    outlinks: list = field(default_factory=list)
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
    ):
        self.start_url = start_url.rstrip("/")
        self.parsed_start = urlparse(self.start_url)
        self.base_domain = self.parsed_start.netloc
        self.max_urls = max_urls
        self.delay = delay
        self.on_progress = on_progress

        self.visited: dict[str, PageData] = {}
        self.queue: deque = deque()
        self.robots = RobotFileParser()
        self._setup_robots()

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "SEOCrawlerBot/1.0 (+https://github.com/seo-crawler)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr,en-US;q=0.7,en;q=0.3",
            }
        )
        self.running = False

    def _setup_robots(self):
        robots_url = f"{self.parsed_start.scheme}://{self.base_domain}/robots.txt"
        self.robots.set_url(robots_url)
        try:
            self.robots.read()
        except Exception:
            pass

    def _is_allowed(self, url: str) -> bool:
        return self.robots.can_fetch("*", url)

    def _normalize_url(self, url: str) -> str:
        url, _ = urldefrag(url)
        parsed = urlparse(url)
        # Remove trailing slash except for root
        path = parsed.path.rstrip("/") or "/"
        return parsed._replace(path=path, query=parsed.query).geturl()

    def _is_same_domain(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc == self.base_domain

    def _is_crawlable(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        ext = parsed.path.lower().split(".")[-1] if "." in parsed.path else ""
        skip_exts = {
            "pdf", "jpg", "jpeg", "png", "gif", "svg", "webp", "ico",
            "css", "js", "woff", "woff2", "ttf", "eot", "mp4", "mp3",
            "zip", "gz", "tar", "exe", "dmg", "xml", "json",
        }
        return ext not in skip_exts

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

            h1_tags = soup.find_all("h1")
            page.h1 = [h.get_text(strip=True) for h in h1_tags]

            body = soup.find("body")
            if body:
                text = body.get_text(separator=" ")
                page.word_count = len(text.split())

            links = set()
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue
                abs_url = self._normalize_url(urljoin(url, href))
                if self._is_same_domain(abs_url) and self._is_crawlable(abs_url):
                    links.add(abs_url)

            page.outlinks = list(links)

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

    def crawl(self) -> dict:
        self.running = True
        self.visited = {}
        self.queue = deque()

        start = self._normalize_url(self.start_url)
        self.queue.append((start, 0))
        queued = {start}

        while self.queue and len(self.visited) < self.max_urls and self.running:
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
                )

            for outlink in page.outlinks:
                if outlink not in self.visited and outlink not in queued:
                    self.queue.append((outlink, depth + 1))
                    queued.add(outlink)
                if outlink in self.visited:
                    self.visited[outlink].inlinks.append(url)

            if self.delay > 0:
                time.sleep(self.delay)

        # Build inlinks from outlinks for pages already visited
        for url, page in self.visited.items():
            for outlink in page.outlinks:
                if outlink in self.visited:
                    if url not in self.visited[outlink].inlinks:
                        self.visited[outlink].inlinks.append(url)

        self.running = False
        return self.export_json()

    def stop(self):
        self.running = False

    def export_json(self) -> dict:
        nodes = []
        edges = []
        url_index = {url: i for i, url in enumerate(self.visited)}

        for url, page in self.visited.items():
            nodes.append(
                {
                    "id": url_index[url],
                    "url": url,
                    "title": page.title,
                    "meta_description": page.meta_description,
                    "status_code": page.status_code,
                    "depth": page.depth,
                    "inlinks_count": len(page.inlinks),
                    "outlinks_count": len(page.outlinks),
                    "word_count": page.word_count,
                    "h1": page.h1,
                    "error": page.error,
                }
            )
            for outlink in page.outlinks:
                if outlink in url_index:
                    edges.append(
                        {"source": url_index[url], "target": url_index[outlink]}
                    )

        return {
            "meta": {
                "start_url": self.start_url,
                "total_pages": len(nodes),
                "total_edges": len(edges),
                "max_depth": max((n["depth"] for n in nodes), default=0),
            },
            "nodes": nodes,
            "edges": edges,
        }


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    max_urls = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    def progress(crawled, total_queued, current_url):
        print(f"[{crawled}/{min(total_queued, max_urls)}] {current_url}")

    crawler = SEOCrawler(url, max_urls=max_urls, delay=0.5, on_progress=progress)
    data = crawler.crawl()

    output = "data/crawl.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nCrawl terminé : {data['meta']['total_pages']} pages → {output}")
