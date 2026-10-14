# -*- coding: utf-8 -*-
"""
静态站生成器：data/items/*.json → site/
纯 Python 标准库，无模板引擎依赖。

用法:
  python generator/build.py            # 按 site.config.json 构建
  python generator/build.py --images   # 仅同步图片目录
"""
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ITEMS_DIR = DATA / "items"
SITE = ROOT / "site"
ASSETS_SRC = Path(__file__).resolve().parent / "assets"

CONFIG_PATH = ROOT / "site.config.json"
DEFAULT_CONFIG = {
    "site_name": "鳄鱼文库",
    "site_en": "GATOR LIBRARY",
    "image_base_url": "images",
    "source_site": "https://gator.ronchy2000.top/",
    "disclaimer": "内容仅供信息交流，不构成任何投资建议；原文版权归原作者所有。",
}

# ------------------------------------------------------------------ 分类
CATS = {
    "daily-info": {"name": "每日信息", "sub": "获得信息差", "en": "DAILY BRIEF",
                   "desc": "隔夜美股、国内外消息、产业链与大宗快讯的每日汇编。"},
    "daily-review": {"name": "每日复盘", "sub": "像鳄鱼一样思考", "en": "DAILY REVIEW",
                     "desc": "市场评分、资金流向与仓位节奏的每日收盘复盘。"},
    "macro": {"name": "宏观分析", "sub": "历史研报", "en": "MACRO",
              "desc": "宏观与大类资产方向的历史研报蒸馏。"},
    "industry": {"name": "行业分析", "sub": "历史研报", "en": "INDUSTRY",
                 "desc": "细分行业景气跟踪与产业链观察的历史研报蒸馏。"},
    "other": {"name": "其他研报", "sub": "历史研报", "en": "REPORTS",
              "desc": "不便归入宏观与行业的历史研报存档。"},
    "notes": {"name": "投资随笔", "sub": "长文思考", "en": "ESSAYS",
              "desc": "不定期长文：指数计划、周期思考与配置框架。"},
}
NAV_ITEMS = [
    ("index.html", "首页"),
    ("category/daily-info.html", "每日信息"),
    ("category/daily-review.html", "每日复盘"),
    ("category/reports.html", "历史研报"),
    ("category/notes.html", "随笔"),
    ("archive.html", "归档"),
]

MINUTES_DEFAULT_CPS = 420  # 无时长数据时按字数估算


def esc(s) -> str:
    from html import escape
    return escape(str(s if s is not None else ""), quote=True)


def load_items() -> list:
    items = []
    for f in ITEMS_DIR.glob("*.json"):
        try:
            items.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"skip bad item {f.name}: {e}")
    for it in items:
        if not it.get("minutes"):
            it["minutes"] = max(1, round(len(it.get("text", "")) / MINUTES_DEFAULT_CPS))
        it.setdefault("summary", "")
    items.sort(key=lambda x: (x.get("date") or "0000", x.get("id")), reverse=True)
    return items


def item_path(it: dict) -> str:
    if it["type"] == "report":
        return f"reports/{it['num']}.html"
    return f"{it['type']}s/{it['id']}.html"


def fmt_date(d: str) -> str:
    if not d or len(d) < 10:
        return "—"
    y, m, day = d.split("-")
    return f"{y}.{m}.{day}"


def rewrite_images(content: str, root: str, image_base: str) -> str:
    base = image_base.rstrip("/")
    if base == "images":
        return content.replace('src="images/', f'src="{root}images/')
    return re.sub(r'src="images/([^"]+)"', lambda m: f'src="{base}/{m.group(1)}"', content)


