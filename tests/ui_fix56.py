"""验证第 5/6 项修复与拖拽上传：
5. 添加模型页按钮内图标不再被放大/染色，垂直居中
6. 上下文/参数/思考三按钮连续快速点击，浮窗不再堆叠/拉长
4. 拖入 GGUF 自动上传并识别元数据（含 MTP 标记）
用法：python tests/ui_fix56.py
"""
import os
import struct
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import requests  # noqa: E402
from ui_check import B, OUT, launch, sync_playwright  # noqa: E402

PASS, FAIL, errs = [], [], []
NAME = "Test-MTP-7B-Q4_K_M.gguf"


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def build_gguf():
    """构造一个最小合法 GGUF v3（1 个 mtp 张量 + nextn 声明）。"""
    def s(x):
        b = x.encode("utf-8")
        return struct.pack("<Q", len(b)) + b

    def kv_str(k, v):
        return s(k) + struct.pack("<I", 8) + s(v)

    def kv_u32(k, v):
        return s(k) + struct.pack("<I", 4) + struct.pack("<I", v)

    kvs = b"".join([
        kv_str("general.architecture", "qwen3"),
        kv_str("general.name", "Synthetic MTP Test"),
        kv_u32("general.file_type", 15),
        kv_u32("qwen3.context_length", 32768),
        kv_u32("qwen3.block_count", 32),
        kv_u32("qwen3.embedding_length", 4096),
        kv_u32("qwen3.attention.head_count", 32),
        kv_u32("nextn_predict_layers", 1),
        kv_str("tokenizer.chat_template", "{{ .Prompt }}"),
    ])
    n_kv = 9
    head = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 1) + struct.pack("<Q", n_kv) + kvs
    # 1 个张量：mtp.fc.weight [4096, 4096] F32
    tensor = s("mtp.fc.weight") + struct.pack("<I", 2) + struct.pack("<Q", 4096) + struct.pack("<Q", 4096) \
        + struct.pack("<I", 0) + struct.pack("<Q", 0)
    return head + tensor


BUF = build_gguf()
print("合成 GGUF：%d 字节" % len(BUF))

