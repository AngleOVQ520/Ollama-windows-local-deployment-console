"""多分区与导入模式测试：第二个分区独立引擎、拉取小模型、强制复制模式导入、分区隔离与清理。
需先运行 app-cn.py。用法：python tests/multi_partition.py [base_url]
"""
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
import requests  # noqa: E402

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8848"
S = requests.Session()
S.trust_env = False
PASS, FAIL = [], []


def j(method, path, **kw):
    r = S.request(method, B + path, timeout=kw.pop("timeout", 300), **kw)
    d = r.json()
    if not d.get("ok"):
        raise AssertionError("%s %s -> %s" % (method, path, str(d)[:300]))
    return d.get("data")


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def wait(pred, timeout=600, step=1):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


def job_done(jid):
    return next((x for x in j("GET", "/api/jobs") if x["id"] == jid and x["status"] in ("done", "error", "cancelled")), None)


print("== 1. 创建第二个分区")
p2dir = os.path.join(ROOT, "models", "test-second")
p2 = j("POST", "/api/partitions", json={"name": "第二分区", "path": p2dir, "color": "#f4715e"})
p2id = p2["id"]

print("== 2. 在第二分区拉取小模型 smollm2:135m（验证独立引擎与分区隔离）")
job = j("POST", "/api/jobs/pull", json={"partition_id": p2id, "model": "smollm2:135m", "remark": "冒烟测试小模型"})
print("   job:", job["id"], job["stage"])
mid_seen = []


def progress():
    js = [x for x in j("GET", "/api/jobs") if x["id"] == job["id"]][0]
    if js["percent"] and round(js["percent"]) not in mid_seen:
        mid_seen.append(round(js["percent"]))
    return js if js["status"] in ("done", "error", "cancelled") else None


done = wait(progress, 900, 1.5)
check("拉取到第二分区完成", done and done["status"] == "done", done and done["message"])
check("拉取过程有进度回调", len(mid_seen) >= 3, mid_seen[:12])
check("文件落在第二分区目录", os.path.isdir(os.path.join(p2dir, "blobs")) and len(os.listdir(os.path.join(p2dir, "blobs"))) >= 2)
parts = j("GET", "/api/partitions")
check("两个分区引擎同时运行", sum(1 for x in parts if x["engine"]["status"] == "running") >= 2,
      [(x["name"], x["engine"]["status"], x["engine"]["port"]) for x in parts])
m2 = [m for m in j("GET", "/api/models") if m["partition_id"] == p2id]
check("模型归属第二分区", any(m["name"] == "smollm2:135m" for m in m2), [(m["name"], m["remark"]) for m in m2])

print("== 3. 加载并对话（无思考能力的模型应自动忽略 think）")
j("POST", "/api/load", json={"partition_id": p2id, "model": "smollm2:135m"})
st = wait(lambda: (lambda s: s if s["status"] in ("loaded", "error") else None)(j("GET", "/api/load")), 180)
check("第二分区模型加载", st and st["status"] == "loaded", st and (st["num_ctx"], st["error"]))
cid = j("POST", "/api/conversations", json={})["id"]
rid = j("POST", "/api/conversations/%s/send" % cid, json={"content": "Say hello in one word.", "partition_id": p2id, "model": "smollm2:135m", "think": "high"})["run_id"]
r = S.get(B + "/api/runs/%s/stream" % rid, stream=True, timeout=300)
ev, out = None, {"content": "", "thinking": ""}
for line in r.iter_lines(decode_unicode=True):
    if line.startswith("event:"):
        ev = line[6:].strip()
    elif line.startswith("data:"):
        d = json.loads(line[5:])
        if ev in ("content", "thinking"):
            out[ev] += d["t"]
        if ev == "done":
            out["done"] = d
            break
r.close()
check("小模型对话成功", out["done"]["status"] == "ok" and out["content"].strip(), out["content"][:60].replace("\n", " "))
check("不支持思考的模型未报错", not out["thinking"], len(out["thinking"]))
rn = [x["name"] for x in j("GET", "/api/running")]
check("仅驻留当前模型（切换时卸载其他分区模型）", rn == ["smollm2:135m"], rn)

print("== 4. 强制复制模式导入（验证复制分支）")
big = os.path.join(ROOT, "Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q8_0.gguf")
job = j("POST", "/api/jobs/import", json={"partition_id": p2id, "path": big, "name": "copy-mode-test:q8", "mode": "copy"})
done = wait(lambda: job_done(job["id"]), 900)
check("复制模式导入完成", done and done["status"] == "done", done and done["message"])
dst = os.path.join(p2dir, "blobs")
size = os.path.getsize(big)
check("复制后文件大小一致", any(os.path.getsize(os.path.join(dst, f)) == size for f in os.listdir(dst)))
check("原文件未被硬链接（复制为独立文件）", not any(f.endswith(".partial") for f in os.listdir(dst)))

print("== 5. 清理")
m_copy = next((m for m in j("GET", "/api/models") if m["name"] == "copy-mode-test:q8"), None)
if m_copy:
    j("DELETE", "/api/models/%d" % m_copy["id"])
j("DELETE", "/api/conversations/%s" % cid)
j("POST", "/api/partitions/%d/engine/stop" % p2id)
j("DELETE", "/api/partitions/%d?files=1" % p2id)
shutil.rmtree(p2dir, ignore_errors=True)
check("分区与文件已清理", not os.path.exists(p2dir) and not any(x["id"] == p2id for x in j("GET", "/api/partitions")))

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
