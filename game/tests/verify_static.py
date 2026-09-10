#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
game/index.html 静态契约检查（只用标准库，不需要 Node）
=====================================================================
自动验收（verify_game.mjs）靠一个假 DOM 把脚本跑起来，能测行为；
但“文件本身是不是符合作品要求”这件事，用静态检查更直接：

  1) 只有一个内联 <script>，没有 src 外链
  2) 没有外链样式表、没有 http(s) 网络资源（注释里出现的链接不算）
  3) 脚本里不出现 import / require / process 等 Node API
  4) JS 里引用的每个元素 id，HTML 里都真的存在（防止改 id 改漏）
  5) 阶段一要求的三项新增功能、阶段二要求的关键函数都在

用法：
    python game/tests/verify_static.py
    退出码 0 = 通过，1 = 有问题
=====================================================================
"""
import os
import re
import sys

# ⚠️ Windows 上这是必须的，否则脚本会直接崩：
#   中文版 Windows 的控制台默认是 GBK 编码，而下面要打印 ✓ / ✗ 和中文说明。
#   GBK 里没有 ✓(U+2713)，Python 会抛 UnicodeEncodeError 而不是降级 —— 实测
#   `python game/tests/verify_static.py` 在 GBK 控制台里直接 traceback。
#   reconfigure 成 UTF-8 并允许替换字符，保证「打印」这个动作本身永远不会让检查脚本失败。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # Python < 3.7 或流被重定向到不支持 reconfigure 的对象时忽略

HERE = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.normpath(os.path.join(HERE, "..", "index.html"))

results = {"pass": 0, "fail": 0}
failures = []


def check(name, ok, detail=""):
    if ok:
        results["pass"] += 1
        print(f"  OK   {name}" + (f"  ({detail})" if detail else ""))
    else:
        results["fail"] += 1
        failures.append(f"{name} → {detail}")
        print(f"  FAIL {name}  {detail}")


def strip_html_comments(html):
    return re.sub(r"<!--.*?-->", "", html, flags=re.S)


def strip_js_comments(js):
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)      # 块注释
    js = re.sub(r"(?m)//.*$", "", js)                   # 行注释
    return js


def main():
    if not os.path.exists(HTML_PATH):
        print(f"找不到 {HTML_PATH}")
        return 1
    with open(HTML_PATH, encoding="utf-8") as f:
        html = f.read()

    print("=" * 64)
    print("2048 单文件静态契约检查")
    print("=" * 64)

    # ---------------- 1. 单文件 / 无外链 ----------------
    print("\n[1] 单文件与无外链")
    scripts = re.findall(r"<script\b[^>]*>([\s\S]*?)<\/script>", html, flags=re.I)
    check("文件大小合理", len(html) > 20000, f"{len(html) / 1024:.1f} KB")
    check("恰好一个内联 <script>", len(scripts) == 1, f"找到 {len(scripts)} 个")
    check("没有 <script src=...>", not re.search(r"<script\b[^>]*\bsrc=", html, flags=re.I))
    check("没有外链样式表", not re.search(r"<link\b[^>]*rel=[\"']?stylesheet", html, flags=re.I))
    check("没有 <img src=http...> 之类的外部资源",
          not re.search(r"<(img|iframe|audio|video|source)\b[^>]*\bsrc=[\"']?https?:", html, flags=re.I))

    source = scripts[0] if scripts else ""

    # 去注释后再找网络请求，避免把注释里的参考链接误判成运行时会联网
    code = strip_js_comments(source)
    check("代码里没有网络请求（fetch / XMLHttpRequest / WebSocket）",
          not re.search(r"\b(fetch\s*\(|XMLHttpRequest|WebSocket|EventSource|importScripts)\b", code))
    check("代码里没有 import / require / process 等 Node API",
          not re.search(r"\b(require\s*\(|module\.exports|process\.env|__dirname)", code))

    # ---------------- 2. HTML ↔ JS 的 id 契约 ----------------
    print("\n[2] HTML 与 JS 的元素 id 契约")
    id_in_html = set(re.findall(r"\bid=[\"']([^\"']+)[\"']", html))
    refs = set(re.findall(r"getElementById\(\s*[\"']([^\"']+)[\"']\s*\)", source))
    el_block = re.search(r"var EL_IDS\s*=\s*\{([\s\S]*?)\};", source)
    if el_block:
        refs |= set(re.findall(r"[\"']([^\"']+)[\"']", el_block.group(1)))
    refs |= set(re.findall(r"querySelector\(\s*[\"']#([^\"']+)[\"']\s*\)", source))
    missing = sorted(refs - id_in_html)
    check(f"JS 引用的元素 id 都存在于 HTML（共 {len(refs)} 个）",
          len(refs) >= 25 and not missing,
          f"缺失：{', '.join(missing) if missing else '无'}")

    # ---------------- 3. 功能点 ----------------
    print("\n[3] 功能点是否齐全")
    funcs = ["createGrid", "slideRow", "applyMove", "canMove", "addRandomTile",
             "cornerHeuristic", "aiPickDepth", "searchMax", "searchExp",
             "chooseMove", "playGame", "makeRng"]
    func_missing = [f for f in funcs if f"function {f}" not in source]
    check("核心函数都有定义", not func_missing, f"缺失：{', '.join(func_missing) if func_missing else '无'}")

    stage1 = {
        "计分制（得分/最高分/局数）": "stats.games" in source and "stats.best" in source,
        "重置按钮（清空本地记录）": "btn-reset" in id_in_html or "btnReset" in source,
        "主题切换（写入 localStorage）": "THEME_KEY" in source and "data-theme" in html,
        "多局战绩（最近 10 局）": "MAX_RECORDS" in source and "pushRecord" in source,
        "键盘操作": "ArrowUp" in source and "KEYMAP" in source,
        "鼠标拖拽 / 触屏滑动": "pointerdown" in source and "touchstart" in source,
    }
    for name, ok in stage1.items():
        check(f"阶段一 · {name}", ok)

    stage2 = {
        "AI 自动演示开关": "startAI" in source and "stopAI" in source,
        "AI 单步决策": "aiStep" in source,
        "硬指标 1024 判定": "WIN_TILE" in source and "1024" in source,
        "演示速度可调": "ai-speed" in id_in_html or "aiSpeed" in source,
    }
    for name, ok in stage2.items():
        check(f"阶段二 · {name}", ok)

    check("逻辑层导出 window.Game2048", "global.Game2048 = {" in source)
    check("UI 桥接层导出 window.__2048__", "window.__2048__ = {" in source)

    # ---------------- 汇总 ----------------
    print("\n" + "=" * 64)
    print(f"通过 {results['pass']} 项，失败 {results['fail']} 项")
    if failures:
        print("\n失败明细：")
        for f in failures:
            print("  - " + f)
        print("\n静态检查未通过")
        return 1
    print("静态检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
