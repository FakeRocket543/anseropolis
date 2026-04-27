"""scrape_media.py — 用 Playwright 抓取需要 JS 渲染的媒體全文

用法:
    pip install playwright
    playwright install chromium
    python scripts/scrape_media.py --source ct      # 中時
    python scripts/scrape_media.py --source cnews   # 匯流新聞網
    python scripts/scrape_media.py --source ltn     # 自由時報
"""

import argparse
import json
import re
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


def scrape_ct(page, max_pages=200):
    """中時電子報 opinion section."""
    articles = []
    for pg in range(1, max_pages + 1):
        page.goto(f"https://www.chinatimes.com/opinion/total?page={pg}&chdtv", wait_until="networkidle")
        links = page.query_selector_all("h3 a[href*='/opinion/']")
        if not links:
            break
        for link in links:
            href = link.get_attribute("href") or ""
            title = link.inner_text().strip()
            if title and "/opinion/" in href:
                url = f"https://www.chinatimes.com{href}" if href.startswith("/") else href
                articles.append({"title": title, "url": url})
        print(f"  CT page {pg}: {len(articles)} total")
        time.sleep(1)
    return articles


def scrape_cnews(page, max_pages=100):
    """匯流新聞網 觀點匯流."""
    articles = []
    # Main page viewpoint section
    page.goto("https://cnews.com.tw", wait_until="networkidle")
    # Click "更多觀點匯流" or scroll
    links = page.query_selector_all("a[href*='cnews.com.tw']")
    for link in links:
        title = link.inner_text().strip()
        href = link.get_attribute("href") or ""
        if ("專欄" in title or "社論" in title) and len(title) > 10:
            articles.append({"title": title, "url": href})

    # Try viewpoint category pages
    for pg in range(1, max_pages + 1):
        try:
            page.goto(f"https://cnews.com.tw/category/viewpoint/page/{pg}/", wait_until="networkidle", timeout=10000)
            links = page.query_selector_all("article a, h3 a, .post-title a")
            if not links:
                break
            for link in links:
                href = link.get_attribute("href") or ""
                title = link.inner_text().strip()
                if title and len(title) > 10 and "cnews.com.tw" in href:
                    articles.append({"title": title, "url": href})
            print(f"  CNEWS page {pg}: {len(articles)} total")
        except:
            break
        time.sleep(1)
    return articles


def scrape_ltn(page, max_pages=100):
    """自由時報 社論."""
    articles = []
    page.goto("https://talk.ltn.com.tw/", wait_until="networkidle")

    # Find editorial links
    links = page.query_selector_all("a[href*='talk.ltn.com.tw/article']")
    for link in links:
        href = link.get_attribute("href") or ""
        title = link.inner_text().strip()
        if "社論" in title and len(title) > 5:
            articles.append({"title": title, "url": href})

    # Try paginated editorial listing
    for pg in range(1, max_pages + 1):
        try:
            page.goto(f"https://talk.ltn.com.tw/article/paper?page={pg}", wait_until="networkidle", timeout=10000)
            links = page.query_selector_all("a[href*='/article/paper/']")
            if not links:
                break
            for link in links:
                href = link.get_attribute("href") or ""
                title = link.inner_text().strip()
                if title and len(title) > 5:
                    articles.append({"title": title, "url": href})
            print(f"  LTN page {pg}: {len(articles)} total")
        except:
            break
        time.sleep(1)
    return articles


def fetch_full_text(page, url, source):
    """Fetch article full text."""
    try:
        page.goto(url, wait_until="networkidle", timeout=15000)
        selectors = {
            "ct": "div.article-body, article .post-content",
            "cnews": "div.entry-content, article .post-content",
            "ltn": "div.text, div.article_content",
        }
        el = page.query_selector(selectors.get(source, "article"))
        if el:
            text = el.inner_text().strip()
            return text[:5000] if len(text) > 100 else None
    except:
        pass
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, choices=["ct", "cnews", "ltn"])
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--max-articles", type=int, default=500)
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Step 1: Get article URLs
        print(f"=== Scraping {args.source} article list ===")
        if args.source == "ct":
            articles = scrape_ct(page, args.max_pages)
        elif args.source == "cnews":
            articles = scrape_cnews(page, args.max_pages)
        else:
            articles = scrape_ltn(page, args.max_pages)

        # Deduplicate
        seen = set()
        unique = []
        for a in articles:
            if a["url"] not in seen:
                seen.add(a["url"])
                unique.append(a)
        articles = unique[:args.max_articles]
        print(f"  Unique articles: {len(articles)}")

        # Step 2: Fetch full text
        print(f"\n=== Fetching full text ===")
        texts = []
        for i, art in enumerate(articles):
            text = fetch_full_text(page, art["url"], args.source)
            if text:
                texts.append(text)
            if (i + 1) % 20 == 0:
                print(f"  {i+1}/{len(articles)}: {len(texts)} texts")
            time.sleep(0.5)

        browser.close()

    # Save
    corpus = "\n\n".join(texts)
    out_path = DATA_DIR / f"{args.source}_corpus.txt"
    out_path.write_text(corpus, encoding="utf-8")
    print(f"\n=== Done: {len(texts)} articles, {len(corpus):,} chars → {out_path} ===")


if __name__ == "__main__":
    main()
