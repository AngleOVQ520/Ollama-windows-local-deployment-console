"""生图链路最小端到端验证：提交极小任务（256²/2 步）→ 进度递增 → 产物可下载 → 清理。
用法：python tests/e2e_image.py
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
import requests  # noqa: E402

B = "http://127.0.0.1:8848"
S = requests.Session()
S.trust_env = False
PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def j(method, path, **kw):
    r = S.request(method, B + path, timeout=kw.pop("timeout", 120), **kw)
    d = r.json()
    assert d.get("ok"), (path, d)
    return d.get("data")


print("== 提交最小任务（256x256 / 2 步 / proj 预览）")
job = j("POST", "/api/image/generate", json={
    "prompt": "a red apple on a white table", "negative": "blurry",
    "width": 256, "height": 256, "steps": 2, "cfg_scale": 4.0, "seed": 1234,
    "batch": 1, "sampling": "euler", "scheduler": "", "flow_shift": 3.0,
    "preview": "proj", "vae_tiling": False,
})
jid = job["id"]
print("   job:", jid, "params:", job["params"])
check("任务已受理", bool(jid))

progress, stages, last = [], set(), None
t0 = time.time()
while time.time() - t0 < 600:
    st = j("GET", "/api/image/jobs/%s" % jid)
    if st["progress"] != last:
        progress.append(st["progress"])
        last = st["progress"]
    if st.get("stage"):
        stages.add(st["stage"])
    if st["status"] in ("done", "error", "cancelled"):
        break
    time.sleep(0.8)

print("   状态:", st["status"], "| 阶段:", sorted(stages), "| 进度采样:", progress[:12], "…")
check("任务完成", st["status"] == "done", st.get("error"))
check("进度是递增的（不是 0→100 跳变）", len(progress) >= 3, len(progress))
check("识别到采样阶段", "采样" in stages, sorted(stages))
check("有产物", len(st.get("outputs") or []) >= 1, len(st.get("outputs") or []))
if st.get("outputs"):
    o = st["outputs"][0]
    r = S.get(B + o["url"], timeout=60)
    check("产物可下载且为 PNG", r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n",
          "%s %d 字节" % (r.status_code, len(r.content)))
    check("产物落在项目目录内", os.path.isfile(os.path.join(ROOT, "data", "images", jid, o["name"])))
check("记录了耗时", (st.get("elapsed_ms") or 0) > 0, st.get("elapsed_ms"))

print("== 取消能力")
job2 = j("POST", "/api/image/generate", json={"prompt": "x", "width": 256, "height": 256, "steps": 30})
time.sleep(2)
j("POST", "/api/image/jobs/%s/cancel" % job2["id"])
t1 = time.time()
while time.time() - t1 < 120:
    s2 = j("GET", "/api/image/jobs/%s" % job2["id"])
    if s2["status"] in ("cancelled", "error", "done"):
        break
    time.sleep(0.6)
check("第二个任务已结束", s2["status"] in ("cancelled", "error", "done"), s2["status"])

print("== 清理测试任务")
for x in (jid, job2["id"]):
    try:
        j("DELETE", "/api/image/jobs/%s" % x)
    except Exception as e:
        print("   清理失败:", x, e)
left = [x for x in j("GET", "/api/image/jobs?limit=50") if x["id"] in (jid, job2["id"])]
check("测试任务已删除", not left, left)

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
