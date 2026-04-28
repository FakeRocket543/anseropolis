"""自由時報評論網爬蟲 — 抓取所有言論分頻道全文（2023-01-01 至今）

策略:
  1. 用 list_ajax API 逐頁取得文章 URL（每頻道最多 300 篇）
  2. 用 paper ID 遞減掃描補充 API 抓不到的歷史文章
  3. 逐篇 GET 文章頁面，用 BeautifulSoup 解析全文
  4. 每個頻道存成獨立子資料夾，每篇存 JSON

用法:
    python3 -u scripts/scrape_ltn.py                  # 全部頻道
    python3 -u scripts/scrape_ltn.py --channel 社論   # 只抓社論
    python3 -u scripts/scrape_ltn.py --phase index    # 只做索引
    python3 -u scripts/scrape_ltn.py --phase fetch    # 只抓全文
    python3 -u scripts/scrape_ltn.py --phase scan     # 只做 ID 掃描
"""

import argparse
import json
import re
import time
from datetime import datetime
from functools import partial
from pathlib import Path

import requests
from bs4 import BeautifulSoup

print = partial(print, flush=True)

BASE = "https://talk.ltn.com.tw"
START_DATE = datetime(2023, 1, 1)
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "ltn"
DELAY_LIST = 1.5
DELAY_ARTICLE = 1.0
DELAY_SCAN = 0.3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# 數字 ID 頻道用 list_ajax/subcategory/{id}/{page}
# 字串 ID 頻道用 columnAjax/{id}/{page}
CHANNELS = {
    "社論": {"id": "8", "type": "list"},
    "自由共和國": {"id": "7", "type": "list"},
    "專論": {"id": "9", "type": "list"},
    "文化週報": {"id": "18", "type": "list"},
    "教育大小聲": {"id": "19", "type": "list"},
    "投書": {"id": "14", "type": "list"},
    "政經": {"id": "4", "type": "list"},
    "社會": {"id": "5", "type": "list"},
    "生活": {"id": "15", "type": "list"},
    "國際": {"id": "16", "type": "list"},
    "名人": {"id": "17", "type": "list"},
    "專欄": {"id": "column", "type": "column"},
    "社群": {"id": "media", "type": "column"},
}

# Paper ID 掃描範圍（2023/01/01 ~ 2026/04/28）
PAPER_ID_START = 1560500  # ~2023/01/01
PAPER_ID_END = 1753000    # ~2026/04/28 (留餘量)


def fetch(url: str, timeout: int = 30) -> requests.Response | None:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    return None


def fetch_json(url: str) -> list | None:
    r = fetch(url)
    if r is None:
        return None
    try:
        data = r.json()
        return data if isinstance(data, list) else None
    except ValueError:
        return None


