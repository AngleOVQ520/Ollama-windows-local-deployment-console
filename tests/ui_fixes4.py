"""验证本轮四项改动：
1. 参数浮窗内可开关 MTP（仅 MTP 模型显示）
2. 三个工具按钮快速连点不再无限拉伸（稳定开/关）
3. 选择模型浮窗里 MTP 模型有高亮标注
4. 参数/上下文按钮图标描边正常可见
用法：python tests/ui_fixes4.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import requests  # noqa: E402
from ui_check import B, OUT, launch, sync_playwright  # noqa: E402

MODEL = "qwen35-9b-defiant-mtp:iq4_nl"
PASS, FAIL, errs = [], [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def j(method, path, **kw):
    r = requests.request(method, B + path, timeout=kw.pop("timeout", 300), **kw)
    d = r.json()
    assert d.get("ok"), d
    return d.get("data")


def wait(pred, timeout=400, step=0.5):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


pid = next(x["id"] for x in j("GET", "/api/partitions") if x["is_default"])
m = next(x for x in j("GET", "/api/models") if x["name"] == MODEL)
check("模型带 MTP 标记", m.get("has_mtp") == 1, "tensors=%s" % m.get("mtp_tensor_count"))
check("模型有 mtp_enabled 字段（默认开）", m.get("mtp_enabled") == 1, m.get("mtp_enabled"))

print("== 预加载 MTP 模型")
j("POST", "/api/load", json={"partition_id": pid, "model": MODEL, "num_ctx": 4096})
st = wait(lambda: (lambda s: s if s["status"] in ("loaded", "error") else None)(j("GET", "/api/load")))
check("模型已加载", st and st["status"] == "loaded", st and st.get("error"))

with sync_playwright() as p:
    ctx = launch(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    page.goto(B + "/#/chat")
    page.wait_for_selector(".composer")
    page.wait_for_timeout(1500)

    print("== 4. 图标可见性（描边/填充计算值）")
    icon_info = page.eval_on_selector_all("[data-params] .ico, [data-ctx] .ico, [data-think] .ico",
        """els => els.map(svg => {
          const path = svg.querySelector('path, circle');
          const cs = getComputedStyle(svg);
          const ps = path ? getComputedStyle(path) : {};
          const r = svg.getBoundingClientRect();
          return {stroke: cs.stroke, ps: ps.stroke, fill: cs.fill, pf: ps.fill,
                  w: Math.round(r.width), h: Math.round(r.height), sw: cs.strokeWidth};
        })""")
    for i, ic in enumerate(icon_info):
        print("   icon%d: stroke=%s path.stroke=%s fill=%s w=%s h=%s sw=%s" % (
            i, ic["stroke"], ic["ps"], ic["fill"], ic["w"], ic["h"], ic["sw"]))
    check("三个按钮图标都有描边颜色（非 fill 且非透明）",
          all(ic["ps"] not in ("none", "rgba(0, 0, 0, 0)") and ic["pf"] == "none" for ic in icon_info),
          [ic["ps"] for ic in icon_info])
    check("图标尺寸正常", all(ic["w"] >= 14 and ic["h"] >= 14 for ic in icon_info))
    page.screenshot(path=os.path.join(OUT, "fix4-composer.png"))

    print("== 3. 选择模型里的 MTP 高亮")
    page.click("[data-model]")
    page.wait_for_timeout(600)
    badges = page.locator(".popover .mp-mtp").count()
    hl = page.locator(".popover .mp-item.mtp").count()
    labels = page.eval_on_selector_all(".popover .mp-mtp", "els => els.map(e => e.textContent.trim())")
    check("MTP 模型有高亮徽标", badges >= 1, labels)
    check("MTP 模型行有高亮底色", hl >= 1, hl)
    sub = page.eval_on_selector_all(".popover .mp-mtp-sub", "els => els.map(e => e.textContent.trim())")
    check("悬浮信息含张量数", any("张量" in s for s in sub), sub[:2])
    page.screenshot(path=os.path.join(OUT, "fix4-picker.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    print("== 1. 参数浮窗内 MTP 开关")
    page.click("[data-params]")
    page.wait_for_timeout(700)
    check("参数浮窗显示 MTP 卡片", page.locator(".popover .pp-mtp").count() == 1)
    sw = page.locator(".popover .pp-mtp input[type=checkbox]")
    check("MTP 开关默认开启", sw.count() == 1 and sw.first.is_checked())
    page.screenshot(path=os.path.join(OUT, "fix4-params-mtp.png"))
    # 关闭（input 被自定义开关隐藏，点击外层 label/开关）
    page.locator(".popover .pp-mtp .switch").first.click()
    page.wait_for_timeout(800)
    mm = next(x for x in j("GET", "/api/models") if x["name"] == MODEL)
    check("关闭后数据库 mtp_enabled=0", mm.get("mtp_enabled") == 0, mm.get("mtp_enabled"))
    print("   等待模型以非 MTP 模式重新加载…")
    st2 = wait(lambda: (lambda s: s if s["status"] == "loaded" and s["model"] == MODEL else None)(j("GET", "/api/load")), 300)
    check("关闭后重新加载完成", st2 is not None)
    page.wait_for_timeout(1200)
    # 再打开
    if page.locator(".popover .pp-mtp").count() == 0:
        page.click("[data-params]")
        page.wait_for_timeout(600)
    sw = page.locator(".popover .pp-mtp input[type=checkbox]")
    if sw.count():
        page.locator(".popover .pp-mtp .switch").first.click()
        page.wait_for_timeout(800)
    mm = next(x for x in j("GET", "/api/models") if x["name"] == MODEL)
    check("重新开启后 mtp_enabled=1", mm.get("mtp_enabled") == 1, mm.get("mtp_enabled"))
    wait(lambda: (lambda s: s if s["status"] == "loaded" and s["model"] == MODEL else None)(j("GET", "/api/load")), 300)
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    print("== 2. 快速连点三个按钮（不应无限拉伸/堆叠）")
    for sel in ("[data-params]", "[data-ctx]", "[data-think]"):
        page.wait_for_timeout(500)
        for _ in range(8):
            page.click(sel, delay=0)
            page.wait_for_timeout(60)
        page.wait_for_timeout(500)
        n_open = page.locator(".popover:not(.leaving)").count()
        n_all = page.locator(".popover").count()
        check("%s 连点后浮层数量 <= 1（实际 DOM %d，可见 %d）" % (sel, n_all, n_open), n_open <= 1,
              "all=%d open=%d" % (n_all, n_open))
        page.keyboard.press("Escape")
        page.wait_for_timeout(420)

    check("全程无脚本错误", len(errs) == 0, errs[:3])
    ctx.close()

print("== 清理：恢复 MTP 开启并卸载")
try:
    j("PATCH", "/api/models/%d" % m["id"], json={"mtp_enabled": 1})
    j("POST", "/api/unload")
except Exception as e:
    print("清理提示：", e)

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