# ------------------------------------------------------------------ 页面骨架
def page_shell(*, root: str, cfg: dict, title: str, desc: str, active: str,
               body_class: str, content: str, item_count: int) -> str:
    nav = "".join(
        f'<a class="nav-link{" is-active" if href.strip("/").replace(".html", "") == active or (active == "index" and href == "index.html") else ""}" '
        f'href="{root}{href}">{esc(name)}</a>'
        for href, name in NAV_ITEMS
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN" data-root="{root}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} | {esc(cfg['site_name'])}</title>
<meta name="description" content="{esc(desc)}">
<link rel="icon" type="image/svg+xml" href="{root}assets/favicon.svg">
<link rel="stylesheet" href="{root}assets/style.css">
<script>(function(){{var t=null;try{{t=localStorage.getItem('gr-theme')}}catch(e){{}}
if(!t)t=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
document.documentElement.setAttribute('data-theme',t);}})();</script>
</head>
<body class="{body_class}">
<div class="progress" id="progress" hidden></div>
<header class="topbar">
  <div class="topbar-inner">
    <a class="brand" href="{root}index.html">
      <span class="seal" aria-hidden="true">鳄</span>
      <span class="brand-text">{esc(cfg['site_name'])}<small>{esc(cfg['site_en'])}</small></span>
    </a>
    <nav class="nav">{nav}</nav>
    <div class="topbar-actions">
      <button class="icon-btn" id="search-open" aria-label="搜索" title="搜索 Ctrl+K">
        <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/></svg>
        <span class="kbd-hint">Ctrl K</span>
      </button>
      <button class="icon-btn" id="theme-toggle" aria-label="切换主题" title="切换主题">
        <svg class="i-sun" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M19.1 4.9l-1.6 1.6M6.5 17.5l-1.6 1.6"/></svg>
        <svg class="i-moon" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.4 14.2A8.3 8.3 0 0 1 9.8 3.6a8.3 8.3 0 1 0 10.6 10.6Z"/></svg>
      </button>
    </div>
  </div>
</header>
<main>
{content}
</main>
<footer class="footer">
  <div class="footer-inner">
    <p>归档自 <a href="{esc(cfg['source_site'])}" target="_blank" rel="noopener noreferrer">鳄鱼派投资档案</a>
       · 收录 {item_count} 篇 · 内容版权归原作者所有</p>
    <p>{esc(cfg['disclaimer'])}</p>
  </div>
</footer>
<div class="search-mask" id="search-mask" hidden>
  <div class="search-panel" role="dialog" aria-label="站内搜索">
    <div class="search-input-row">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/></svg>
      <input id="search-input" type="text" placeholder="搜索标题与正文…" autocomplete="off" spellcheck="false">
      <span class="kbd-hint">Esc</span>
    </div>
    <div class="search-results" id="search-results"></div>
  </div>
</div>
<script src="{root}assets/app.js" defer></script>
</body>
</html>"""


def chip(cat: str) -> str:
    c = CATS[cat]
    return f'<a class="chip chip-{cat}" href="category/{cat}.html">{esc(c["name"])}</a>'


def item_row(it: dict, root: str, with_chip: bool = True) -> str:
    c = CATS[it["category"]]
    chip_html = f'<span class="row-chip">{esc(c["name"])}</span>' if with_chip else ""
    return f"""<a class="row" href="{root}{item_path(it)}">
  <time class="row-date">{fmt_date(it.get('date'))}</time>
  {chip_html}
  <span class="row-title">{esc(it['title'])}</span>
  <span class="row-min">{it['minutes']} 分钟</span>
</a>"""


def month_block(rows: str, ym: str) -> str:
    return f'<section class="month"><h2 class="month-h">{esc(ym)}</h2><div class="rows">{rows}</div></section>'


# ------------------------------------------------------------------ 各页面
def build_home(items, cfg, root=""):
    counts = Counter(it["category"] for it in items)
    latest_date = max((it.get("date") or "") for it in items)
    cards = ""
    for key in ("daily-info", "daily-review", "notes"):
        c = CATS[key]
        cards += f"""<a class="cat-card" href="{root}category/{key}.html">
  <span class="cat-en">{esc(c['en'])}</span>
  <span class="cat-name">{esc(c['name'])}<small>{esc(c['sub'])}</small></span>
  <span class="cat-desc">{esc(c['desc'])}</span>
  <span class="cat-count">{counts[key]} 篇</span>