def parse_date(date_str: str) -> datetime | None:
    """解析各種日期格式。"""
    for fmt in ("%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y%m%d%H%M%S", "%Y%m%d%H%M",
                "%Y-%m-%dT%H:%M:%S+08:00", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    # 嘗試 ISO 格式
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


# === 第一階段：AJAX API 索引 ===

def collect_channel_urls(channel_name: str, channel_info: dict) -> list[dict]:
    """用 AJAX API 收集某頻道所有文章 URL（最多 300 篇）。"""
    ch_id = channel_info["id"]
    ch_type = channel_info["type"]

    if ch_type == "list":
        api_tpl = f"{BASE}/list_ajax/subcategory/{ch_id}/{{}}"
    else:
        api_tpl = f"{BASE}/columnAjax/{ch_id}/{{}}"

    articles = []
    page = 1

    while True:
        url = api_tpl.format(page)
        data = fetch_json(url)

        if not data:
            break

        stop = False
        for item in data:
            view_time = item.get("LTNA_ViewTime", "")
            dt = parse_date(view_time)
            if dt and dt < START_DATE:
                stop = True
                break

            art_url = item.get("url", "")
            if not art_url:
                group = item.get("LTNA_Group", "breakingnews")
                no = item.get("LTNA_No", "")
                if no:
                    art_url = f"{BASE}/article/{group}/{no}"

            if art_url:
                articles.append({
                    "title": item.get("LTNA_Title", ""),
                    "date": view_time,
                    "url": art_url,
                })

        if stop:
            break

        page += 1
        time.sleep(DELAY_LIST)

    return articles


# === 第二階段：Paper ID 掃描 ===

def scan_paper_ids(progress_file: Path) -> list[dict]:
    """並行掃描 paper ID 範圍，找出所有 talk 文章。
    
    第一遍：10 並行 GET 找出有效 ID
    第二遍：逐篇解析標題和日期
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 載入進度
    if progress_file.exists():
        progress = json.loads(progress_file.read_text())
        scanned_up_to = progress.get("scanned_up_to", PAPER_ID_END)
        articles = progress.get("articles", [])
        print(f"  恢復掃描進度: 已掃到 ID {scanned_up_to}, 找到 {len(articles)} 篇")
    else:
        scanned_up_to = PAPER_ID_END
        articles = []

    already_found = {a["url"] for a in articles}

    def check_id(tid):
        try:
            r = requests.get(f"{BASE}/article/paper/{tid}", headers=HEADERS, timeout=10)
            return (tid, r.status_code == 200)
        except requests.RequestException:
            return (tid, False)

    # 分批掃描（每批 500 個 ID）
    BATCH = 500
    current = scanned_up_to

    while current > PAPER_ID_START:
        batch_end = current
        batch_start = max(current - BATCH, PAPER_ID_START)
        ids = list(range(batch_end - 1, batch_start - 1, -1))
        current = batch_start

        # 並行檢查
        valid_ids = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(check_id, tid): tid for tid in ids}
            for f in as_completed(futures):
                tid, ok = f.result()
                if ok:
                    valid_ids.append(tid)

        # 對有效 ID 逐篇解析
        for tid in sorted(valid_ids, reverse=True):
            url = f"{BASE}/article/paper/{tid}"
            if url in already_found:
                continue

            r = fetch(url, timeout=10)
            if r is None:
                continue

            # 日期
            m = re.search(r'article:published_time.*?content="([^"]+)"', r.text)
            if m:
                dt = parse_date(m.group(1))
                if dt and dt < START_DATE:
                    print(f"  到達 START_DATE (ID={tid}, {m.group(1)[:10]})，停止")
                    progress_file.write_text(json.dumps({
                        "scanned_up_to": batch_start,
                        "articles": articles,
                    }, ensure_ascii=False))
                    return articles

            # 標題
            soup = BeautifulSoup(r.text, "html.parser")
            h1 = soup.select_one("h1")
            title = h1.get_text(strip=True) if h1 else ""

            articles.append({
                "title": title,
                "date": m.group(1) if m else "",
                "url": url,
            })
            already_found.add(url)
            time.sleep(0.1)

        # 存進度
        progress_file.write_text(json.dumps({
            "scanned_up_to": batch_start,
            "articles": articles,
        }, ensure_ascii=False))

        if valid_ids:
            print(f"  ID {batch_start}~{batch_end}: +{len(valid_ids)} 篇 (累計 {len(articles)})")

    return articles


# === 第三階段：抓全文 ===

def fetch_article(url: str) -> dict | None:
    """抓取單篇文章全文。"""
    r = fetch(url)
    if r is None:
        return None
    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    # 標題
    title = ""
    h1 = soup.select_one("h1")
    if h1:
        title = h1.get_text(strip=True)

    # 日期
    pub_date = ""
    meta_date = soup.select_one("meta[property='article:published_time']")
    if meta_date:
        pub_date = meta_date.get("content", "")
    if not pub_date:
        m = re.search(r"(\d{4}/\d{2}/\d{2}\s*\d{2}:\d{2})", html[:5000])
        if m:
            pub_date = m.group(1)

    # 正文 — 有兩個 div.text，取有內容的那個
    body_el = None
    for el in soup.select("div.text"):
        if el.get_text(strip=True):
            body_el = el
            break
    if not body_el:
        return None

    # 移除廣告、相關新聞等雜訊
    for tag in body_el.select("script, style, .ad, .related, .photo_desc, .appE1121, .boxTitle, [id^='ad-']"):
        tag.decompose()

    paragraphs = []
    for p in body_el.find_all(["p", "div"], recursive=False):
        text = p.get_text(strip=True)
        if text and "不用抽" not in text and "點我下載APP" not in text and "按我看活動辦法" not in text and "請繼續往下閱讀" not in text:
            paragraphs.append(text)

    if not paragraphs:
        text = body_el.get_text("\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        paragraphs = [l for l in lines if "不用抽" not in l and "點我下載APP" not in l and "請繼續往下閱讀" not in l]

    body = "\n".join(paragraphs)
    if len(body) < 50:
        return None

    return {"title": title, "date": pub_date, "url": url, "body": body}


def scrape_channel(channel_name: str, channel_info: dict, phase: str = "all"):
    """爬取單一頻道。"""
    ch_dir = OUTPUT_DIR / channel_name
    ch_dir.mkdir(parents=True, exist_ok=True)

    # === 索引階段 ===
    index_file = ch_dir / "_index.json"
    if phase in ("all", "index"):
        if index_file.exists() and phase != "index":
            articles = json.loads(index_file.read_text())
            print(f"  [{channel_name}] 載入既有索引: {len(articles)} 篇")
        else:
            print(f"  [{channel_name}] 收集文章 URL (AJAX)...")
            articles = collect_channel_urls(channel_name, channel_info)
            index_file.write_text(json.dumps(articles, ensure_ascii=False, indent=2))
            print(f"  [{channel_name}] 索引完成: {len(articles)} 篇")
    else:
        if index_file.exists():
            articles = json.loads(index_file.read_text())
        else:
            articles = []

    # === 全文抓取階段 ===
    if phase in ("all", "fetch"):
        done_file = ch_dir / "_done.json"
        done_urls = set()
        if done_file.exists():
            done_urls = set(json.loads(done_file.read_text()))

        remaining = [a for a in articles if a["url"] not in done_urls]
        print(f"  [{channel_name}] 已完成 {len(done_urls)}，剩餘 {len(remaining)}")

        for i, art in enumerate(remaining):
            url = art["url"]
            data = fetch_article(url)
            if data:
                data["channel"] = channel_name
                m = re.search(r"/(paper|breakingnews)/(\d+)", url)
                art_id = m.group(2) if m else str(hash(url) & 0xFFFFFFFF)
                out_file = ch_dir / f"{art_id}.json"
                out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))

            done_urls.add(url)

            if (i + 1) % 20 == 0:
                done_file.write_text(json.dumps(list(done_urls), ensure_ascii=False))
                success = len(list(ch_dir.glob("[0-9]*.json")))
                print(f"  [{channel_name}] {i+1}/{len(remaining)} (成功 {success} 篇)")

            time.sleep(DELAY_ARTICLE)

        done_file.write_text(json.dumps(list(done_urls), ensure_ascii=False))
        total = len(list(ch_dir.glob("[0-9]*.json")))
        print(f"  [{channel_name}] ✅ 完成，共 {total} 篇")


def run_scan():
    """掃描 paper ID 補充歷史文章。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    progress_file = OUTPUT_DIR / "_scan_progress.json"

    print("=== Paper ID 掃描（補充歷史文章）===")
    print(f"  範圍: {PAPER_ID_START} ~ {PAPER_ID_END}")
    articles = scan_paper_ids(progress_file)
    print(f"  掃描完成，共找到 {len(articles)} 篇")

    # 將掃描到的文章分配到各頻道的索引中
    # 先抓全文時會自動判斷頻道
    scan_index = OUTPUT_DIR / "_scan_index.json"
    scan_index.write_text(json.dumps(articles, ensure_ascii=False, indent=2))
    print(f"  索引已存: {scan_index}")


def fetch_scanned_articles():
    """抓取掃描到的文章全文。"""
    scan_index = OUTPUT_DIR / "_scan_index.json"
    if not scan_index.exists():
        print("請先執行 --phase scan")
        return

    articles = json.loads(scan_index.read_text())
    done_file = OUTPUT_DIR / "_scan_done.json"
    done_urls = set()
    if done_file.exists():
        done_urls = set(json.loads(done_file.read_text()))

    remaining = [a for a in articles if a["url"] not in done_urls]
    print(f"掃描文章全文抓取: 共 {len(articles)} 篇，已完成 {len(done_urls)}，剩餘 {len(remaining)}")

    # 用 _unsorted 資料夾暫存
    unsorted_dir = OUTPUT_DIR / "_unsorted"
    unsorted_dir.mkdir(exist_ok=True)

    for i, art in enumerate(remaining):
        url = art["url"]
        data = fetch_article(url)
        if data:
            m = re.search(r"/(paper|breakingnews)/(\d+)", url)
            art_id = m.group(2) if m else str(hash(url) & 0xFFFFFFFF)
            out_file = unsorted_dir / f"{art_id}.json"
            out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))

        done_urls.add(url)

        if (i + 1) % 50 == 0:
            done_file.write_text(json.dumps(list(done_urls), ensure_ascii=False))
            success = len(list(unsorted_dir.glob("*.json")))
            print(f"  {i+1}/{len(remaining)} (成功 {success} 篇)")

        time.sleep(DELAY_ARTICLE)

    done_file.write_text(json.dumps(list(done_urls), ensure_ascii=False))
    total = len(list(unsorted_dir.glob("*.json")))
    print(f"✅ 掃描文章抓取完成，共 {total} 篇 → {unsorted_dir}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", help="只抓指定頻道名稱")
    parser.add_argument("--phase", choices=["all", "index", "fetch", "scan", "scan-fetch"],
                        default="all", help="執行階段")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.phase == "scan":
        run_scan()
        return

    if args.phase == "scan-fetch":
        fetch_scanned_articles()
        return

    print(f"輸出目錄: {OUTPUT_DIR}")
    print(f"目標: 2023-01-01 至今")
    print(f"頻道: {list(CHANNELS.keys())}")
    print()

    for name, info in CHANNELS.items():
        if args.channel and args.channel != name:
            continue
        scrape_channel(name, info, phase=args.phase)
        print()

    print("✅ 全部完成！")


if __name__ == "__main__":
    main()
