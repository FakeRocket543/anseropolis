"""scrape_upmedia.py — 用 Playwright 爬取上報評論全文 (2023-01-01 至今)

7 個分類：上報專欄、國內政經、國際局勢、國防軍事、中港透視、讀者投書、想想論壇

用法:
    python3 scripts/scrape_upmedia.py
"""

import re
import time
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

DATA_DIR = Path(__file__).parent.parent / "data"
BASE = "https://www.upmedia.mg"
CATEGORIES = [
    "columnists",
    "political-and-economics-debate",
    "world-affairs",
    "military-affairs",
    "china-hong-kong-insights",
    "reader-submissions",
    "thinking-taiwan",
]
START_DATE = date(2023, 1, 1)
CTX_OPTS = dict(
    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    viewport={"width": 1920, "height": 1080},
    locale="zh-TW",
)
INIT_SCRIPT = 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'


def open_page(browser, url, timeout=20000):
    """Open URL in fresh context, return (page, context). Caller must close ctx."""
    ctx = browser.new_context(**CTX_OPTS)
    page = ctx.new_page()
    page.add_init_script(INIT_SCRIPT)
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    page.wait_for_timeout(2000)
    return page, ctx


def collect_urls(browser, category_slug: str) -> list[str]:
    """Paginate through a category listing, collect article URLs."""
    urls = []
    seen = set()
    pg = 1
    while True:
        url = f"{BASE}/tw/commentary/{category_slug}?p={pg}"
        try:
            page, ctx = open_page(browser, url)
        except Exception:
            break

        try:
            links = page.query_selector_all("a[href*='/tw/commentary/']")
            new_count = 0
            for link in links:
                href = link.get_attribute("href") or ""
                if re.search(r"/\d+$", href) and href not in seen:
                    seen.add(href)
                    urls.append(f"{BASE}{href}" if href.startswith("/") else href)
                    new_count += 1

            if new_count == 0:
                ctx.close()
                break

            page_text = page.inner_text("body")
            dates_found = re.findall(r"\d{4}-\d{2}-\d{2}", page_text)
        finally:
            ctx.close()

        if dates_found and min(dates_found) < "2023-01-01":
            break

        pg += 1
        if pg % 10 == 0:
            print(f"    page {pg}, {len(urls)} urls")
        if pg > 500:
            break
        time.sleep(0.5)

    return urls


def fetch_article(browser, url: str) -> str | None:
    """Fetch article body text."""
    try:
        page, ctx = open_page(browser, url)
    except Exception:
        return None

    try:
        text = page.inner_text("body")
    finally:
        ctx.close()

    if len(text) < 500:
        return None

    # Check date
    m = re.search(r"(\d{4})年(\d{2})月(\d{2})日", text)
    if m:
        art_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if art_date < START_DATE:
            return None

    # Extract body
    m = re.search(
        r"\d{4}年\d{2}月\d{2}日 \d{2}:\d{2}:\d{2}\n(.*?)"
        r"(?:猜你喜歡|Recommended by|【上報徵稿】|評論熱門新聞)",
        text,
        re.DOTALL,
    )
    if not m:
        return None

    body = m.group(1).strip()
    if len(body) < 100:
        return None

    lines = []
    for l in body.split("\n"):
        l = l.strip()
        if not l or l == "\xa0":
            continue
        if re.match(r"(PR・|AD・|推薦閱讀|延伸閱讀|Recommended|猜你喜歡)", l):
            break
        lines.append(l)

    result = "\n".join(lines)
    return result if len(result) >= 100 else None


def main():
    out_path = DATA_DIR / "upmedia_corpus.txt"
    all_urls = set()
    all_texts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )

        # Step 1: Collect URLs from all categories
        for cat_slug in CATEGORIES:
            print(f"\n[列表] {cat_slug}")
            urls = collect_urls(browser, cat_slug)
            new = [u for u in urls if u not in all_urls]
            all_urls.update(urls)
            print(f"  {len(urls)} links ({len(new)} new, {len(all_urls)} total)")

        print(f"\n{'='*50}")
        print(f"Total unique URLs: {len(all_urls)}")
        print(f"{'='*50}")

        # Step 2: Fetch articles
        url_list = sorted(all_urls)
        count = 0
        for i, art_url in enumerate(url_list):
            text = fetch_article(browser, art_url)
            if text:
                all_texts.append(text)
                count += 1
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(url_list)}: {count} texts")
            time.sleep(0.5)

        browser.close()

    corpus = "\n\n".join(all_texts)
    out_path.write_text(corpus, encoding="utf-8")
    print(f"\nDone: {len(all_texts)} articles, {len(corpus):,} chars → {out_path}")


if __name__ == "__main__":
    main()
