# -*- coding: utf-8 -*-
"""
鳄鱼派投资档案全量爬虫（可断点续爬）
数据源: https://gator.ronchy2000.top/  (robots.txt: Allow all)

产出:
  data/items/*.json      每篇内容一份元数据+清洗后的正文
  data/images/<slug>/*.  文章图片本地镜像
  data/crawl_log.txt     进度日志
"""
import json
import re
import sys
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

BASE = "https://gator.ronchy2000.top"
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ITEMS_DIR = DATA / "items"
IMAGES_DIR = DATA / "images"
LOG_PATH = DATA / "crawl_log.txt"

for p in (ITEMS_DIR, IMAGES_DIR):
    p.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GatorReaderCrawler/1.0; personal-archive)",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
SESSION_LOCAL = threading.local()
_lock = threading.Lock()
_done_count = {"items": 0, "images": 0, "fail": 0}


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    with _lock:
        print(line, flush=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def session() -> requests.Session:
    if not hasattr(SESSION_LOCAL, "s"):
        s = requests.Session()
        s.headers.update(HEADERS)
        retry = requests.adapters.Retry(
            total=3, backoff_factor=1.2, status_forcelist=[429, 500, 502, 503, 504]
        )
        s.mount("https://", requests.adapters.HTTPAdapter(max_retries=retry))
        SESSION_LOCAL.s = s
    return SESSION_LOCAL.s


def fetch(url: str, binary: bool = False, timeout: int = 25):
    """带限速的抓取：4-7 req/s 每线程抖动，整体温和。"""
    time.sleep(random.uniform(0.12, 0.25))
    r = session().get(url, timeout=timeout)
    r.raise_for_status()
    return r.content if binary else r.text


# ---------------------------------------------------------------- HTML 清洗
ALLOWED_TAGS = {
    "p", "section", "strong", "em", "b", "i", "u", "s", "br", "hr",
    "blockquote", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "tr", "td", "th", "a", "img", "figure",
    "figcaption", "sup", "sub", "code", "pre",
}
DROP_WITH_NOTE = {"iframe", "video", "embed", "object"}


def _media_only(node: Tag) -> bool:
    kids = [c for c in node.children if getattr(c, "name", None) or (isinstance(c, str) and c.strip())]
    return len(kids) == 1 and getattr(kids[0], "name", None) == "img"


def sanitize_body(container: Tag, slug_hint: str) -> str:
    """微信富文本 → 语义化干净 HTML：剥样式/脚本，section 归并为块级，图片居中。"""
    if container is None:
        return ""
    root = BeautifulSoup("<div></div>", "html.parser")
    out = root.find("div")

    def walk(node, dest):
        for child in list(node.children):
            if isinstance(child, str):
                dest.append(child.replace("\u00a0", " "))
                continue
            name = (child.name or "").lower()
            if name in ("script", "style", "noscript", "svg", "form", "input", "button", "link", "meta"):
                continue
            if name in DROP_WITH_NOTE:
                note = root.new_tag("p")
                note["class"] = "media-note"
                note.string = "［此处在原文中为视频/嵌入内容，请查看原文］"
                dest.append(note)
                continue
            if name == "span":
                # span 仅作文字包装：直接并入父级
                walk(child, dest)
                continue
            if name not in ALLOWED_TAGS:
                walk(child, dest)  # 未知标签：拆壳保内容
                continue
            new = root.new_tag(name)
            # 图片：改写为本地相对路径，保留宽高比提示
            if name == "img":
                src = child.get("src") or ""
                if not src:
                    continue
                m = re.search(r"/article-assets/([^/]+)/([^/?#]+)", src)
                if m:
                    new["src"] = f"images/{m.group(1)}/{m.group(2)}"
                elif src.startswith("http"):
                    new["src"] = src  # 极少数外链图
                else:
                    continue
                if child.get("data-ratio"):
                    new["data-ratio"] = child["data-ratio"]
                if child.get("alt"):
                    new["alt"] = child["alt"]
                new["loading"] = "lazy"
                dest.append(new)
                continue
            if name == "a":
                href = child.get("href") or ""
                if href.startswith("javascript"):
                    walk(child, dest)
                    continue
                new["href"] = urljoin(BASE, href)
                new["target"] = "_blank"
                new["rel"] = "noopener noreferrer"
            # section → 块级容器；只含一张图时升级为 figure
            if name == "section":
                new.name = "figure" if _media_only(child) else "p"
                if new.name == "figure":
                    walk(child, new)
                    dest.append(new)
                    continue
            walk(child, new)
            if new.name in ("p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "figcaption") and not new.get_text(strip=True) and not new.find("img"):
                continue
            dest.append(new)

    walk(container, out)
    html = str(out)[5:-6]  # 去掉外层 <div></div>
    html = re.sub(r"<p>(\s|　)*</p>", "", html)
    return html.strip()


def strip_tags(html: str, limit: int = 4000) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


# ---------------------------------------------------------------- 页面解析
def parse_meta_header(soup):
    """article-meta / report-meta 容器：日期 / 阅读时长 / 原文链接。"""
    meta = soup.find(class_=re.compile(r"(article-meta|report-meta)"))
    date_iso, minutes, origin = None, None, None
    if meta:
        t = meta.find("time")
        if t and t.get("datetime"):
            # 源站存 UTC，站内展示为东八区日期
            try:
                dt = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00"))
                date_iso = dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
            except Exception:
                date_iso = t["datetime"][:10]
        m = re.search(r"约?\s*(\d+)\s*分钟", meta.get_text(" ", strip=True))
        if m:
            minutes = int(m.group(1))
        a = meta.find("a", href=re.compile(r"mp\.weixin\.qq\.com|h5\.2025eyp\.com"))
        if a:
            origin = a["href"]
    return date_iso, minutes, origin


CAT_BY_HASH = {}  # 已弃用：分类以 article_category_map() 的源站分类页为准


def crawl_article(url: str, category: str = "") -> dict:
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    title_el = soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else slug
    date_iso, minutes, origin = parse_meta_header(soup)
    if not date_iso:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", slug)
        date_iso = m.group(1) if m else None
    body = soup.find(class_="article-body")
    content = sanitize_body(body, slug)
    images = []
    if body:
        for img in body.find_all("img"):
            src = img.get("src") or ""
            m = re.search(r"/article-assets/([^/]+)/([^/?#]+)", src)
            if m:
                images.append(f"/article-assets/{m.group(1)}/{m.group(2)}")
    return {
        "id": slug,
        "type": "article",
        "category": category or "daily-review",
        "title": title,
        "date": date_iso,
        "minutes": minutes,
        "origin_url": origin,
        "source_url": url,
        "content": content,
        "images": images,
        "text": strip_tags(content),
    }


def crawl_report(url: str, cat_fallback: str = "") -> dict:
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    num = int(re.search(r"/reports/(\d+)", url).group(1))
    title_el = soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else f"研报 #{num}"
    # kicker: <span>LEGACY REPORT / #N</span><span>行业分析</span>
    category = cat_fallback
    kicker = soup.find(class_="report-kicker")
    if kicker:
        spans = [s.get_text(strip=True) for s in kicker.find_all("span")]
        cat_map = {"宏观分析": "macro", "行业分析": "industry", "其他": "other"}
        for s in spans:
            if s in cat_map:
                category = cat_map[s]
                break
    date_iso, minutes, origin = parse_meta_header(soup)
    if not origin:
        a = soup.find("a", href=re.compile(r"h5\.2025eyp\.com"))
        if a:
            origin = a["href"]
    summary_html = ""
    summary = soup.find(class_="report-summary")
    if summary:
        ol = summary.find("ol") or summary.find("ul")
        if ol:
            items = "".join(f"<li>{li.get_text(' ', strip=True)}</li>" for li in ol.find_all("li"))
            summary_html = f"<ol>{items}</ol>"
    body = soup.find(class_="report-body")
    content = sanitize_body(body, f"report-{num}")
    return {
        "id": f"report-{num}",
        "num": num,
        "type": "report",
        "category": category or "other",
        "title": title,
        "date": date_iso,
        "minutes": minutes,
        "origin_url": origin,
        "source_url": url,
        "summary": summary_html,
        "content": content,
        "images": [],
        "text": strip_tags(summary_html + content),
    }


def crawl_note(url: str) -> dict:
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    title_el = soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else slug
    date_iso, minutes, origin = parse_meta_header(soup)
    if not date_iso:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", slug)
        date_iso = m.group(1) if m else None
    art = soup.find("article") or soup.find("main")
    body = art.find(class_=re.compile(r"(article-body|report-body|note-body)")) if art else None
    if body is None and art:
        body = art
    content = sanitize_body(body, slug)
    return {
        "id": slug,
        "type": "note",
        "category": "notes",
        "title": title,
        "date": date_iso,
        "minutes": minutes,
        "origin_url": origin,
        "source_url": url,
        "content": content,
        "images": [],
        "text": strip_tags(content),
    }


# ---------------------------------------------------------------- 图片下载
def download_images(item: dict) -> int:
    n = 0
    for rel in item.get("images", []):
        m = re.match(r"/article-assets/([^/]+)/([^/?#]+)", rel)
        if not m:
            continue
        slug, fname = m.group(1), m.group(2)
        dest_dir = IMAGES_DIR / slug
        dest = dest_dir / fname
        if dest.exists() and dest.stat().st_size > 0:
            n += 1
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            blob = fetch(BASE + rel, binary=True)
            dest.write_bytes(blob)
            n += 1
        except Exception as e:
            log(f"  IMG FAIL {rel}: {e}")
    return n


# ---------------------------------------------------------------- 枚举
def enumerate_urls() -> list:
    x = fetch(BASE + "/sitemap-0.xml")
    urls = re.findall(r"<loc>([^<]+)</loc>", x)
    items, reports, notes = [], [], []
    for u in urls:
        if "/articles/" in u:
            items.append(u)
        elif re.search(r"/reports/\d+", u):
            reports.append(u)
        elif "/notes/" in u:
            notes.append(u)
    log(f"sitemap: articles={len(items)} reports={len(reports)} notes={len(notes)}")
    return items, reports, notes


def article_category_map() -> dict:
    """以源站两个分类页为权威：slug → daily-info / daily-review。"""
    mapping = {}
    for cat, path in (("daily-info", "/archive/huode-xinxicha/"),
                      ("daily-review", "/archive/like-a-gator/")):
        html = fetch(BASE + path)
        for link in re.findall(r'href="(/articles/[^"]+/)"', html):
            mapping[link.rstrip("/").rsplit("/", 1)[-1]] = cat
    return mapping


def report_category_map() -> dict:
    """研报索引页单页含全部 913 行，data-category 直接给分类。"""
    html = fetch(BASE + "/reports/")
    soup = BeautifulSoup(html, "html.parser")
    mapping = {}
    for row in soup.find_all(attrs={"data-report-row": True}):
        a = row.find("a", href=re.compile(r"/reports/(\d+)"))
        if not a:
            continue
        num = int(re.search(r"/reports/(\d+)", a["href"]).group(1))
        mapping[num] = row.get("data-category", "")
    log(f"report category map: {len(mapping)} entries")
    return mapping


# ---------------------------------------------------------------- 主流程
def process_url(url: str, kind: str, cat: str = "") -> int:
    """返回下载图片数；item 落盘 data/items/<id>.json"""
    if kind == "article":
        item = crawl_article(url, cat)
    elif kind == "report":
        item = crawl_report(url, cat)
    else:
        item = crawl_note(url)
    out = ITEMS_DIR / f"{item['id']}.json"
    n_img = download_images(item)
    item["images_done"] = n_img
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out)
    return n_img


def main():
    t0 = time.time()
    items, reports, notes = enumerate_urls()
    cat_map = report_category_map()
    art_map = article_category_map()
    log(f"article category map: {len(art_map)} entries")

    tasks = [(u, "article", art_map.get(u.rstrip("/").rsplit("/", 1)[-1], "")) for u in items]
    tasks += [(u, "report", cat_map.get(int(re.search(r"/reports/(\d+)", u).group(1)), "")) for u in reports]
    tasks += [(u, "note", "") for u in notes]
    total = len(tasks)

    # 断点续爬：已完成 item 的直接跳过
    todo = []
    for url, kind, cat in tasks:
        if kind == "report":
            num = int(re.search(r"/reports/(\d+)", url).group(1))
            done = (ITEMS_DIR / f"report-{num}.json").exists()
        else:
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            done = (ITEMS_DIR / f"{slug}.json").exists()
        if not done:
            todo.append((url, kind, cat))
    log(f"total={total} todo={len(todo)} (resumed, skipped {total - len(todo)})")

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(process_url, u, k, c): (u, k) for u, k, c in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            url, kind = futs[fut]
            try:
                n = fut.result()
                with _lock:
                    _done_count["items"] += 1
                    _done_count["images"] += n
            except Exception as e:
                with _lock:
                    _done_count["fail"] += 1
                log(f"FAIL [{kind}] {url}: {type(e).__name__} {e}")
            if i % 50 == 0:
                log(f"progress {i}/{len(todo)} | ok={_done_count['items']} imgs={_done_count['images']} fail={_done_count['fail']} | {time.time()-t0:.0f}s")

    log(f"DONE items={_done_count['items']} images={_done_count['images']} fail={_done_count['fail']} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
