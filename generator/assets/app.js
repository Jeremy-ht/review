/* 鳄鱼文库 · 交互：主题 / 搜索 / 阅读进度 */
(function () {
  "use strict";
  var doc = document.documentElement;
  var root = doc.getAttribute("data-root") || "";

  /* ---------------- theme ---------------- */
  var toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = doc.getAttribute("data-theme") === "dark" ? "light" : "dark";
      doc.setAttribute("data-theme", next);
      try { localStorage.setItem("gr-theme", next); } catch (e) {}
    });
  }

  /* ---------------- reading progress ---------------- */
  var bar = document.getElementById("progress");
  if (bar && document.body.classList.contains("page-item")) {
    bar.hidden = false;
    var ticking = false;
    var update = function () {
      ticking = false;
      var h = doc.scrollHeight - window.innerHeight;
      bar.style.width = (h > 0 ? Math.min(100, (window.scrollY / h) * 100) : 0) + "%";
    };
    window.addEventListener("scroll", function () {
      if (!ticking) { ticking = true; requestAnimationFrame(update); }
    }, { passive: true });
    update();
  }

  /* ---------------- search ---------------- */
  var mask = document.getElementById("search-mask");
  var input = document.getElementById("search-input");
  var results = document.getElementById("search-results");
  var INDEX = null;        // [{u,t,c,d,x}]
  var flat = [];           // 预处理
  var active = -1;
  var current = [];

  var CAT_NAME = {
    "daily-info": "每日信息", "daily-review": "每日复盘",
    "macro": "宏观分析", "industry": "行业分析", "other": "其他研报", "notes": "随笔"
  };

  function openSearch() {
    mask.hidden = false;
    document.body.style.overflow = "hidden";
    input.value = "";
    render([]);
    input.focus();
    loadIndex();
  }
  function closeSearch() {
    mask.hidden = true;
    document.body.style.overflow = "";
  }

  function loadIndex() {
    if (INDEX) return;
    fetch(root + "assets/search-index.json")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        INDEX = data;
        flat = data.map(function (e) {
          return { e: e, t: e.t.toLowerCase(), x: e.x.toLowerCase() };
        });
        if (input.value.trim()) doSearch(input.value);
      })
      .catch(function () { results.innerHTML = '<div class="search-empty">索引加载失败，请刷新重试</div>'; });
  }

  function esc(s) {
    return s.replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

  function snippet(text, q) {
    var i = text.toLowerCase().indexOf(q);
    if (i < 0) return esc(text.slice(0, 90));
    var s = Math.max(0, i - 34);
    var frag = text.slice(s, s + 96);
    return esc(frag).replace(new RegExp(escRe(esc(q)), "gi"), function (m) { return "<mark>" + m + "</mark>"; });
  }

  function doSearch(q) {
    q = q.trim();
    if (!q) { render([]); return; }
    var lq = q.toLowerCase();
    var scored = [];
    for (var i = 0; i < flat.length; i++) {
      var f = flat[i], score = 0;
      var ti = f.t.indexOf(lq);
      if (ti >= 0) score += 120 - Math.min(ti, 60);
      if (f.t === lq) score += 80;
      var xi = f.x.indexOf(lq);
      if (xi >= 0) score += 30;
      if (!score) continue;
      // 多词查询：全部命中加分
      var words = lq.split(/\s+/);
      if (words.length > 1) {
        var all = words.every(function (w) { return f.t.indexOf(w) >= 0 || f.x.indexOf(w) >= 0; });
        if (all) score += 40; else continue;
      }
      scored.push([score, f.e]);
    }
    scored.sort(function (a, b) { return b[0] - a[0]; });
    render(scored.slice(0, 40).map(function (s) { return s[1]; }), lq, scored.length);
  }

  function render(list, lq, total) {
    current = list; active = -1;
    if (!list.length) {
      results.innerHTML = '<div class="search-empty">' +
        (INDEX ? "没有找到相关内容" : "正在加载索引…") + "</div>";
      return;
    }
    var html = "";
    for (var i = 0; i < list.length; i++) {
      var e = list[i];
      html += '<a class="sr-item" href="' + root + e.u + '">' +
        '<div class="sr-top"><span class="sr-title">' +
        (lq ? esc(e.t).replace(new RegExp(escRe(esc(lq)), "gi"), function (m) { return "<mark>" + m + "</mark>"; }) : esc(e.t)) +
        '</span><span class="sr-meta">' + (e.d || "").replace(/-/g, ".") + "</span></div>" +
        (lq && e.x ? '<div class="sr-snip">' + snippet(e.x, lq) + "</div>" : "") +
        '<div class="sr-meta" style="margin-top:4px">' + (CAT_NAME[e.c] || e.c) + "</div></a>";
    }
    html += '<div class="sr-foot"><span>' + (total || list.length) + " 条结果</span><span>↑↓ 选择 · Enter 打开</span></div>";
    results.innerHTML = html;
    var items = results.querySelectorAll(".sr-item");
    for (var j = 0; j < items.length; j++) {
      items[j].addEventListener("click", closeSearch);
    }
  }

  function setActive(n) {
    var items = results.querySelectorAll(".sr-item");
    if (!items.length) return;
    if (active >= 0 && items[active]) items[active].classList.remove("is-active");
    active = Math.max(0, Math.min(items.length - 1, active + n));
    items[active].classList.add("is-active");
    items[active].scrollIntoView({ block: "nearest" });
  }

  var openBtns = [];
  ["search-open", "hero-search"].forEach(function (id) {
    var b = document.getElementById(id);
    if (b) openBtns.push(b);
  });
  openBtns.forEach(function (b) {
    b.addEventListener("click", openSearch);
    b.addEventListener("focus", function () { b.blur(); }, { once: true });
  });

  mask.addEventListener("mousedown", function (e) { if (e.target === mask) closeSearch(); });
  input.addEventListener("input", function () { doSearch(input.value); });

  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      mask.hidden ? openSearch() : closeSearch();
      return;
    }
    if (mask.hidden) return;
    if (e.key === "Escape") { closeSearch(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(-1); }
    else if (e.key === "Enter") {
      if (active >= 0 && current[active]) location.href = root + current[active].u;
      else if (current.length) location.href = root + current[0].u;
    }
  });

  /* ---------------- 研报分类筛选 ---------------- */
  var tabs = document.getElementById("report-tabs");
  if (tabs) {
    tabs.addEventListener("click", function (e) {
      var btn = e.target.closest(".tab");
      if (!btn) return;
      tabs.querySelectorAll(".tab").forEach(function (t) { t.classList.toggle("is-active", t === btn); });
      var cat = btn.getAttribute("data-cat");
      document.querySelectorAll(".report-wrap .row").forEach(function (r) {
        var show = cat === "all" || r.getAttribute("data-rcat") === cat;
        r.classList.toggle("is-hidden", !show);
      });
      document.querySelectorAll(".report-wrap .month").forEach(function (m) {
        var any = m.querySelectorAll(".row:not(.is-hidden)").length > 0;
        m.classList.toggle("is-shown", any);
      });
      // 初始态：全部显示
      if (cat === "all") {
        document.querySelectorAll(".report-wrap .month").forEach(function (m) { m.classList.add("is-shown"); });
      }
    });
    document.querySelectorAll(".report-wrap .month").forEach(function (m) { m.classList.add("is-shown"); });
  }
})();
