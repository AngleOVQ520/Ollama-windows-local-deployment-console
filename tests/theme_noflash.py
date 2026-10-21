"""验证：重启后端后，重新打开页面首帧就是用户选择的主题（不会再先闪一下深色）。
用法：python tests/theme_noflash.py（需后端已在运行）
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import requests  # noqa: E402
from ui_check import B, OUT, launch, sync_playwright  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


db_theme = requests.get(B + "/api/settings", timeout=10).json()["data"]["ui"]["theme"]
meta = requests.get(B + "/api/settings/meta", timeout=10).json()["data"]
print("数据库中的主题:", db_theme, "| 存储来源:", meta["source"], "| 设置行数:", meta["rows"])

with sync_playwright() as p:
    ctx = launch(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    # 从文档最开始记录 data-theme 的每一次变化（首帧就被 inline 脚本设置 → 不应出现 dark）
    page.add_init_script("""
      window.__themeTrail = [];
      window.__themeAtDOMReady = null;
      window.__bgAtDOMReady = null;
      (function arm() {
        // init script 运行得极早，此时 documentElement 可能还不存在，需要等到就位再挂观察器
        if (!document.documentElement) return setTimeout(arm, 0);
        new MutationObserver(() => window.__themeTrail.push(document.documentElement.dataset.theme))
          .observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
        // 记录"解析完成时"的值（此时 <head> 里的 inline 脚本已执行）
        window.__themeTrail.push(document.documentElement.dataset.theme);
        document.addEventListener('DOMContentLoaded', () => {
          window.__themeAtDOMReady = document.documentElement.dataset.theme;
          window.__bgAtDOMReady = getComputedStyle(document.body).backgroundColor;
        });
      })();
    """)
    page.goto(B + "/#/chat")
    page.wait_for_selector(".composer")
    page.wait_for_timeout(1500)
    cache = page.evaluate("() => JSON.parse(localStorage.getItem('ui-cache') || '{}')")
    check("本地缓存与数据库主题一致", cache.get("theme") == db_theme, cache.get("theme"))
    page.reload()
    page.wait_for_selector(".composer")
    page.wait_for_timeout(1200)
    trail = page.evaluate("() => window.__themeTrail")
    at_ready = page.evaluate("() => window.__themeAtDOMReady")
    bg = page.evaluate("() => window.__bgAtDOMReady")
    now = page.evaluate("() => document.documentElement.dataset.theme")
    print("   data-theme 变化轨迹:", trail, "| DOM 就绪时:", at_ready, "| 现在:", now, "| 首帧背景:", bg)
    check("首帧即为目标主题（无深色闪烁）", at_ready == db_theme, at_ready)
    check("加载全程未切过其它主题", all(t == db_theme for t in trail) and trail, trail)
    check("最终主题正确", now == db_theme, now)
    if db_theme == "light":
        check("浅色首帧背景确实是浅色", bg not in ("rgb(9, 12, 13)", "rgba(0, 0, 0, 0)"), bg)
    page.screenshot(path=os.path.join(OUT, "theme-first-paint.png"))
    ctx.close()

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
