"""生图页 UI 冒烟测试：导航、页面渲染、资产状态、参数持久化。
用法：python tests/ui_image.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from ui_check import B, OUT, launch, sync_playwright  # noqa: E402

PASS, FAIL, errs = [], [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


with sync_playwright() as p:
    ctx = launch(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    page.goto(B + "/#/image")
    page.wait_for_selector(".img-composer", timeout=20000)
    page.wait_for_timeout(1200)

    check("导航里有「生图」入口", page.locator('.nav-tabs a[data-r="image"]').count() == 1)
    check("创作区渲染", page.locator("[data-prompt]").count() == 1)
    check("参考图拖拽区渲染", page.locator("[data-refzone]").count() == 1)
    check("尺寸预设 5 个", page.locator("[data-size]").count() == 5,
          page.locator("[data-size]").count())

    hint = page.locator("[data-engine-hint]").inner_text()
    check("引擎状态已显示", "引擎就绪" in hint or "未找到" in hint, hint.strip())

    assets = page.locator(".asset-row").count()
    check("资产面板 4 行", assets == 4, assets)
    miss = page.locator(".asset-row.miss").count()
    check("必需资产无缺失", miss == 0, "%d 缺失" % miss)
    page.screenshot(path=os.path.join(OUT, "image-page.png"))

    # 参数持久化：切到 3:4 并改步数，刷新后应保留
    page.locator('[data-size="768x1024"]').click()
    page.wait_for_timeout(600)
    page.fill("[data-steps]", "26")
    page.dispatch_event("[data-steps]", "change")
    page.wait_for_timeout(700)
    page.reload()
    page.wait_for_selector(".img-composer", timeout=20000)
    page.wait_for_timeout(1000)
    on = page.locator(".size-item.on").inner_text()
    steps = page.locator("[data-steps]").input_value()
    check("尺寸选择已持久化", "3:4" in on, on.replace("\n", " "))
    check("步数已持久化", steps == "26", steps)

    # 参数齐全性
    for sel, name in (("[data-cfg]", "CFG"), ("[data-seed]", "种子"), ("[data-batch]", "张数"),
                      ("[data-sampling]", "采样器"), ("[data-scheduler]", "调度器"),
                      ("[data-flow]", "flow-shift"), ("[data-guidance]", "guidance"),
                      ("[data-slg]", "SLG"), ("[data-clipskip]", "CLIP skip"),
                      ("[data-preview]", "实时预览"), ("[data-vaetiling]", "VAE 分块")):
        check("参数项：%s" % name, page.locator(sel).count() == 1)
    check("采样器选项 >= 20", page.locator("[data-sampling] option").count() >= 20,
          page.locator("[data-sampling] option").count())

    # 参考图上传 → 图生图参数出现
    ref = os.path.join(ROOT, "runtime", "shots", "product-white-v2.png")
    if os.path.isfile(ref):
        page.set_input_files("[data-reffile]", ref)
        page.wait_for_timeout(1500)
        check("参考图已上传并显示缩略图", page.locator(".ref-item img").count() >= 1,
              page.locator(".ref-item").count())
        check("图生图参数出现（strength / img-CFG）",
              page.locator(".i2i-only:not(.hidden) [data-strength]").count() == 1)
        page.screenshot(path=os.path.join(OUT, "image-page-i2i.png"))
        page.locator(".ref-item .rm").first.click()
        page.wait_for_timeout(300)
        check("移除参考图后回到文生图", page.locator(".i2i-only.hidden").count() == 1)
    else:
        check("参考图存在（跳过上传测试）", False, ref)

    # 设置页生图分区
    page.goto(B + "/#/settings")
    page.wait_for_selector("#set-image", timeout=20000)
    page.wait_for_timeout(900)
    check("设置页有「生图」分区", page.locator("#set-image").count() == 1)
    check("设置页生图状态已加载", "sd-cli" in page.locator("#set-image .img-st").inner_text(),
          page.locator("#set-image .img-st").inner_text()[:60].replace("\n", " "))
    page.screenshot(path=os.path.join(OUT, "settings-image.png"))

    check("无脚本错误", len(errs) == 0, errs[:3])
    ctx.close()

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
