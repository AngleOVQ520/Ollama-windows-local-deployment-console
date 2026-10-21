"""确认浏览器实际渲染出的 SVG 已带内联描边属性（修复缓存后复审）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from ui_check import B, launch, sync_playwright  # noqa: E402

with sync_playwright() as p:
    ctx = launch(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(B + "/#/chat")
    page.wait_for_selector(".composer")
    page.wait_for_timeout(1200)
    html = page.eval_on_selector("[data-params] .ico", "el => el.outerHTML")
    print("参数按钮 SVG:", html[:160])
    ok1 = 'fill="none"' in html and 'stroke="currentColor"' in html
    print("  内联描边属性:", "YES" if ok1 else "NO")
    page.locator(".comp-bar").screenshot(path=os.path.join(os.path.dirname(__file__), "..", "runtime", "fix4-final-bar.png"))

    page.goto(B + "/#/add")
    page.wait_for_timeout(900)
    page.click("[data-src=gguf]")
    page.wait_for_timeout(400)
    h2 = page.eval_on_selector("[data-pickf] .ico", "el => el.outerHTML")
    h3 = page.eval_on_selector("[data-scan] .ico", "el => el.outerHTML")
    print("浏览文件 SVG:", h2[:120])
    print("扫描文件夹 SVG:", h3[:120])
    ok2 = 'stroke="currentColor"' in h2 and 'stroke="currentColor"' in h3
    print("  按钮图标内联描边:", "YES" if ok2 else "NO")
    page.locator(".drop-zone").screenshot(path=os.path.join(os.path.dirname(__file__), "..", "runtime", "fix4-final-dropzone.png"))
    ctx.close()
sys.exit(0 if ok1 and ok2 else 1)