</a>"""
    cards += f"""<a class="cat-card" href="{root}category/reports.html">
  <span class="cat-en">LEGACY REPORTS</span>
  <span class="cat-name">历史研报<small>宏观 · 行业 · 其他</small></span>
  <span class="cat-desc">宏观分析 {counts['macro']} 篇 / 行业分析 {counts['industry']} 篇 / 其他 {counts['other']} 篇。</span>
  <span class="cat-count">{counts['macro'] + counts['industry'] + counts['other']} 篇</span>
</a>"""

    rows = "".join(item_row(it, root) for it in items[:30])
    content = f"""
<section class="hero">
  <p class="hero-kicker">READ · SEARCH · ARCHIVE</p>
  <h1 class="hero-title">把每日信息、复盘与研报<br>放回一条<em>可检索</em>的时间线</h1>
  <p class="hero-sub">收录「获得信息差」与「像鳄鱼一样思考」全部日更，及 913 篇历史研报。数据更新至 {fmt_date(latest_date)}。</p>
  <button class="hero-search" id="hero-search" type="button">
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/></svg>
    搜索标题或正文关键词<span class="kbd-hint">Ctrl K</span>
  </button>
</section>
<section class="cat-grid">{cards}</section>
<section class="home-list">
  <div class="sec-head"><h2>最新更新</h2><a class="sec-more" href="{root}archive.html">全部归档 →</a></div>
  <div class="rows">{rows}</div>
</section>"""
    return page_shell(root=root, cfg=cfg, title="首页", desc="每日信息、每日复盘与历史研报的全文检索归档",
                      active="index", body_class="page-home", content=content, item_count=len(items))


def build_category(items, cfg, cat_key: str, root="../"):
    if cat_key == "reports":
        sub = [it for it in items if it["category"] in ("macro", "industry", "other")]
        title, desc, en = "历史研报", "宏观分析、行业分析与其他历史研报的蒸馏存档。", "LEGACY REPORTS"
        tabs = f"""<div class="tabs" id="report-tabs">
  <button class="tab is-active" data-cat="all">全部</button>
  <button class="tab" data-cat="macro">宏观分析</button>
  <button class="tab" data-cat="industry">行业分析</button>
  <button class="tab" data-cat="other">其他</button>
</div>"""
        # 按月分组
        groups = defaultdict(list)
        for it in sub:
            groups[(it.get("date") or "0000-00")[:7]].append(it)
        blocks = ""
        for ym in sorted(groups, reverse=True):
            rows = "".join(f'<a class="row" href="{root}{item_path(it)}" data-rcat="{it["category"]}">'
                           f'<time class="row-date">{fmt_date(it.get("date"))}</time>'
                           f'<span class="row-chip">{esc(CATS[it["category"]]["name"])}</span>'
                           f'<span class="row-title">{esc(it["title"])}</span>'
                           f'<span class="row-min">{it["minutes"]} 分钟</span></a>'
                           for it in groups[ym])
            blocks += month_block(rows, ym)
        content = f"""
<section class="page-head">
  <p class="hero-kicker">{en}</p>
  <h1 class="page-title">{title}</h1>
  <p class="page-sub">{desc} 共 {len(sub)} 篇。</p>
  {tabs}
</section>
<div class="report-wrap">{blocks}</div>"""
        return page_shell(root=root, cfg=cfg, title=title, desc=desc, active="category/reports",
                          body_class="page-cat", content=content, item_count=len(items))

    c = CATS[cat_key]
    sub = [it for it in items if it["category"] == cat_key]
    groups = defaultdict(list)
    for it in sub:
        groups[(it.get("date") or "0000-00")[:7]].append(it)
    blocks = ""
    for ym in sorted(groups, reverse=True):
        rows = "".join(item_row(it, root, with_chip=False) for it in groups[ym])
        blocks += month_block(rows, ym)
    content = f"""
