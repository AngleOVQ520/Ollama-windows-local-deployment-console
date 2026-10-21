"""验证 MTP 开关真的影响推理：关闭→检测不到推测解码；开启→检测到。
并截取输入区局部图检查图标观感。
用法：python tests/mtp_toggle_effect.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import requests  # noqa: E402
from ui_check import B, OUT, launch, sync_playwright  # noqa: E402

MODEL = "qwen35-9b-defiant-mtp:iq4_nl"
PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def j(method, path, **kw):
    r = requests.request(method, B + path, timeout=kw.pop("timeout", 300), **kw)
    d = r.json()
    assert d.get("ok"), d
    return d.get("data")


def wait(pred, timeout=360, step=0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


pid = next(x["id"] for x in j("GET", "/api/partitions") if x["is_default"])
mid = next(x["id"] for x in j("GET", "/api/models") if x["name"] == MODEL)

print("== 关闭 MTP 后重新加载")
j("POST", "/api/load", json={"partition_id": pid, "model": MODEL, "num_ctx": 4096})
wait(lambda: (lambda s: s if s["status"] == "loaded" else None)(j("GET", "/api/load")))
j("PATCH", "/api/models/%d" % mid, json={"mtp_enabled": 0})
st = wait(lambda: (lambda s: s if s["status"] == "loaded" else None)(j("GET", "/api/load")))
mtp = wait(lambda: (lambda s: s["mtp"] if s["mtp"] else None)(j("GET", "/api/load")), 40)
check("关闭后模型加载成功", st is not None)
check("关闭后检测不到 MTP", mtp and mtp["detected"] is False, mtp and mtp["evidence"])

print("== 开启 MTP 后重新加载")
j("PATCH", "/api/models/%d" % mid, json={"mtp_enabled": 1})
st = wait(lambda: (lambda s: s if s["status"] == "loaded" else None)(j("GET", "/api/load")))
mtp = wait(lambda: (lambda s: s["mtp"] if s["mtp"] else None)(j("GET", "/api/load")), 40)
check("开启后模型加载成功", st is not None)
check("开启后检测到 MTP", mtp and mtp["detected"] is True, mtp and mtp["evidence"])

print("== 输入区图标局部截图")
with sync_playwright() as p:
    ctx = launch(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(B + "/#/chat")
    page.wait_for_selector(".composer")
    page.wait_for_timeout(1500)
    page.locator(".comp-bar").screenshot(path=os.path.join(OUT, "fix4-icons-zoom.png"))
    # 悬停参数按钮，看图标 hover 态
    page.hover("[data-params]")
    page.wait_for_timeout(400)
    page.locator(".comp-bar").screenshot(path=os.path.join(OUT, "fix4-icons-hover.png"))
    print("   已保存 fix4-icons-zoom.png / fix4-icons-hover.png")
    ctx.close()

print("== 清理：卸载")
j("POST", "/api/unload")
print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
