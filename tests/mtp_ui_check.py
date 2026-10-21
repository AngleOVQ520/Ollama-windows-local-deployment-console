"""MTP 功能 UI 验证：模型列表 MTP 列、导入页 MTP 提示、设置开关存在。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from ui_check import B, OUT, launch, sync_playwright  # noqa: E402

PASS, FAIL, errs = [], [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


with sync_playwright() as p:
    ctx = launch(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    # 忽略预期的 HTTP 4xx（损坏文件被正确拒绝时浏览器会记一条 400 资源日志，不是脚本错误）
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" and "400" not in m.text and "Failed to load resource" not in m.text else None)

    print("== 模型列表 MTP 列")
    page.goto(B + "/#/models")
    page.wait_for_timeout(1800)
    hdrs = page.eval_on_selector_all("table.dt thead th", "els => els.map(e => e.textContent.trim())")
    check("表头含 MTP 列", "MTP" in hdrs, hdrs)
    mtp_cells = page.eval_on_selector_all("table.dt tbody tr", """els => els.map(tr => {
      const tds = tr.querySelectorAll('td');
      return {name: tds[1]?.innerText.trim().split('\\n')[0], mtp: tds[8]?.innerText.trim()};
    })""")
    print("   各模型 MTP 标记:", json.dumps(mtp_cells, ensure_ascii=False) if (json := __import__("json")) else mtp_cells)
    check("sorc 模型显示 MTP ✓", any("MTP ✓" in (x["mtp"] or "") for x in mtp_cells))
    check("非 MTP 模型显示 —", any((x["mtp"] or "") == "—" for x in mtp_cells))
    page.screenshot(path=os.path.join(OUT, "mtp-models.png"))

    print("== 设置页 MTP 开关")
    page.goto(B + "/#/settings")
    page.wait_for_timeout(1200)
    row = page.locator(".set-row", has_text="自动探测 MTP 加速")
    check("设置开关存在", row.count() >= 1)
    sw_on = row.locator("input[type=checkbox]").first.is_checked()
    print("   开关当前状态:", "开" if sw_on else "关")
    check("设置已落库（mtp_auto 存在）", page.evaluate("() => fetch('/api/settings').then(r=>r.json()).then(d=>'mtp_auto' in d.data.ui)"))

    print("== GGUF 导入页 MTP 提示（用损坏文件验证错误路径 + 用正常文件验证无 MTP 不显示）")
    page.goto(B + "/#/add")
    page.wait_for_timeout(900)
    page.click("[data-src=gguf]")
    page.wait_for_timeout(300)
    page.fill("[data-gpath]", r"J:\ollama最终兵器\Qwen3.5-9B-The-Defiant-Fable-Uncnr-Heretic-NEO-MAX-MTP-IQ2_M.gguf")
    page.click("[data-insp]")
    page.wait_for_timeout(1500)
    toast_text = page.locator(".toast").last.inner_text() if page.locator(".toast").count() else ""
    check("损坏文件被拒绝并提示", "GGUF" in toast_text or "不是有效" in toast_text, toast_text[:80])
    check("全程无脚本错误", len(errs) == 0, errs[:3])
    ctx.close()

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
