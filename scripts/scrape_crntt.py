"""scrape_crntt.py — 爬取中評社文章 (2023-01-01 至今)

用法:
    python scripts/scrape_crntt.py                # 完整爬取
    python scripts/scrape_crntt.py --list-only    # 只爬列表不抓正文
    python scripts/scrape_crntt.py --resume       # 從上次中斷處繼續抓正文
"""

import argparse
import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests

BASE = "https://hk.crntt.com"
DATA_DIR = Path(__file__).parent.parent / "data"
INDEX_PATH = DATA_DIR / "crntt_index.json"
OUTPUT_PATH = DATA_DIR / "crntt_corpus.json"

CUTOFF = datetime(2023, 1, 1)

# 分類定義: (name, category, subcategory, url_type, coluid, kindid)
CATEGORIES = [
    ("社評", "觀察", "社評", "kind", 136, 4710),
    ("快評", "觀察", "快評", "kind", 136, 21933),
    ("專論", "觀察", "專論", "kind", 136, 4711),
    ("分析", "觀察", "分析", "kind", 136, 4712),
    ("智庫匯聚", "評論", "智庫匯聚", "kind", 5, 22051),
    ("社評摘要", "評論", "社評摘要", "kind", 5, 22),
    ("專家訪談", "評論", "專家訪談", "kind", 5, 21960),
    ("觀察分析", "評論", "觀察分析", "kind", 5, 24),
    ("國際輿論", "評論", "國際輿論", "kind", 5, 25),
    ("兩岸動態", "兩岸", "動態", "kind", 3, 12),
    ("兩岸綜合", "兩岸", "綜合", "kind", 3, 21824),
    ("兩岸分析", "兩岸", "分析", "kind", 3, 14),
    ("兩岸專訪", "兩岸", "專訪", "kind", 3, 15),
    ("北京來論", "兩岸", "北京來論", "kind", 3, 21932),
    ("台灣", "台灣", "", "msg", 46, 0),
    ("藍營", "台灣", "藍營", "msg", 255, 0),
    ("綠營", "台灣", "綠營", "msg", 142, 0),
    ("白營", "台灣", "白營", "msg", 397, 0),
]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})

# --- 列表爬取 ---

LI_RE = re.compile(
    r'<li><a href="(/doc/[^"]+)"[^>]*>([^<]+)</a>\s*<font[^>]*><em>\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\)</em>',
)
TOTAL_RE = re.compile(r"共(\d+)條")
DOCID_RE = re.compile(r"_(\d+)_\d+_\d+\.html")


def list_url(cat):
    _, _, _, url_type, coluid, kindid = cat
    if url_type == "kind":
        return f"{BASE}/crn-webapp/kindOutline.jsp?coluid={coluid}&kindid={kindid}"
    return f"{BASE}/crn-webapp/msgOutline.jsp?coluid={coluid}"


def scrape_list_page(url, page):
    sep = "&" if "?" in url else "?"
    full_url = f"{url}{sep}page={page}" if page > 1 else url
    resp = SESSION.get(full_url, timeout=20)
    resp.encoding = "utf-8"
    return resp.text


