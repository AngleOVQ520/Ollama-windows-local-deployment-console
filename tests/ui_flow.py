"""界面交互测试：悬浮窗、模型切换、发送/停止、HTML 预览、数学公式、各页面操作。需先运行 app-cn.py。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui_check import B, OUT, launch, sync_playwright  # noqa: E402

PASS, FAIL, errors, iframe_errors = [], [], [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


with sync_playwright() as p:
    ctx = launch(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    def on_console(m):
        if m.type != "error":
            return
        loc = (m.location or {}).get("url", "")
        (iframe_errors if "srcdoc" in loc else errors).append("[%s] %s @ %s" % (m.type, m.text, loc))

    def on_pageerror(e):
        stack = getattr(e, "stack", "") or ""
        (iframe_errors if "srcdoc" in stack else errors).append("[pageerror] %s" % e)

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.goto(B + "/#/chat")
    page.wait_for_selector(".composer")
    page.evaluate("localStorage.clear()")
    page.reload()
    page.wait_for_timeout(1200)
    page.click("[data-new]")

    print("== 悬浮窗")
    for sel, name in [("[data-model]", "模型切换"), ("[data-ctx]", "上下文"), ("[data-params]", "参数"), ("[data-think]", "思考")]:
        page.click(sel)
        page.wait_for_timeout(450)
        ok = page.locator(".popover.show").count() == 1
        page.screenshot(path=os.path.join(OUT, "pop-%s.png" % sel.strip("[]").replace("data-", "")))
        check("悬浮窗：" + name, ok)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

    print("== 选择 2B 模型（立即开始加载 + 进度条）")
    page.click("[data-model]")
    page.wait_for_timeout(300)
    page.locator(".mp-item", has_text="qwen3.5:2b").first.click()
    page.wait_for_timeout(300)
    seen = page.evaluate("document.querySelector('.load-bar').classList.contains('show')")
    check("选择后显示加载进度条", seen)
    page.wait_for_function("document.querySelector('.model-btn').classList.contains('loaded')", timeout=240000)
    check("模型加载完成", True, page.inner_text(".load-text"))

    print("== 思考强度设为 关闭，发送 HTML 请求")
    page.click("[data-think]")
    page.wait_for_timeout(300)
    page.locator(".tk-item", has_text="关闭").click()
    page.fill(".composer textarea", "写一个完整的单文件 HTML 页面：居中显示一个绿色渐变按钮，点击后数字加一。只输出代码块。再用 LaTeX 写出欧拉公式 $e^{i\\pi}+1=0$。")
    page.click("[data-send]")
    page.wait_for_timeout(600)
    check("发送后按钮变为停止", page.evaluate("document.querySelector('[data-send]').classList.contains('stop')"))
    page.wait_for_function("!document.querySelector('[data-send]').classList.contains('stop')", timeout=300000)
    page.wait_for_timeout(500)
    check("统计行显示", page.locator(".msg.assistant .stats").count() >= 1, page.inner_text(".msg.assistant .stats").replace("\n", " ")[:200])
    has_html = page.locator(".code-block .seg button", has_text="预览").count() > 0
    check("HTML 代码块有 代码/预览 切换", has_html)
    if has_html:
        page.locator(".code-block .seg button", has_text="预览").first.click()
        page.wait_for_timeout(1200)
        check("预览 iframe 显示", page.locator(".code-block.show-preview iframe").count() >= 1)
    if has_html:
        fr = page.frame_locator(".code-block.show-preview iframe").first
        page.wait_for_timeout(800)
        check("HTML 预览内按钮可见", fr.locator("button, body").first.is_visible())
    page.screenshot(path=os.path.join(OUT, "chat-html.png"), full_page=False)
    page.fill(".composer textarea", "直接写出：一元二次方程求根公式（用 $$ 块级公式）和勾股定理（行内 $ 公式），不要代码块。")
    page.click("[data-send]")
    page.wait_for_function("!document.querySelector('[data-send]').classList.contains('stop')", timeout=300000)
    page.wait_for_timeout(600)
    check("数学公式 KaTeX 渲染", page.locator(".msg.assistant .md > .katex-display, .msg.assistant .md .katex").count() >= 1,
          page.locator(".msg.assistant .katex").count())
    page.screenshot(path=os.path.join(OUT, "chat-math.png"), full_page=False)

    print("== 停止按钮")
    page.fill(".composer textarea", "写一篇 3000 字的长文介绍宇宙的起源")
    page.click("[data-send]")
    page.wait_for_selector(".msg.assistant.streaming .md:not(:empty)", timeout=120000)
    page.wait_for_timeout(1200)
    page.click("[data-send]")
    page.wait_for_function("!document.querySelector('[data-send]').classList.contains('stop')", timeout=30000)
    page.wait_for_timeout(500)
    check("停止后显示已停止标记", page.locator(".stats .st", has_text="已手动停止").count() >= 1)

    print("== 深度思考（mini）")
    page.click("[data-think]")
    page.wait_for_timeout(300)
    page.locator(".tk-item", has_text="Mini").click()
    page.fill(".composer textarea", "一个数列 1,1,2,3,5,8 下一个数是多少？")
    page.click("[data-send]")
    page.wait_for_selector(".think", timeout=120000)
    check("思考块出现", True)
    page.wait_for_function("!document.querySelector('[data-send]').classList.contains('stop')", timeout=300000)
    page.wait_for_timeout(500)
    last_stats = page.locator(".msg.assistant .stats").last.inner_text().replace("\n", " ")
    check("思考统计（推理耗时）", "推理" in last_stats and "—" not in last_stats.split("推理")[1][:6], last_stats[:200])
    page.screenshot(path=os.path.join(OUT, "chat-think.png"))

    print("== 历史侧栏：置顶 / 折叠")

    def pinned_count():
        return page.evaluate("fetch('/api/conversations').then(r=>r.json()).then(d=>d.data.filter(c=>c.pinned).length)")

    cid = page.locator(".conv-item").first.get_attribute("data-id")
    target = page.locator('.conv-item[data-id="%s"]' % cid)

    def toggle_pin():
        before = pinned_count()
        target.hover()
        target.locator("[data-m]").click()
        page.wait_for_timeout(250)
        page.locator(".menu button").filter(has_text="置顶").first.click()
        page.wait_for_timeout(1100)
        return before, pinned_count()

    b1, a1 = toggle_pin()
    b2, a2 = toggle_pin()
    check("置顶可切换（一次开启一次关闭）", abs(a1 - b1) == 1 and abs(a2 - b2) == 1 and (a1 - b1) == -(a2 - b2),
          "%s→%s, %s→%s" % (b1, a1, b2, a2))
    if a2 < b2:  # 最后一轮是取消置顶，再置顶一次用于后续断言
        b3, a3 = toggle_pin()
    check("置顶分组出现", page.locator(".sb-group", has_text="置顶").count() >= 1)
    page.click("[data-side]")
    page.wait_for_timeout(600)
    check("侧栏折叠", page.evaluate("document.querySelector('.sidebar').classList.contains('collapsed')"))
    page.click("[data-side]")
    page.wait_for_timeout(400)

    print("== 其他页面")
    page.goto(B + "/#/models")
    page.wait_for_timeout(1200)
    rows = page.locator("table.dt tbody tr").count()
    check("模型列表显示两个模型", rows >= 2, rows)
    hdr = page.locator("table.dt thead").inner_text()
    check("列顺序：备注/ID/类别/添加时间/参数量/大小/上下文", all(x in hdr for x in ["备注名称", "模型 ID", "类别", "添加时间", "参数量", "模型大小", "最大上下文"]))
    page.screenshot(path=os.path.join(OUT, "models-full.png"))
    page.goto(B + "/#/add")
    page.wait_for_timeout(1000)
    page.click("[data-src=gguf]")
    page.wait_for_timeout(400)
    page.fill("[data-gpath]", r"J:\ollama最终兵器\Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q8_0.gguf")
    page.click("[data-insp]")
    page.wait_for_selector(".gguf-info", timeout=20000)
    check("GGUF 解析展示", "262,144" in page.inner_text(".gg-detail"))
    page.screenshot(path=os.path.join(OUT, "add-gguf.png"))
    page.click("[data-newpart]")
    page.wait_for_timeout(400)
    page.click(".modal [data-pick]")
    page.wait_for_selector(".fb-drives .chip", timeout=8000)
    check("文件夹浏览器", page.locator(".fb-drives .chip").count() >= 1)
    page.screenshot(path=os.path.join(OUT, "add-browser.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    page.keyboard.press("Escape")
    page.goto(B + "/#/stats")
    page.wait_for_timeout(2000)
    check("统计图表渲染", page.locator(".chart canvas").count() >= 10, page.locator(".chart canvas").count())
    page.screenshot(path=os.path.join(OUT, "stats-full.png"), full_page=True)
    page.goto(B + "/#/settings")
    page.wait_for_timeout(1000)
    page.locator(".set-nav a", has_text="API 服务").click()
    page.wait_for_timeout(800)
    check("设置：API 状态运行中", page.locator(".api-st .tag.ok").count() == 1)
    page.screenshot(path=os.path.join(OUT, "settings-api.png"))
    # 记录原始主题，测完恢复，避免影响使用者自己的选择
    orig_theme = page.evaluate("() => fetch('/api/settings').then(r=>r.json()).then(d=>d.data.ui.theme)")
    page.locator(".set-nav a", has_text="数据与备份").click()
    page.wait_for_timeout(600)
    check("设置：显示数据库存储信息", "app.db" in page.inner_text(".st-info"), page.inner_text(".st-info")[:60].replace("\n", " "))
    page.locator(".seg button", has_text="浅色").first.click()
    page.wait_for_timeout(600)
    check("切换浅色主题", page.evaluate("document.documentElement.dataset.theme") == "light")
    page.goto(B + "/#/chat")
    page.wait_for_timeout(800)
    page.screenshot(path=os.path.join(OUT, "chat-light.png"))
    page.evaluate("(t) => fetch('/api/settings', {method:'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ui:{theme:t}})})", orig_theme)
    page.wait_for_timeout(400)
    check("已恢复原主题", page.evaluate("(t) => fetch('/api/settings').then(r=>r.json()).then(d=>d.data.ui.theme===t)", orig_theme), orig_theme)
    ctx.close()

print("\n控制台错误：%d（另有 %d 条来自模型生成的预览页面内部，属预期）" % (len(errors), len(iframe_errors)))
for e in errors:
    print("  ", e[:300])
for e in iframe_errors[:5]:
    print("   [预览页内部]", e[:150])
print("结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL or errors else 0)
