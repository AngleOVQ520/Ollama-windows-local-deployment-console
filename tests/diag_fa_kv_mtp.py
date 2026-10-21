"""诊断三件事：
A. 本机 Flash Attention 是否支持/启用
B. KV 缓存量化（f16 vs q8_0）实际效果（KV 缓冲大小对比）
C. MTP 加速复测（27B IQ2_M 开/关，贪心解码）
用法：python tests/diag_fa_kv_mtp.py
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
MTP_MODEL = "qwen3.8-27b-uncensored:iq2_m"
SMALL = "qwen3.5-4b-sompoa-heresy-v2-mtp:q4_k_m"
CTX = 8192
PROMPTS = ["用三句话介绍长城。", "解释什么是递归，两段以内。", "列出五个中国的世界遗产，每个一句话。"]
OUT = {}

S = requests.Session()
S.trust_env = False


def j(method, path, **kw):
    r = S.request(method, B + path, timeout=kw.pop("timeout", 300), **kw)
    d = r.json()
    assert d.get("ok"), (path, d)
    return d.get("data")


def wait(pred, timeout=360, step=0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


def mark():
    return os.path.getsize(LOG) if os.path.isfile(LOG) else 0


def since(pos):
    if not os.path.isfile(LOG):
        return ""
    with open(LOG, "rb") as f:
        f.seek(pos)
        return f.read().decode("utf-8", errors="replace")


def load(model, ctx=CTX):
    j("POST", "/api/unload")
    time.sleep(1.2)
    j("POST", "/api/load", json={"partition_id": pid, "model": model, "num_ctx": ctx})
    return wait(lambda: (lambda s: s if s["status"] in ("loaded", "error") else None)(j("GET", "/api/load")), 400)


def chat(model, prompt, think="off"):
    conv = j("POST", "/api/conversations", json={})
    rid = j("POST", "/api/conversations/%s/send" % conv["id"],
            json={"content": prompt, "partition_id": pid, "model": model, "think": think,
                  "params": {"temperature": 0, "seed": 42}})["run_id"]
    r = S.get(B + "/api/runs/%s/stream" % rid, stream=True, timeout=600)
    ev, dd = None, None
    for line in r.iter_lines(decode_unicode=True):
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            d = json.loads(line[5:])
            if ev == "done":
                dd = d
                break
    r.close()
    j("DELETE", "/api/conversations/%s" % conv["id"])
    return dd["stats"]


pid = next(x["id"] for x in j("GET", "/api/partitions") if x["is_default"])
orig = j("GET", "/api/settings")
KEEP = {k: orig[k] for k in ("engine", "context", "params", "ui")}

try:
    # ---------- A/B: FA 与 KV ----------
    j("PATCH", "/api/settings", json={"context": {"num_ctx": CTX, "max_output": 200},
                                      "engine": {"flash_attention": True, "kv_cache_type": "f16"}})
    wait(lambda: [x for x in j("GET", "/api/partitions") if x["is_default"]][0]["engine"]["status"] == "running", 90)
    time.sleep(1)

    print("== A. Flash Attention ==")
    pos = mark()
    st = load(SMALL)
    time.sleep(1)
    seg = since(pos)
    fa = re.findall(r"flash_attn\s*=\s*(\w+)", seg)
    fa_disable = re.findall(r"flash_attn.*(?:disabled|not supported|failed)", seg, re.I)
    kv_f16 = re.findall(r"CUDA0 KV buffer size\s*=\s*([\d.]+) MiB", seg)
    types = re.findall(r"type_[kv]\s*=\s*(\w+)", seg)
    print("   flash_attn 取值:", fa[:5], "| 失败/禁用提示:", fa_disable[:2])
    print("   KV 类型声明:", types[:6], "| KV 缓冲:", kv_f16[:3], "MiB")
    OUT["fa"] = {"loaded": bool(st and st["status"] == "loaded"), "flash_attn": fa[:3],
                 "failed": fa_disable[:2], "kv_types": types[:4], "kv_buffer_mib": kv_f16[:3]}

    print("== B. KV 缓存量化 f16 → q8_0 ==")
    j("POST", "/api/unload")
    time.sleep(1)
    j("PATCH", "/api/settings", json={"engine": {"kv_cache_type": "q8_0"}})
    wait(lambda: [x for x in j("GET", "/api/partitions") if x["is_default"]][0]["engine"]["status"] == "running", 90)
    time.sleep(1)
    pos = mark()
    st = load(SMALL)
    time.sleep(1)
    seg = since(pos)
    kv_q8 = re.findall(r"CUDA0 KV buffer size\s*=\s*([\d.]+) MiB", seg)
    types_q8 = re.findall(r"type_[kv]\s*=\s*(\w+)", seg)
    print("   KV 类型声明:", types_q8[:6], "| KV 缓冲:", kv_q8[:3], "MiB")
    OUT["kv"] = {"f16": kv_f16[:3], "q8_0": kv_q8[:3], "q8_types": types_q8[:4]}
    if kv_f16 and kv_q8:
        a, b = float(kv_f16[0]), float(kv_q8[0])
        print("   对比: f16 %.1f MiB → q8_0 %.1f MiB（节省 %.1f%%，约 %.1f MiB）" % (a, b, (1 - b / a) * 100, a - b))
        OUT["kv"]["saving_pct"] = round((1 - b / a) * 100, 1)

    # ---------- C: MTP 复测 ----------
    print("== C. MTP 加速复测 ==")
    j("PATCH", "/api/settings", json={"engine": {"kv_cache_type": "f16"}, "ui": {"mtp_auto": True},
                                      "context": {"num_ctx": 2048, "max_output": 120}})
    wait(lambda: [x for x in j("GET", "/api/partitions") if x["is_default"]][0]["engine"]["status"] == "running", 90)
    time.sleep(1)
    mid = next(x["id"] for x in j("GET", "/api/models") if x["name"] == MTP_MODEL)
    j("PATCH", "/api/models/%d" % mid, json={"mtp_enabled": 1})
    st = load(MTP_MODEL, 2048)
    mtp = wait(lambda: (lambda s: s["mtp"] if s["mtp"] else None)(j("GET", "/api/load")), 40)
    print("   加载:", bool(st), "| MTP 探测:", mtp)
    on_rows = []
    for p in PROMPTS:
        s = chat(MTP_MODEL, p)
        on_rows.append(s["tps"])
        print("     [on] %.2f tok/s (out=%d)" % (s["tps"], s["output_tokens"]))
    # 关闭 MTP（自动重载）
    j("PATCH", "/api/models/%d" % mid, json={"mtp_enabled": 0})
    wait(lambda: (lambda s: s if s["status"] == "loaded" and s["model"] == MTP_MODEL else None)(j("GET", "/api/load")), 400)
    time.sleep(1.5)
    off_rows = []
    for p in PROMPTS:
        s = chat(MTP_MODEL, p)
        off_rows.append(s["tps"])
        print("     [off] %.2f tok/s (out=%d)" % (s["tps"], s["output_tokens"]))
    a = sum(on_rows) / len(on_rows)
    b = sum(off_rows) / len(off_rows)
    print("   MTP 平均 %.2f vs 普通 %.2f → %+.2f tok/s (%+.1f%%)" % (a, b, a - b, (a - b) / b * 100))
    OUT["mtp"] = {"on": on_rows, "off": off_rows, "on_avg": a, "off_avg": b, "pct": (a - b) / b * 100,
                  "detected": bool(mtp and mtp.get("detected")), "evidence": (mtp or {}).get("evidence")}
finally:
    j("PATCH", "/api/settings", json={"engine": {"flash_attention": KEEP["engine"]["flash_attention"],
                                                 "kv_cache_type": KEEP["engine"]["kv_cache_type"],
                                                 "spec_type": KEEP["engine"]["spec_type"]},
                                      "context": {"num_ctx": KEEP["context"]["num_ctx"],
                                                  "max_output": KEEP["context"]["max_output"]},
                                      "ui": {"mtp_auto": KEEP["ui"]["mtp_auto"]}})
    try:
        j("PATCH", "/api/models/%d" % mid, json={"mtp_enabled": 1})
    except Exception:
        pass
    j("POST", "/api/unload")
    time.sleep(1.5)

with open(os.path.join(ROOT, "runtime", "diag_fa_kv_mtp.json"), "w", encoding="utf-8") as f:
    json.dump(OUT, f, ensure_ascii=False, indent=2)
print("\n结果已保存 runtime/diag_fa_kv_mtp.json")