def scrape_category(cat):
    """爬取一個分類的所有文章列表，回傳 list of dict。遇到 cutoff 日期前的文章就停。"""
    name, category, subcategory, _, coluid, kindid = cat
    url = list_url(cat)
    articles = []
    page = 1

    # 先取總頁數
    html = scrape_list_page(url, 1)
    m = TOTAL_RE.search(html)
    total = int(m.group(1)) if m else 0
    per_page = 60 if "kindOutline" in url else 100
    max_pages = (total // per_page) + 1

    while page <= max_pages:
        if page > 1:
            html = scrape_list_page(url, page)
        
        matches = LI_RE.findall(html)
        if not matches:
            break

        stop = False
        for path, title, date_str in matches:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            if dt < CUTOFF:
                stop = True
                break
            docid_m = DOCID_RE.search(path)
            docid = docid_m.group(1) if docid_m else path
            articles.append({
                "docid": docid,
                "title": title.strip(),
                "date": date_str,
                "url": path,
                "category": category,
                "subcategory": subcategory,
            })

        if stop:
            break
        page += 1
        time.sleep(0.3)

    print(f"  {name}: {len(articles)} 篇 (2023至今)")
    return articles


# --- 正文爬取 ---

PAGE_RE = re.compile(r"<a href='(/doc/[^']+)'>第\d+頁</a>")


def extract_body(html):
    """從單頁 HTML 提取正文。"""
    parts = re.split(r'</TABLE>', html, flags=re.IGNORECASE)
    text = ""
    for part in parts[1:]:
        if "中評社" in part or len(part) > 500:
            clean = re.sub(r'<[^>]+>', '', part)
            clean = re.sub(r'&nbsp;', ' ', clean)
            clean = re.sub(r'\r\n|\r', '\n', clean)
            clean = re.sub(r'[ \t]+', ' ', clean)
            clean = re.sub(r'\n{3,}', '\n\n', clean)
            cut = re.search(r'(掃描二維碼|相關新聞|更多 >>|您的位置|【 第\d+頁)', clean)
            if cut:
                clean = clean[:cut.start()]
            clean = clean.strip()
            if len(clean) > len(text):
                text = clean
    return text


def fetch_article(path):
    """抓取單篇文章正文（含多頁）。"""
    url = BASE + path
    resp = SESSION.get(url, timeout=20, allow_redirects=True)
    resp.encoding = "utf-8"
    html = resp.text

    text = extract_body(html)

    # 處理多頁
    pages = PAGE_RE.findall(html)
    for page_path in pages:
        time.sleep(0.3)
        resp2 = SESSION.get(BASE + page_path, timeout=20, allow_redirects=True)
        resp2.encoding = "utf-8"
        page_text = extract_body(resp2.text)
        if page_text:
            text += "\n\n" + page_text

    return text


# --- 主程式 ---

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-only", action="store_true", help="只爬列表")
    parser.add_argument("--resume", action="store_true", help="從上次中斷處繼續")
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()

    # Step 1: 爬列表
    if args.resume and INDEX_PATH.exists():
        print("=== 載入已有索引 ===")
        articles = json.loads(INDEX_PATH.read_text("utf-8"))
    else:
        print("=== 爬取文章列表 ===")
        all_articles = []
        for cat in CATEGORIES:
            all_articles.extend(scrape_category(cat))
            time.sleep(0.5)

        # 去重 (用 docid)
        seen = {}
        for a in all_articles:
            did = a["docid"]
            if did not in seen:
                seen[did] = a
        articles = list(seen.values())
        articles.sort(key=lambda x: x["date"], reverse=True)
        print(f"\n=== 去重後共 {len(articles)} 篇 ===")

        INDEX_PATH.write_text(json.dumps(articles, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"索引已存: {INDEX_PATH}")

    if args.list_only:
        return

    # Step 2: 爬正文
    print(f"\n=== 爬取正文 ({len(articles)} 篇) ===")

    # 載入已有結果
    done = {}
    if args.resume and OUTPUT_PATH.exists():
        for line in OUTPUT_PATH.read_text("utf-8").strip().split("\n"):
            if line:
                obj = json.loads(line)
                done[obj["docid"]] = True
        print(f"  已完成 {len(done)} 篇，繼續剩餘...")

    # 用 append 模式寫入 JSONL
    with open(OUTPUT_PATH, "a", encoding="utf-8") as f:
        count = len(done)
        for i, art in enumerate(articles):
            if art["docid"] in done:
                continue
            try:
                text = fetch_article(art["url"])
                if text and len(text) > 50:
                    record = {
                        "docid": art["docid"],
                        "title": art["title"],
                        "date": art["date"],
                        "category": art["category"],
                        "subcategory": art["subcategory"],
                        "url": BASE + art["url"],
                        "text": text,
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    f.flush()
                    count += 1
            except Exception as e:
                print(f"  [ERR] {art['title']}: {e}")

            if (i + 1) % 50 == 0:
                print(f"  進度: {i+1}/{len(articles)}, 成功: {count}")
            time.sleep(0.5)

    print(f"\n=== 完成: {count} 篇 → {OUTPUT_PATH} ===")


if __name__ == "__main__":
    main()
