"""检查添加模型页按钮图标的实际渲染（位置/颜色）并截图。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from ui_check import B, OUT, launch, sync_playwright  # noqa: E402

os.makedirs(OUT, exist_ok=True)
with sync_playwright() as p:
    ctx = launch(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(B + "/#/add")
    page.wait_for_selector("[data-src=gguf]")
    page.click("[data-src=gguf]")
    page.wait_for_selector(".drop-zone")
    page.wait_for_timeout(500)

    info = page.evaluate("""() => {
      const pick = (sel) => {
        const btn = document.querySelector(sel);
        const svg = btn.querySelector('svg');
        const path = svg.querySelector('path');
        const br = btn.getBoundingClientRect();
        const sr = svg.getBoundingClientRect();
        const cs = getComputedStyle(btn);
        const csSvg = getComputedStyle(svg);
        return {btnColor: cs.color, bg: cs.backgroundColor, stroke: csSvg.stroke,
                btnH: br.height, svgTopGap: sr.top - br.top, svgBottomGap: br.bottom - sr.bottom,
                svgW: sr.width, svgH: sr.height,
                pathStroke: getComputedStyle(path).stroke};
      };
      return {pickf: pick('[data-pickf]'), scan: pick('[data-scan]')};
    }""")
    for k, v in info.items():
        print(k, v)
    page.locator(".drop-zone").screenshot(path=os.path.join(OUT, "diag-dropzone.png"))
    page.locator(".drop-zone .row").screenshot(path=os.path.join(OUT, "diag-buttons.png"))
    ctx.close()
