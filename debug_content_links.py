"""
Script de diagnostic : teste l'extraction des liens éditoriaux sur une URL donnée.
Usage : python debug_content_links.py https://cataneo-investissement-immobilier.fr/nos-actualites/municipales-lyon-immobilier/
"""
import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag

# ─── Copie des sélecteurs du crawler ───
NAV_SELECTORS_CSS = [
    "header", "footer", "nav", "aside",
    "[role='navigation']", "[role='banner']", "[role='contentinfo']",
    ".nav", ".menu", ".navigation", ".header", ".footer",
    ".sidebar", ".breadcrumb", ".breadcrumbs",
    "#menu", "#nav", "#header", "#footer", "#sidebar",
    "#wpadminbar", ".wp-block-navigation", ".wp-block-template-part",
    ".site-header", ".site-footer", ".site-navigation",
    ".wp-site-blocks > header", ".wp-site-blocks > footer",
    ".elementor-location-header", ".elementor-location-footer",
    "#main-header", "#main-footer", ".et-menu-nav",
    ".fusion-header-wrapper", ".fusion-footer-widget-area", ".fusion-footer",
    ".genesis-nav-menu", ".genesis-skip-link",
    ".related-posts", ".related", ".post-related",
    ".author-bio", ".author-box", ".post-author",
    ".social-share", ".share-buttons", ".sharedaddy",
    ".tags-links", ".cat-links", ".post-tags", ".post-categories",
    "#comments", ".comments-area", ".comment-list",
    ".cookie-banner", ".cookie-notice", "#cookie-law-info-bar",
    ".popup", ".modal", ".overlay",
    ".pagination", ".wp-pagenavi", ".nav-links",
    ".search-form", ".search-widget",
]
NAV_CLASSES = {
    "nav", "menu", "navigation", "header", "footer",
    "sidebar", "breadcrumb", "breadcrumbs",
    "top-bar", "topbar", "menubar",
    "site-header", "site-footer", "site-navigation",
    "wp-block-navigation",
    "elementor-location-header", "elementor-location-footer",
    "related-posts", "author-bio", "author-box",
    "social-share", "share-buttons", "post-tags", "post-categories",
    "tags-links", "cat-links", "pagination", "nav-links",
    "comments-area", "comment-list",
}
NAV_IDS = {"menu", "nav", "header", "footer", "sidebar", "wpadminbar", "main-header", "main-footer", "comments"}
CONTENT_SELECTORS = [
    "article.hentry", "article.type-post", "article.type-page",
    ".elementor-widget-theme-post-content", ".et_pb_post_content",
    ".entry-content", ".post-content", ".page-content", ".wp-block-post-content", ".single-content",
    ".content", ".content-area", ".content-wrapper", ".article-content", ".article-body",
    ".post-body", ".post-entry", ".blog-content", ".page-body", ".main-content", ".main-body",
    "#main-content", "#post-content", "#article-content",
    "main", "[role='main']", "article",
    "#content",
    ".rich-text", ".w-richtext",
    ".blog-post__body", ".hb-blog-post", ".sqs-block-html",
    ".post", ".hentry", ".type-post", ".type-page",
]

def normalize(url):
    url, _ = urldefrag(url)
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return p._replace(path=path).geturl()

def extract(html, base_url):
    base_domain = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "html.parser")

    # 1. Suppression des blocs nav par sélecteur CSS
    removed_css = 0
    for sel in NAV_SELECTORS_CSS:
        for tag in soup.select(sel):
            try: tag.decompose(); removed_css += 1
            except: pass

    # 2. Suppression par classe/id
    removed_cls = 0
    for tag in soup.find_all(True):
        try:
            classes = {c.lower() for c in tag.get("class", [])}
            tag_id = (tag.get("id") or "").lower()
            if (classes & NAV_CLASSES) or tag_id in NAV_IDS:
                tag.decompose(); removed_cls += 1
        except: pass

    print(f"\n[NAV REMOVAL] {removed_css} blocs CSS + {removed_cls} blocs classe/id supprimés")

    # 3. Recherche zone éditoriale
    content_area = None
    matched_sel = None
    for sel in CONTENT_SELECTORS:
        content_area = soup.select_one(sel)
        if content_area:
            matched_sel = sel
            break

    if not content_area:
        print("[CONTENT AREA] Aucun sélecteur matché → fallback body")
        content_area = soup.find("body") or soup
    else:
        print(f"[CONTENT AREA] Sélecteur matché : {matched_sel}")
        print(f"               Classes : {content_area.get('class')}")
        print(f"               ID      : {content_area.get('id')}")

    # 4. Extraction des liens
    links = []
    for a in content_area.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        abs_url = normalize(urljoin(base_url, href))
        if urlparse(abs_url).netloc == base_domain:
            links.append((abs_url, a.get_text(strip=True)))

    return links

def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://cataneo-investissement-immobilier.fr/nos-actualites/municipales-lyon-immobilier/"
    print(f"\nTest extraction liens éditoriaux sur :\n{url}\n{'─'*70}")

    r = requests.get(url, timeout=15, headers={"User-Agent": "SEOCrawlerBot/1.0"})
    print(f"Status HTTP : {r.status_code}")

    links = extract(r.text, url)

    print(f"\n[LIENS ÉDITORIAUX TROUVÉS] {len(links)} liens internes\n")
    for href, anchor in links:
        print(f"  • {anchor[:60]:<60} → {href}")

if __name__ == "__main__":
    main()
