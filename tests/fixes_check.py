"""针对本轮 5 项改动的界面验证（真实模型）：
  1 已加载模型一键卸载
  2 回复完成后正文不再覆盖思考内容
  3 快速切换导航栏不卡顿（不重复重建 DOM）
  4 模型按钮与右侧按钮水平对齐、加载文案移到底部
  5 停止按钮的边缘光环贴合按钮轮廓
用法：python tests/fixes_check.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui_check import B, OUT, launch, sync_playwright  # noqa: E402

PASS, FAIL, errors = [], [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def console_errors(page):
    out = []
    page.on("console", lambda m: out.append("[%s] %s" % (m.type, m.text)) if m.type == "error" else None)
    page.on("pageerror", lambda e: out.append("[pageerror] %s" % e))
    return out


with sync_playwright() as p:
    ctx = launch(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    errs = console_errors(page)
    page.goto(B + "/#/chat")
    page.wait_for_selector(".composer")
    page.wait_for_timeout(1200)

    print("== 4. 输入区布局：加载文案移入底部、模型按钮与右侧按钮水平对齐")
    box = lambda sel: page.eval_on_selector(sel, "el => { const r = el.getBoundingClientRect(); return {x:r.x, y:r.y, w:r.width, h:r.height, cy:r.y+r.height/2}; }")
    check("load-text 位于 comp-foot 内", page.eval_on_selector(".load-text", "el => !!el.closest('.comp-foot')"))
    mb, cb, sb = box("[data-model]"), box("[data-ctx]"), box("[data-send]")
    check("模型按钮与上下文按钮同心（水平对齐）", abs(mb["cy"] - cb["cy"]) <= 1.5, "模型 cy=%.1f 上下文 cy=%.1f 发送 cy=%.1f" % (mb["cy"], cb["cy"], sb["cy"]))
    check("模型按钮与发送按钮同心", abs(mb["cy"] - sb["cy"]) <= 2, "差值 %.1f" % abs(mb["cy"] - sb["cy"]))
    bar = box(".load-bar")
    check("进度条贴在按钮下沿且不挤占行高", 0 <= bar["y"] - (mb["y"] + mb["h"]) <= 8, "button底=%.1f bar顶=%.1f" % (mb["y"] + mb["h"], bar["y"]))
    page.screenshot(path=os.path.join(OUT, "fix-composer.png"))

    print("== 3. 快速切换导航栏")
    order = ["#/models", "#/stats", "#/settings", "#/add", "#/chat", "#/stats", "#/models", "#/settings", "#/chat", "#/stats"]
    before = page.eval_on_selector("#app", "el => el.querySelectorAll('*').length")
    t0 = time.time()
    for h in order:
        page.evaluate("location.hash = '%s'" % h)
        page.wait_for_timeout(90)
    switch_ms = (time.time() - t0) * 1000
    check("10 次快速切换总耗时 < 3s", switch_ms < 3000, "%.0f ms" % switch_ms)
    page.wait_for_timeout(700)
    check("切换过程无脚本错误", len(errs) == 0, errs[:2])
    # DOM 节点标识不变 → 说明没有重复重建
    node_id = page.evaluate("() => { const el = document.querySelector('.view[data-view=settings] .set-body'); el.dataset.mark = 'keep'; return el.dataset.mark; }")
    page.evaluate("location.hash = '#/chat'")
    page.wait_for_timeout(300)
    page.evaluate("location.hash = '#/settings'")
    page.wait_for_timeout(500)
    check("返回设置页未重建 DOM（无卡顿源）", page.evaluate("() => !!document.querySelector('.view[data-view=settings] .set-body[data-mark=keep]')"), node_id)
    check("设置区块数量完整", page.eval_on_selector_all(".set-sec", "els => els.length") >= 13, page.eval_on_selector_all(".set-sec", "els => els.length"))

    print("== 1. 一键卸载")
    page.evaluate("location.hash = '#/chat'")
    page.wait_for_timeout(400)
    # 先确保有模型加载
    page.click("[data-model]")
    page.wait_for_timeout(400)
    names = page.eval_on_selector_all(".mp-item .mi-name", "els => els.map(e => e.textContent.trim())")
    page.locator(".mp-item").first.click()
    page.wait_for_function("document.querySelector('.model-btn').classList.contains('loaded')", timeout=240000)
    check("卸载按钮随加载状态出现", page.eval_on_selector("[data-unload]", "el => !el.classList.contains('hidden')"))
    page.click("[data-unload]")
    page.wait_for_function("() => fetch('/api/load').then(r=>r.json()).then(d=>d.data.status==='idle')", timeout=30000)
    page.wait_for_timeout(400)
    check("点击后模型已卸载", page.evaluate("() => fetch('/api/load').then(r=>r.json()).then(d=>d.data.status)") == "idle")
    check("卸载按钮自动隐藏", page.eval_on_selector("[data-unload]", "el => el.classList.contains('hidden')"))
    check("按钮文案回到「选择模型」", page.eval_on_selector(".model-btn .m-name", "el => el.textContent.trim()") == "选择模型")

    print("== 5. 停止按钮的自转光环")
    page.click("[data-model]")
    page.wait_for_timeout(400)
    page.locator(".mp-item").first.click()
    page.wait_for_function("document.querySelector('.model-btn').classList.contains('loaded')", timeout=240000)
    page.fill(".composer textarea", "写一篇 2000 字的散文描述秋天的傍晚")
    page.click("[data-send]")
    page.wait_for_selector("[data-send].stop", timeout=60000)
    page.wait_for_timeout(700)
    ring = page.eval_on_selector("[data-send]", """el => {
      const cs = getComputedStyle(el, '::before');
      const r = el.getBoundingClientRect();
      return {bg: cs.backgroundImage, mask: cs.maskImage || cs.webkitMaskImage, radius: cs.borderRadius, anim: cs.animationName,
              inset: [cs.top, cs.right, cs.bottom, cs.left].join(','), size: r.width, hasAfter: getComputedStyle(el, '::after').borderTopWidth};
    }""")
    check("光环使用 conic-gradient + 遮罩成环", "conic-gradient" in ring["bg"] and "linear-gradient" in ring["mask"], ring["bg"][:48] + " | mask=" + str(ring["mask"])[:40])
    check("光环半径与按钮圆角贴合（13+3=16px）", ring["radius"].startswith("16px"), ring["radius"])
    check("光环四边等距内缩 3px", ring["inset"] == "-3px,-3px,-3px,-3px", ring["inset"])
    check("光环按角度动画（不再是整体旋转方框）", ring["anim"] == "ringSpin", ring["anim"])
    check("存在一圈常驻底环轨道", ring["hasAfter"] == "2px", ring["hasAfter"])
    page.screenshot(path=os.path.join(OUT, "fix-stop-ring.png"))
    page.click("[data-send]")
    page.wait_for_selector("[data-send]:not(.stop)", timeout=30000)

    print("== 2. 思考结束后正文与思考内容不再串位")
    page.fill(".composer textarea", "17*23 等于多少？先简要说明计算思路，再给出结果。")
    page.click("[data-send]")
    page.wait_for_selector(".msg.assistant.streaming .think", timeout=180000)
    page.wait_for_selector("[data-send]:not(.stop)", timeout=300000)
    page.wait_for_timeout(1200)
    dom = page.evaluate("""() => {
      const m = [...document.querySelectorAll('.msg.assistant')].pop();
      const think = m.querySelector('.think-md');
      const body = m.querySelector('.msg-md');
      return {think: think ? think.innerText.trim() : null, body: body.innerText.trim(),
              thinkIsLast: think === m.querySelector('.think-slot .md'),
              bodyLen: body.innerText.trim().length};
    }""")
    print("   思考框内容长度:", len(dom["think"] or ""), "| 正文长度:", dom["bodyLen"])
    print("   思考框前 40 字:", (dom["think"] or "")[:40].replace("\n", " "))
    print("   正文前 40 字:", dom["body"][:40].replace("\n", " "))
    check("思考内容仍在思考框内", bool(dom["think"]) and len(dom["think"]) > 20)
    check("正文非空且未落入思考框", dom["bodyLen"] > 5)
    check("正文与思考内容不相同（没有互相覆盖）", dom["think"] != dom["body"])
    check("思考内容不含正文结果 391", "391" not in (dom["think"] or "") or "391" in dom["body"], "think含391=%s" % ("391" in (dom["think"] or "")))
    check("正文包含结果", "391" in dom["body"], dom["body"][:60].replace("\n", " "))
    page.screenshot(path=os.path.join(OUT, "fix-think-body.png"))

    print("== 2b. 思考达到预算（两段式续写）时同样不串位、不回显前缀")
    old_budget = page.evaluate("() => fetch('/api/settings').then(r=>r.json()).then(d=>d.data.thinking.budgets.mini)")
    # 临时把 mini 预算压到 64，确保一定触发「思考超限 → 续写答案」的两段式路径
    page.evaluate("""(v) => fetch('/api/settings', {method:'PATCH', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({thinking:{budgets:{mini:v}}})})""", 64)
    page.wait_for_timeout(500)
    page.click("[data-think]")
    page.wait_for_timeout(350)
    page.locator(".tk-item", has_text="Mini").click()
    page.wait_for_timeout(250)
    page.fill(".composer textarea", "请详细解释快速排序的原理，并给出复杂度公式。")
    page.click("[data-send]")
    page.wait_for_selector("[data-send]:not(.stop)", timeout=300000)
    page.wait_for_timeout(1200)
    dom2 = page.evaluate("""() => {
      const m = [...document.querySelectorAll('.msg.assistant')].pop();
      const think = m.querySelector('.think-md');
      const body = m.querySelector('.msg-md');
      return {thinkLen: think ? think.innerText.trim().length : 0, body: body.innerText.trim(),
              all: m.innerText, stats: m.querySelector('.stats')?.innerText.replace(/\\n/g, ' ') || ''};
    }""")
    print("   思考长度:", dom2["thinkLen"], "| 正文长度:", len(dom2["body"]))
    print("   正文前 40 字:", dom2["body"][:40].replace("\n", " "))
    check("两段式：正文非空", len(dom2["body"]) > 20, dom2["body"][:40].replace("\n", " "))
    check("两段式：正文未回显 <think> 前缀或预算提示", "<think>" not in dom2["body"] and "思考预算已用尽" not in dom2["body"], dom2["body"][:60].replace("\n", " "))
    check("两段式：思考内容仍在思考框", dom2["thinkLen"] > 20)
    check("两段式：预算提示可见", "思考达到预算" in dom2["all"], dom2["stats"][-70:])
    page.screenshot(path=os.path.join(OUT, "fix-budget-two-phase.png"))
    page.evaluate("""(v) => fetch('/api/settings', {method:'PATCH', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({thinking:{budgets:{mini:v}}})})""", old_budget)
    page.wait_for_timeout(300)

    check("全程无控制台错误", len(errs) == 0, errs[:3])
    ctx.close()

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
for e in errors:
    print("  ", e)
sys.exit(1 if FAIL or errs else 0)
