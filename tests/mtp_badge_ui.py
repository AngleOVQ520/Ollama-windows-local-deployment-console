"""UI 最终验证：MTP 模型加载 + 对话 → 统计行显示「MTP 加速中」徽标。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui_check import B, OUT, launch, sync_playwright  # noqa: E402

MODEL = "qwen35-9b-defiant-mtp:iq4_nl"
PASS, FAIL, errs = [], [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


with sync_playwright() as p:
    ctx = launch(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(B + "/#/chat")
    page.wait_for_selector(".composer")
    page.wait_for_timeout(1000)

    print("== 通过界面加载 MTP 模型")
    page.click("[data-model]")
    page.wait_for_timeout(400)
    page.locator(".mp-item", has_text="qwen35-9b-defiant-mtp").first.click()
    page.wait_for_timeout(800)
    # 自动模式下引擎会以 MTP 模式重启，加载时间较长
    page.wait_for_function("document.querySelector('.model-btn').classList.contains('loaded')", timeout=420000)
    check("模型加载完成", True, page.inner_text(".load-text")[:60])

    print("== 发送消息，验证统计行 MTP 徽标")
    page.fill(".composer textarea", "用两句话介绍故宫。")
    page.click("[data-send]")
    page.wait_for_selector("[data-send].stop", timeout=120000)
    page.wait_for_function("!document.querySelector('[data-send]').classList.contains('stop')", timeout=300000)
    page.wait_for_timeout(1500)
    stats_text = page.locator(".msg.assistant .stats").last.inner_text().replace("\n", " ")
    badge = page.locator(".msg.assistant .stats .st", has_text="MTP 加速中").last
    print("   统计行:", stats_text[:180])
    check("统计行显示「MTP 加速中」", badge.count() == 1)
    if badge.count():
        tip = badge.get_attribute("data-tip") or ""
        check("徽标悬浮含引擎证据", "speculative" in tip or "draft" in tip, tip[:80])
    page.screenshot(path=os.path.join(OUT, "mtp-badge.png"))

    print("== 历史记录持久化验证（刷新后徽标仍在）")
    api_mtp = page.evaluate("() => fetch('/api/load').then(r=>r.json()).then(d=>d.data.mtp)")
    print("   后端 /api/load 的 mtp 状态:", api_mtp)
    page.reload()
    page.wait_for_selector(".composer")
    page.wait_for_timeout(2500)
    page.locator(".conv-item").first.click()
    page.wait_for_timeout(1200)
    badge2 = page.locator(".msg.assistant .stats .st", has_text="MTP 加速中")
    check("刷新后徽标仍在（store.load.mtp 持久）", badge2.count() >= 1)
    check("全程无脚本错误", len(errs) == 0, errs[:3])
    ctx.close()

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
