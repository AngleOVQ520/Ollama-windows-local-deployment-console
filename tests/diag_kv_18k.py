"""在用户实际上下文（18432）下实测 KV 缓存量化 f16 vs q8_0 的显存占用，
并顺带确认 Flash Attention 状态。
用法：python tests/diag_kv_18k.py
"""
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
import requests  # noqa: E402

B = "http://127.0.0.1:8848"
LOG = os.path.join(ROOT, "runtime", "logs", "engine-p1.log")
MODEL = "qwen3.5-4b-sompoa-heresy-v2-mtp:q4_k_m"
CTX = int(sys.argv[1]) if len(sys.argv) > 1 else 18432

S = requests.Session()
S.trust_env = False


def j(method, path, **kw):
    r = S.request(method, B + path, timeout=kw.pop("timeout", 300), **kw)
    d = r.json()
    assert d.get("ok"), (path, d)
    return d.get("data")


def wait(pred, timeout=240, step=0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


pid = next(x["id"] for x in j("GET", "/api/partitions") if x["is_default"])
orig = j("GET", "/api/settings")
KEEP_KV = orig["engine"]["kv_cache_type"]
KEEP_CTX = orig["context"]["num_ctx"]


def seg_from(pos):
    with open(LOG, "rb") as f:
        f.seek(pos)
        return f.read().decode("utf-8", errors="replace")


def measure(kv, pos):
    j("PATCH", "/api/settings", json={"engine": {"kv_cache_type": kv, "flash_attention": True},
                                      "context": {"num_ctx": CTX}})
    wait(lambda: [x for x in j("GET", "/api/partitions") if x["is_default"]][0]["engine"]["status"] == "running", 120)
    time.sleep(1)
    pos2 = os.path.getsize(LOG)
    j("POST", "/api/load", json={"partition_id": pid, "model": MODEL, "num_ctx": CTX})
    st = wait(lambda: (lambda s: s if s["status"] in ("loaded", "error") else None)(j("GET", "/api/load")), 300)
    time.sleep(1)
    seg = seg_from(pos2)
    fa = re.findall(r"flash_attn\s*=\s*(\w+)", seg)
    kvb = re.findall(r"CUDA0 KV buffer size\s*=\s*([\d.]+) MiB", seg)
    print("  [%s] loaded=%s flash_attn=%s KV buffer=%s MiB ctx=%s" % (
        kv, st and st["status"], fa[:2], kvb[:3], CTX))
    return {"loaded": bool(st and st["status"] == "loaded"), "fa": fa[:2], "kv_mib": kvb[:3]}


try:
    print("== KV 缓存量化实测 @ num_ctx=%s ==" % CTX)
    a = measure("f16", 0)
    j("POST", "/api/unload")
    time.sleep(1.5)
    b = measure("q8_0", 0)
    out = {"ctx": CTX, "f16": a, "q8_0": b}
    if a["kv_mib"] and b["kv_mib"]:
        x, y = float(a["kv_mib"][0]), float(b["kv_mib"][0])
        out["save_mib"] = round(x - y, 1)
        out["save_pct"] = round((1 - y / x) * 100, 1)
        print("  节省：%.1f MiB（%.1f%%）" % (x - y, out["save_pct"]))
finally:
    j("POST", "/api/unload")
    j("PATCH", "/api/settings", json={"engine": {"kv_cache_type": KEEP_KV},
                                      "context": {"num_ctx": KEEP_CTX}})
    time.sleep(0.5)

with open(os.path.join(ROOT, "runtime", "diag_kv_18k.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("已保存 runtime/diag_kv_18k.json")
