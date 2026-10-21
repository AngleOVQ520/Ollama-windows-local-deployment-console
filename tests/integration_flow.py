"""端到端集成测试（真实模型）：GGUF 导入 → 加载中切换 → 对话中切换 → API 调用 → 统计。
需先运行 app-cn.py。用法：python tests/integration_flow.py [gguf_path] [base_url]
"""
import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
import requests  # noqa: E402

GGUF = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q8_0.gguf")
B = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8848"
S = requests.Session()
S.trust_env = False
PASS, FAIL = [], []


def j(method, path, **kw):
    r = S.request(method, B + path, timeout=kw.pop("timeout", 120), **kw)
    d = r.json()
    if not d.get("ok"):
        raise AssertionError("%s %s -> %s" % (method, path, d))
    return d.get("data")


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def wait(pred, timeout=300, step=0.2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


def running_names():
    return [r["name"] for r in j("GET", "/api/running")]


pid = next(p["id"] for p in j("GET", "/api/partitions") if p["is_default"])
print("== 1. 导入 GGUF：", GGUF)
info = j("POST", "/api/gguf/inspect", json={"path": GGUF})
check("GGUF 解析上下文长度", info["context_length"] == 262144, info["context_length"])
check("GGUF 解析参数量", info["param_count"] and info["param_count"] > 4e9, info["params_label"])
NAME4 = "qwen3.5-4b-uncensored:q8_0"
existing = [m for m in j("GET", "/api/models") if m["name"] == NAME4]
if not existing:
    job = j("POST", "/api/jobs/import", json={"partition_id": pid, "path": GGUF, "name": NAME4, "remark": "Qwen3.5 4B 无审查版"})
    done = wait(lambda: next((x for x in j("GET", "/api/jobs") if x["id"] == job["id"] and x["status"] in ("done", "error")), None), 300, 1)
    check("GGUF 导入完成", done and done["status"] == "done", done and done["message"])
m4 = next(m for m in j("GET", "/api/models") if m["name"] == NAME4)
check("导入模型元数据", m4["context_length"] == 262144 and m4["params"] and m4["display_category"].startswith("千问"),
      (m4["params_label"], m4["context_length"], m4["display_category"], m4["quant"]))
blob = os.path.join(ROOT, "models", "default", "blobs")
check("模型文件位于项目 models 目录", any(os.path.getsize(os.path.join(blob, f)) == os.path.getsize(GGUF) for f in os.listdir(blob)))
NAME2 = "qwen3.5:2b"

print("== 2. 加载中切换模型（应中断旧加载并加载新模型）")
j("POST", "/api/unload")
time.sleep(1.5)
j("POST", "/api/load", json={"partition_id": pid, "model": NAME2})
wait(lambda: j("GET", "/api/load")["progress"] > 2, 30, 0.1)
mid = j("GET", "/api/load")
print("   切换时 2b 状态:", mid["status"], "%.0f%%" % mid["progress"])
j("POST", "/api/load", json={"partition_id": pid, "model": NAME4})
st = wait(lambda: (lambda s: s if s["status"] in ("loaded", "error") else None)(j("GET", "/api/load")), 300)
check("最终加载的是新模型", st and st["model"] == NAME4 and st["status"] == "loaded", st and (st["model"], st["status"], st["error"]))
time.sleep(1)
rn = running_names()
check("旧模型未驻留", NAME2 not in rn, rn)

print("== 3. 对话（4B，思考 low）")
cid = j("POST", "/api/conversations", json={})["id"]


def stream(run_id, on_first=None):
    r = S.get(B + "/api/runs/%s/stream" % run_id, stream=True, timeout=600)
    ev, out, fired = None, {"content": "", "thinking": ""}, False
    for line in r.iter_lines(decode_unicode=True):
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            d = json.loads(line[5:])
            if ev in ("content", "thinking"):
                out[ev] += d["t"]
                if on_first and not fired:
                    fired = True
                    on_first()
            if ev == "done":
                out["done"] = d
                break
    r.close()
    return out


rid = j("POST", "/api/conversations/%s/send" % cid, json={"content": "用 Python 写一个快速排序函数，并给出时间复杂度公式（LaTeX）", "partition_id": pid, "model": NAME4, "think": "low"})["run_id"]
o = stream(rid)
s = o["done"]["stats"]
check("4B 对话成功", o["done"]["status"] == "ok" and "def" in o["content"], "out=%s tps=%.1f ttft=%.0fms think=%.0fms" % (s["output_tokens"], s["tps"], s["ttft_ms"], s["think_ms"]))
check("统计字段齐全", all(k in s for k in ("input_tokens", "output_tokens", "tps", "think_ms", "ttft_ms")))

print("== 4. 对话中切换模型（应等输出完成后再切换）")
switched = {}


def switch():
    switched["st"] = j("POST", "/api/load", json={"partition_id": pid, "model": NAME2})


rid = j("POST", "/api/conversations/%s/send" % cid, json={"content": "写一段 300 字左右的文字介绍黄山", "partition_id": pid, "model": NAME4, "think": "off"})["run_id"]
o = stream(rid, on_first=lambda: threading.Thread(target=switch).start())
time.sleep(0.3)
check("输出期间记为待切换", switched.get("st", {}).get("pending", {}) and switched["st"]["pending"]["model"] == NAME2, switched.get("st", {}).get("pending"))
check("当前回复由原模型完整输出", o["done"]["status"] == "ok" and o["done"]["stats"]["model"] == NAME4 and len(o["content"]) > 100, len(o["content"]))
st = wait(lambda: (lambda s: s if s["model"] == NAME2 and s["status"] in ("loaded", "error") else None)(j("GET", "/api/load")), 300)
check("输出完成后自动加载新模型", st and st["status"] == "loaded", st and st["status"])

print("== 5. 对话中切换 + 手动停止（停止后立即切换）")
rid = j("POST", "/api/conversations/%s/send" % cid, json={"content": "写一篇 2000 字的小说", "partition_id": pid, "model": NAME2, "think": "off"})["run_id"]


def stop_soon():
    j("POST", "/api/load", json={"partition_id": pid, "model": NAME4})
    time.sleep(0.8)
    j("POST", "/api/conversations/%s/stop" % cid)


o = stream(rid, on_first=lambda: threading.Thread(target=stop_soon).start())
check("手动停止", o["done"]["status"] == "stopped", o["done"]["stats"].get("output_tokens"))
check("停止后统计有输出 tokens", o["done"]["stats"]["output_tokens"] > 0, o["done"]["stats"]["output_tokens"])
st = wait(lambda: (lambda s: s if s["model"] == NAME4 and s["status"] in ("loaded", "error") else None)(j("GET", "/api/load")), 300)
check("停止后切换到新模型", st and st["status"] == "loaded")

print("== 6. OpenAI 兼容 API")
r = S.post("http://127.0.0.1:8849/v1/chat/completions", json={"model": NAME4, "messages": [{"role": "user", "content": "只回复：OK"}], "max_tokens": 200, "reasoning_effort": "none"}, timeout=300).json()
check("API /v1/chat/completions", "choices" in r and r["choices"][0]["message"]["content"], str(r)[:200])
r = S.post("http://127.0.0.1:8849/api/chat", json={"model": NAME4, "messages": [{"role": "user", "content": "只回复：OK"}], "stream": False, "think": False}, timeout=300).json()
check("API /api/chat", r.get("message", {}).get("content"), str(r)[:120])

print("== 7. 用量统计")
o = j("GET", "/api/usage/overview")
rep = j("GET", "/api/usage/report?days=7")
check("统计包含 API 调用", any(x["source"] == "api" for x in rep["by_source"]), rep["by_source"])
check("今日调用计数", o["today"]["calls"] >= 4, o["today"]["calls"])

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