<section class="page-head">
  <p class="hero-kicker">{esc(c['en'])} · {esc(c['sub'])}</p>
  <h1 class="page-title">{esc(c['name'])}</h1>
  <p class="page-sub">{esc(c['desc'])} 共 {len(sub)} 篇。</p>
</section>
{blocks}"""
    return page_shell(root=root, cfg=cfg, title=c["name"], desc=c["desc"],
                      active=f"category/{cat_key}", body_class="page-cat",
                      content=content, item_count=len(items))


def build_archive(items, cfg, root=""):
    years = defaultdict(lambda: defaultdict(list))
    for it in items:
        y = (it.get("date") or "0000")[:4]
        m = (it.get("date") or "0000-00")[5:7]
        years[y][m].append(it)
    sections = ""
    for y in sorted(years, reverse=True):
        if not y.isdigit():
            continue
        months = ""
        for m in sorted(years[y], reverse=True):
            rows = "".join(item_row(it, root) for it in years[y][m])
            months += f'<div class="arc-month"><h3>{y}.{m}<span>{len(years[y][m])} 篇</span></h3><div class="rows">{rows}</div></div>'
        total = sum(len(v) for v in years[y].values())
        open_attr = " open" if y == max(years) else ""
        sections += f'<details class="arc-year"{open_attr}><summary>{y}<span>{total} 篇</span></summary>{months}</details>'
    content = f"""
<section class="page-head">
  <p class="hero-kicker">TIMELINE</p>
  <h1 class="page-title">全部归档</h1>
  <p class="page-sub">按年份与月份浏览全部 {len(items)} 篇内容。</p>
</section>
<div class="archive">{sections}</div>"""
    return page_shell(root=root, cfg=cfg, title="归档", desc="按时间线浏览全部归档内容",
                      active="archive", body_class="page-archive", content=content, item_count=len(items))


def build_item(it, cfg, all_items, root="../../"):
    c = CATS[it["category"]]
    # 同分类内前后篇
    sibs = [x for x in all_items if x["category"] == it["category"]]
    idx = next(i for i, x in enumerate(sibs) if x["id"] == it["id"])
    prev_it = sibs[idx + 1] if idx + 1 < len(sibs) else None
    next_it = sibs[idx - 1] if idx > 0 else None

    origin = ""
    if it.get("origin_url"):
        origin = f'<a class="meta-link" href="{esc(it["origin_url"])}" target="_blank" rel="noopener noreferrer">原文链接 ↗</a>'
    summary = ""
    if it.get("summary"):
        summary = f"""<aside class="report-summary"><div class="rs-label">报告摘要<small>SUMMARY</small></div>{it['summary']}</aside>"""
    nav_cards = ""
    if prev_it or next_it:
        pl = f'<a class="pn-card" href="{root}{item_path(prev_it)}"><small>← 上一篇</small><span>{esc(prev_it["title"])}</span></a>' if prev_it else '<span class="pn-card is-empty"></span>'
        nx = f'<a class="pn-card is-next" href="{root}{item_path(next_it)}"><small>下一篇 →</small><span>{esc(next_it["title"])}</span></a>' if next_it else '<span class="pn-card is-empty"></span>'
        nav_cards = f'<nav class="pn">{pl}{nx}</nav>'

    back_name = c["name"] if it["type"] != "report" else "历史研报"
    back_href = f"{root}category/{it['category']}.html" if it["type"] != "report" else f"{root}category/reports.html"
    content_html = rewrite_images(it["content"], root, cfg["image_base_url"])

    content = f"""