with sync_playwright() as p:
    ctx = launch(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    # ---------- 5. 添加模型页按钮图标 ----------
    print("== 5. 浏览文件 / 扫描文件夹 按钮内图标")
    page.goto(B + "/#/add")
    page.wait_for_selector("[data-src=gguf]")
    page.click("[data-src=gguf]")
    page.wait_for_selector(".drop-zone")
    page.wait_for_timeout(400)
    info = page.evaluate("""() => {
      const pick = (sel) => {
        const btn = document.querySelector(sel);
        const svg = btn.querySelector('svg');
        const br = btn.getBoundingClientRect();
        const sr = svg.getBoundingClientRect();
        const cs = getComputedStyle(btn), ss = getComputedStyle(svg);
        const path = svg.querySelector('path, circle, line');
        return {color: cs.color, bg: cs.backgroundColor, stroke: ss.stroke,
                w: sr.width, h: sr.height,
                topGap: +(sr.top - br.top).toFixed(2), bottomGap: +(br.bottom - sr.bottom).toFixed(2),
                leftGap: +(sr.left - br.left).toFixed(2), rightGap: +(br.right - sr.right).toFixed(2),
                pathStroke: path ? getComputedStyle(path).stroke : null,
                zoneIcon: (() => { const z = document.querySelector('.drop-zone > .ico');
                  return z ? Math.round(z.getBoundingClientRect().width) : null; })()};
      };
      return {pickf: pick('[data-pickf]'), scan: pick('[data-scan]')};
    }""")
    for k, v in info.items():
        print("   %s: %s" % (k, v))
    for key, label in (("pickf", "浏览文件"), ("scan", "扫描文件夹")):
        v = info[key]
        check("%s 图标尺寸 18px" % label, abs(v["w"] - 18) < 0.6 and abs(v["h"] - 18) < 0.6, f'{v["w"]}x{v["h"]}')
        check("%s 图标颜色 = 按钮文字色（非背景同色）" % label,
              v["stroke"] == v["color"] and v["stroke"] != v["bg"], f'stroke={v["stroke"]} color={v["color"]} bg={v["bg"]}')
        check("%s 图标垂直居中" % label, abs(v["topGap"] - v["bottomGap"]) <= 1.5,
              f'topGap={v["topGap"]} bottomGap={v["bottomGap"]}')
        check("%s 图标紧贴左内边距（不是偏上/偏移）" % label, abs(v["leftGap"] - 15) <= 1.5,
              f'leftGap={v["leftGap"]}')
    check("拖拽区装饰图标仍为 40px", info["pickf"]["zoneIcon"] == 40, info["pickf"]["zoneIcon"])
    page.locator(".drop-zone .row").screenshot(path=os.path.join(OUT, "fix5-buttons.png"))

    # ---------- 4. 拖入 GGUF 自动识别 ----------
    print("== 4. 拖入 GGUF 自动识别")
    dt = page.evaluate_handle("""(arg) => {
      const dt = new DataTransfer();
      dt.items.add(new File([new Uint8Array(arg.bytes)], arg.name,
                            {type: 'application/octet-stream'}));
      return dt;
    }""", {"bytes": list(BUF), "name": NAME})
    page.evaluate("""(dt) => {
      const z = document.querySelector('.drop-zone');
      z.dispatchEvent(new DragEvent('dragenter', {bubbles: true, cancelable: true, dataTransfer: dt}));
      z.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: dt}));
    }""", dt)
    ok_box = False
    t0 = time.time()
    while time.time() - t0 < 25:
        if page.locator(".gg-detail .gguf-info").count():
            ok_box = True
            break
        page.wait_for_timeout(200)
    check("拖入后上传并完成解析", ok_box)
    if ok_box:
        page.wait_for_timeout(300)
        val = page.locator(".gg-detail [data-n]").input_value()
        check("建议模型名基于原始文件名", val == "test-mtp-7b:q4_k_m", val)
        txt = page.locator(".gg-detail").inner_text()
        check("元数据含架构/上下文", "qwen3" in txt and "32,768" in txt, txt[:120].replace("\n", " / "))
        check("识别出 MTP 头", "MTP" in txt and "mtp 张量" in txt, "MTP" in txt)
        check("标注临时上传（导入后自动删除）", "临时目录" in txt)
        page.locator(".drop-zone").screenshot(path=os.path.join(OUT, "fix4-upload.png"))
    # 清理临时上传
    try:
        requests.delete(B + "/api/gguf/uploads", timeout=30)
        print("   已清理临时上传")
    except Exception as e:
        print("   清理失败：", e)

    # ---------- 6. 三按钮连点不拉伸 ----------
    print("== 6. 上下文/参数/思考 连续快速点击")
    page.goto(B + "/#/chat")
    page.wait_for_selector(".composer")
    page.wait_for_timeout(1200)
    for sel in ("[data-ctx]", "[data-params]", "[data-think]"):
        # 先测一次稳定高度
        page.click(sel)
        page.wait_for_timeout(450)
        h0 = page.evaluate("() => { const p = document.querySelector('.popover.show'); return p ? p.getBoundingClientRect().height : 0; }")
        page.keyboard.press("Escape")
        page.wait_for_timeout(380)
        page.evaluate("""(sel) => {
          window.__samples = [];
          window.__t = setInterval(() => {
            const ps = [...document.querySelectorAll('.popover')];
            const b = document.querySelector(sel);
            window.__samples.push({n: ps.length,
              bw: b ? +b.getBoundingClientRect().width.toFixed(2) : 0,
              hs: ps.map(p => +p.getBoundingClientRect().height.toFixed(2))});
          }, 16);
        }""", sel)
        for _ in range(18):
            page.click(sel, delay=0)
            page.wait_for_timeout(65)
        page.wait_for_timeout(500)
        samples = page.evaluate("() => { clearInterval(window.__t); return window.__samples; }")
        max_h = max([h for s in samples for h in s["hs"]] or [0])
        widths = [s["bw"] for s in samples if s["bw"]]
        max_n = max([s["n"] for s in samples] or [0])
        n_now = page.locator(".popover").count()
        ripple = page.locator(sel + " .ripple").count()
        check("%s 按钮宽度不再被水波纹撑长（%.2f ~ %.2f）" % (sel, min(widths), max(widths)),
              widths and max(widths) - min(widths) <= 0.75 and ripple == 0,
              "ripple=%d" % ripple)
        check("%s 浮窗高度稳定（基线 %.0f，峰值 %.0f）" % (sel, h0, max_h),
              h0 > 0 and max_h <= h0 + 2.5, "max_n=%d" % max_n)
        check("%s 连点后无堆叠（当前 %d 个）" % (sel, n_now), n_now <= 1)
        page.keyboard.press("Escape")
        page.wait_for_timeout(420)

    check("全程无脚本错误", len(errs) == 0, errs[:3])
    page.screenshot(path=os.path.join(OUT, "fix6-chat.png"))
    ctx.close()

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
