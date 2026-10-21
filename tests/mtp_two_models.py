"""两个模型的 MTP 开/关速度实测：
1. qwen35-9b-defiant-mtp:iq4_nl（带 nextn 声明 + 原生张量 → MTP 应能启用）
2. sorc/qwen3.5-claude-4.6-opus:2b（有 mtp.* 张量但缺声明键 → 预期无法启用）
贪心解码（temperature=0, seed=42）、固定 num_ctx=8192，输出可复现。
用法：python tests/mtp_two_models.py
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
ENGINE_LOG = os.path.join(ROOT, "runtime", "logs", "engine-p1.log")
NUM_CTX = 8192
PROMPTS = [
    "用三句话介绍长城。",
    "写一首关于秋天的短诗，四行。",
    "解释什么是递归，两段以内。",
    "列出五个中国的世界遗产，每个一句话。",
    "简单说明什么是光合作用。",
]
MODELS = [
    {"name": "qwen35-9b-defiant-mtp:iq4_nl", "label": "IQ4_NL 9B MTP"},
    {"name": "sorc/qwen3.5-claude-4.6-opus:2b", "label": "sorc opus 2B"},
]


def wait(pred, timeout=420, step=0.4):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


S = requests.Session()
S.trust_env = False


def j(method, path, **kw):
    r = S.request(method, B + path, timeout=kw.pop("timeout", 300), **kw)
    d = r.json()
    if not d.get("ok"):
        raise AssertionError("%s %s -> %s" % (method, path, str(d)[:200]))
    return d.get("data")


def bench(model, label):
    """加载 + 5 prompt 贪心解码，返回结果 dict。"""
    log_pos = os.path.getsize(ENGINE_LOG) if os.path.isfile(ENGINE_LOG) else 0
    j("POST", "/api/unload")
    time.sleep(1.5)
    j("POST", "/api/load", json={"partition_id": pid, "model": model, "num_ctx": NUM_CTX})
    st = wait(lambda: (lambda s: s if s["status"] in ("loaded", "error") else None)(j("GET", "/api/load")), 400)
    if not st or st["status"] != "loaded":
        return {"error": (st or {}).get("error", "加载超时"), "loaded": False}
    time.sleep(1.2)
    mtp_st = wait(lambda: (lambda s: s["mtp"] if s["mtp"] else None)(j("GET", "/api/load")), 30) or {"detected": False, "evidence": "探测超时"}
    run = j("GET", "/api/running")
    vram = next((r.get("size_vram") for r in run if r["name"] == model), None)
    rows = []
    conv = j("POST", "/api/conversations", json={})
    for pr in PROMPTS:
        rid = j("POST", "/api/conversations/%s/send" % conv["id"],
                json={"content": pr, "partition_id": pid, "model": model, "think": "off",
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
        ss = dd["stats"]
        rows.append({"prompt": pr, "tps": ss["tps"], "out": ss["output_tokens"],
                     "ttft_ms": ss["ttft_ms"], "total_ms": ss["total_ms"]})
        print("      [%s] tps=%.2f out=%d" % (pr[:12], ss["tps"], ss["output_tokens"]))
    time.sleep(2)
    with open(ENGINE_LOG, "rb") as f:
        f.seek(log_pos)
        log = f.read().decode("utf-8", errors="replace")
    acc = re.findall(r"draft acceptance = ([\d.]+) \(\s*(\d+) accepted /\s*(\d+) generated\), mean len =\s*([\d.]+)", log)
    spec_hit = "speculative decoding context initialized" in log
    spec_fail = "no implementations specified" in log
    j("DELETE", "/api/conversations/%s" % conv["id"])
    mean = sum(x["tps"] for x in rows) / len(rows)
    return {"loaded": True, "mtp": mtp_st, "vram": vram, "rows": rows, "mean_tps": mean,
            "acceptance": acc, "spec_hit": spec_hit, "spec_fail": spec_fail}


# 确保后端在运行
started_here = False
try:
    requests.get(B + "/api/bootstrap", timeout=3)
except Exception:
    import subprocess
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "app-cn.py"), "--no-browser", "--plain"],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    started_here = True
    for _ in range(140):
        try:
            if requests.get(B + "/api/bootstrap", timeout=2).json()["data"]["app"]["ready"]:
                break
        except Exception:
            pass
        time.sleep(0.5)

RESULTS = {}
ORIG = {}
try:
    s0 = j("GET", "/api/settings")
    ORIG = {"num_ctx": s0["context"]["num_ctx"], "max_output": s0["context"]["max_output"],
            "spec_type": s0["engine"]["spec_type"], "mtp_auto": s0["ui"]["mtp_auto"]}
    j("PATCH", "/api/settings", json={"context": {"num_ctx": NUM_CTX, "max_output": 220}, "ui": {"mtp_auto": True}})
    pid = next(x["id"] for x in j("GET", "/api/partitions") if x["is_default"])

    for md in MODELS:
        name, label = md["name"], md["label"]
        print("\n======== %s (%s) ========" % (label, name))
        R = {"label": label}
        # --- MTP 开 ---
        print("  -- MTP 开 --")
        R["on"] = bench(name, label)
        if R["on"]["loaded"]:
            print("     平均 tps=%.2f | MTP=%s | 接受率样本=%d" % (
                R["on"]["mean_tps"], R["on"]["mtp"]["detected"], len(R["on"]["acceptance"])))
        else:
            print("     加载失败:", R["on"]["error"])
        # --- MTP 关 ---
        print("  -- MTP 关 --")
        j("PATCH", "/api/settings", json={"ui": {"mtp_auto": False}})
        time.sleep(0.5)
        R["off"] = bench(name, label)
        if R["off"]["loaded"]:
            print("     平均 tps=%.2f | MTP=%s" % (R["off"]["mean_tps"], R["off"]["mtp"]["detected"]))
        j("PATCH", "/api/settings", json={"ui": {"mtp_auto": True}})
        if R["on"]["loaded"] and R["off"]["loaded"]:
            outs_on = [x["out"] for x in R["on"]["rows"]]
            outs_off = [x["out"] for x in R["off"]["rows"]]
            R["reproducible"] = outs_on == outs_off
            R["diff"] = R["on"]["mean_tps"] - R["off"]["mean_tps"]
            R["pct"] = R["diff"] / R["off"]["mean_tps"] * 100 if R["off"]["mean_tps"] else 0
            print("     对比: %+.2f tok/s (%+.1f%%) | 输出一致=%s" % (R["diff"], R["pct"], R["reproducible"]))
        RESULTS[label] = R
finally:
    j("PATCH", "/api/settings", json={"context": {"num_ctx": ORIG.get("num_ctx", 18432),
                                                  "max_output": ORIG.get("max_output", 4096)},
                                      "ui": {"mtp_auto": ORIG.get("mtp_auto", True)},
                                      "engine": {"spec_type": ORIG.get("spec_type", "")}})
    j("POST", "/api/unload")
    time.sleep(1.5)
    if started_here:
        try:
            requests.post(B + "/api/app/shutdown", timeout=5)
        except Exception:
            pass

with open(os.path.join(ROOT, "runtime", "mtp_two_models.json"), "w", encoding="utf-8") as f:
    json.dump(RESULTS, f, ensure_ascii=False, indent=2)
print("\n=== 汇总 ===")
for label, R in RESULTS.items():
    if R.get("on", {}).get("loaded") and R.get("off", {}).get("loaded"):
        print("%-16s MTP=%.2f  普通=%.2f  提升=%+.1f%%  接受率=%s" % (
            label, R["on"]["mean_tps"], R["off"]["mean_tps"], R["pct"],
            ("%.0f%%" % (sum(float(a[0]) for a in R["on"]["acceptance"]) / len(R["on"]["acceptance"]) * 100)) if R["on"]["acceptance"] else "N/A"))
    else:
        err = (R.get("on") or {}).get("error") or (R.get("off") or {}).get("error") or "?"
        print("%-16s MTP 无法启用: %s" % (label, err[:90]))
