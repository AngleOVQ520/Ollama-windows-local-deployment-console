"""对话 / 加载 / 停止 / 思考预算 集成测试（真实模型）。用法：python tests/smoke_chat.py <partition_id> <model> [base]"""
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runtime", "pylib"))
import requests

PID = int(sys.argv[1])
MODEL = sys.argv[2]
B = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8848"
S = requests.Session()
S.trust_env = False


def j(method, path, **kw):
    r = S.request(method, B + path, timeout=kw.pop("timeout", 120), **kw)
    d = r.json()
    if not d.get("ok"):
        raise AssertionError("%s %s -> %s" % (method, path, d))
    return d.get("data")


def wait_load(timeout=180):
    t0 = time.time()
    seen = []
    while time.time() - t0 < timeout:
        st = j("GET", "/api/load")
        seen.append(round(st["progress"]))
        if st["status"] in ("loaded", "error"):
            return st, seen
        time.sleep(0.2)
    raise AssertionError("load timeout")


def stream(run_id, stop_after=None, cid=None):
    r = S.get(B + "/api/runs/%s/stream" % run_id, stream=True, timeout=600)
    ev = None
    out = {"thinking": "", "content": "", "events": []}
    t0 = time.time()
    for line in r.iter_lines(decode_unicode=True):
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            d = json.loads(line[5:])
            out["events"].append(ev)
            if ev == "thinking":
                out["thinking"] += d["t"]
            elif ev == "content":
                out["content"] += d["t"]
            elif ev == "notice":
                print("   notice:", d["text"])
            elif ev == "done":
                out["done"] = d
                break
            if stop_after and time.time() - t0 > stop_after and cid:
                j("POST", "/api/conversations/%s/stop" % cid)
                stop_after = None
    r.close()
    return out


def chat(cid, content, think="off", ctxo=None, stop_after=None):
    d = j("POST", "/api/conversations/%s/send" % cid, json={"content": content, "partition_id": PID, "model": MODEL,
                                                             "think": think, "context": ctxo or {}})
    return stream(d["run_id"], stop_after=stop_after, cid=cid)


print("== select & load", MODEL)
j("POST", "/api/load", json={"partition_id": PID, "model": MODEL})
st, seen = wait_load()
print("  status=%s load=%.1fs ctx=%s vram=%s progress samples=%s" % (st["status"], st["load_ms"] / 1000, st["num_ctx"], st["size_vram"], sorted(set(seen))[:20]))
assert st["status"] == "loaded", st

conv = j("POST", "/api/conversations", json={})
cid = conv["id"]
print("== chat think=off")
o = chat(cid, "用一句话介绍你自己")
s = o["done"]["stats"]
print("  content:", o["content"][:120].replace("\n", " "))
print("  stats: in=%s out=%s tps=%.1f ttft=%.0fms think=%.0fms status=%s" % (s["input_tokens"], s["output_tokens"], s["tps"], s["ttft_ms"], s["think_ms"], o["done"]["status"]))
assert o["content"] and o["done"]["status"] == "ok"

print("== chat think=mini (budget)")
o = chat(cid, "17*23 等于多少？", think="mini")
s = o["done"]["stats"]
print("  thinking len=%d content: %s" % (len(o["thinking"]), o["content"][:160].replace("\n", " ")))
print("  stats: in=%s out=%s think_tok=%s tps=%.1f ttft=%.0fms think=%.0fms budget_hit=%s" % (s["input_tokens"], s["output_tokens"], s["thinking_tokens"], s["tps"], s["ttft_ms"], s["think_ms"], s["budget_hit"]))
assert o["content"], "no content after budget"

print("== chat think=medium")
o = chat(cid, "简单解释一下勾股定理，并给出公式", think="medium")
s = o["done"]["stats"]
print("  thinking len=%d content: %s" % (len(o["thinking"]), o["content"][:160].replace("\n", " ")))
print("  stats: out=%s think_tok=%s think=%.0fms budget_hit=%s" % (s["output_tokens"], s["thinking_tokens"], s["think_ms"], s["budget_hit"]))

print("== stop mid-generation")
o = chat(cid, "写一篇 1500 字的文章介绍长城的历史", stop_after=1.5)
print("  status=%s content_len=%d out=%s" % (o["done"]["status"], len(o["content"]), o["done"]["stats"]["output_tokens"]))
assert o["done"]["status"] == "stopped"

print("== conversation persisted")
c = j("GET", "/api/conversations/%s" % cid)
print("  title=%s messages=%d" % (c["title"], len(c["messages"])))
print("== usage")
o = j("GET", "/api/usage/overview")
print("  today:", o["today"])