<article class="reader">
  <header class="reader-head">
    <a class="back" href="{back_href}">← {esc(back_name)}</a>
    <div class="reader-meta">
      <span class="chip chip-{it['category']}">{esc(c['name'])}</span>
      <time>{fmt_date(it.get('date'))}</time>
      <span>约 {it['minutes']} 分钟</span>
      {origin}
    </div>
    <h1 class="reader-title">{esc(it['title'])}</h1>
  </header>
  <div class="reader-rule"><span></span><span></span></div>
  <div class="prose">
    {summary}
    {content_html}
  </div>
  <footer class="reader-foot">
    <p class="end-mark">END OF ARTICLE · 内容仅供信息交流，不构成任何投资建议</p>
    {nav_cards}
  </footer>
</article>"""
    return page_shell(root=root, cfg=cfg, title=it["title"], desc=it.get("text", "")[:120],
                      active=f"category/{it['category']}", body_class="page-item",
                      content=content, item_count=len(all_items))


def build_404(cfg, items, root="../"):
    content = f"""
<section class="page-head" style="text-align:center">
  <p class="hero-kicker">404</p>
  <h1 class="page-title">页面不存在</h1>
  <p class="page-sub">内容可能已被移动，回<a href="{root}index.html">首页</a>看看。</p>
</section>"""
    return page_shell(root=root, cfg=cfg, title="页面不存在", desc="404",
                      active="none", body_class="page-404", content=content, item_count=len(items))


def build_search_index(items, cfg) -> str:
    entries = []
    for it in items:
        entries.append({
            "u": item_path(it),
            "t": it["title"],
            "c": it["category"],
            "d": it.get("date") or "",
            "x": it.get("text", "")[:3500],
        })
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":"))


def copy_images():
    src, dst = DATA / "images", SITE / "images"
    if not src.exists():
        return 0
    n = 0
    for slug_dir in src.iterdir():
        if not slug_dir.is_dir():
            continue
        out = dst / slug_dir.name
        out.mkdir(parents=True, exist_ok=True)
        for f in slug_dir.iterdir():
            target = out / f.name
            if not target.exists() or target.stat().st_size != f.stat().st_size:
                shutil.copy2(f, target)
                n += 1
    return n


def main():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))

    if "--images" in sys.argv:
        print("images copied:", copy_images())
        return

    items = load_items()
    print(f"loaded {len(items)} items")
    t0 = datetime.now()

    # 静态资源
    (SITE / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ASSETS_SRC / "style.css", SITE / "assets" / "style.css")
    shutil.copy2(ASSETS_SRC / "app.js", SITE / "assets" / "app.js")
    shutil.copy2(ASSETS_SRC / "favicon.svg", SITE / "assets" / "favicon.svg")

    # 首页 / 分类 / 归档 / 404
    (SITE / "index.html").write_text(build_home(items, cfg), encoding="utf-8")
    (SITE / "archive.html").write_text(build_archive(items, cfg), encoding="utf-8")
    (SITE / "404.html").write_text(build_404(cfg, items), encoding="utf-8")
    for key in ("daily-info", "daily-review", "macro", "industry", "other", "notes"):
        (SITE / "category").mkdir(exist_ok=True)
        (SITE / "category" / f"{key}.html").write_text(
            build_category(items, cfg, key), encoding="utf-8")
    # 历史研报聚合页
    (SITE / "category" / "reports.html").write_text(
        build_category(items, cfg, "reports"), encoding="utf-8")

    # 内容页
    n_art = n_rep = n_note = 0
    for it in items:
        path = SITE / item_path(it)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_item(it, cfg, items), encoding="utf-8")
        if it["type"] == "article":
            n_art += 1
        elif it["type"] == "report":
            n_rep += 1
        else:
            n_note += 1

    # 搜索索引（懒加载）
    idx = build_search_index(items, cfg)
    (SITE / "assets" / "search-index.json").write_text(idx, encoding="utf-8")

    n_img = copy_images()
    print(f"built: articles={n_art} reports={n_rep} notes={n_note} "
          f"index={len(idx)//1024}KB images_new={n_img} in {(datetime.now()-t0).total_seconds():.1f}s")


if __name__ == "__main__":
    main()
