"""MTP 严格 A/B 对比基准：同一模型（qwen35-9b-defiant-mtp:iq4_nl）、同一组 prompt、
贪心解码（temperature=0 + 固定 seed）、固定 num_ctx，对比 draft-mtp 开/关。
同时抓取引擎 debug 日志中的 draft acceptance（草稿接受率）。
用法：python tests/mtp_ab.py
"""
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
import requests  # noqa: E402

B = "http://127.0.0.1:8848"
ENGINE_LOG = os.path.join(ROOT, "runtime", "logs", "engine-p1.log")
MODEL = "qwen35-9b-defiant-mtp:iq4_nl"
NUM_CTX = 8192
PROMPTS = [
    "用三句话介绍长城。",
    "写一首关于秋天的短诗，四行。",
    "解释什么是递归，两段以内。",
    "列出五个中国的世界遗产，每个一句话。",
    "简单说明什么是光合作用。",
]
PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def j(method, path, **kw):
    r = S.request(method, B + path, timeout=kw.pop("timeout", 300), **kw)
    d = r.json()
    if not d.get("ok"):
        raise AssertionError("%s %s -> %s" % (method, path, str(d)[:200]))
    return d.get("data")


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

# 启动后端（若未运行）
started_here = False
try:
    requests.get(B + "/api/bootstrap", timeout=3)
except Exception:
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

RESULTS = {"spec": {}, "prompts": PROMPTS}
ORIG = {}
pid = next(x["id"] for x in j("GET", "/api/partitions") if x["is_default"])

try:
    # 保存并锁定测试条件
    s0 = j("GET", "/api/settings")
    ORIG = {"num_ctx": s0["context"]["num_ctx"], "spec_type": s0["engine"]["spec_type"],
            "mtp_auto": s0["ui"]["mtp_auto"], "debug": s0["engine"]["debug"],
            "max_output": s0["context"]["max_output"]}
    j("PATCH", "/api/settings", json={"context": {"num_ctx": NUM_CTX, "max_output": 220},
                                      "engine": {"debug": True}, "ui": {"mtp_auto": True}})
    models = j("GET", "/api/models")
    m = next((x for x in models if x["name"] == MODEL), None)
    if not m:
        raise SystemExit("模型未导入，请先运行 tests/mtp_e2e.py")
    RESULTS["model"] = {"name": m["name"], "has_mtp": m.get("has_mtp"),
                        "mtp_tensors": m.get("mtp_tensor_count"), "mtp_layers": m.get("mtp_layers"),
                        "params": m.get("params_label")}

    def run_phase(spec, mtp_auto):
        j("PATCH", "/api/settings", json={"engine": {"spec_type": spec}, "ui": {"mtp_auto": mtp_auto}})
        # spec_type 变更触发引擎重启；等待引擎就绪
        wait(lambda: any(x["engine"]["status"] == "running" for x in j("GET", "/api/partitions") if x["is_default"]), 120)
        j("POST", "/api/unload")
        time.sleep(1.5)
        log_pos = os.path.getsize(ENGINE_LOG) if os.path.isfile(ENGINE_LOG) else 0
        j("POST", "/api/load", json={"partition_id": pid, "model": MODEL, "num_ctx": NUM_CTX})
        st = wait(lambda: (lambda s: s if s["status"] in ("loaded", "error") else None)(j("GET", "/api/load")), 400)
        if not st or st["status"] != "loaded":
            raise RuntimeError("加载失败: %s" % (st or {}))
        time.sleep(1.2)
        mtp_st = wait(lambda: (lambda s: s["mtp"] if s["mtp"] else None)(j("GET", "/api/load")), 30) or {"detected": False, "evidence": "探测超时"}
        run_info = j("GET", "/api/running")
        vram = next((r.get("size_vram") for r in run_info if r["name"] == MODEL), None)
        ctx_loaded = next((r.get("context_length") for r in run_info if r["name"] == MODEL), None)
        rows = []
        conv = j("POST", "/api/conversations", json={})
        for pr in PROMPTS:
            rid = j("POST", "/api/conversations/%s/send" % conv["id"],
                    json={"content": pr, "partition_id": pid, "model": MODEL, "think": "off",
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
            rows.append({"prompt": pr, "tps": ss["tps"], "ttft_ms": ss["ttft_ms"], "out": ss["output_tokens"],
                         "total_ms": ss["total_ms"]})
            print("   [%s] tps=%.2f out=%d ttft=%.0fms" % (pr[:12], ss["tps"], ss["output_tokens"], ss["ttft_ms"]))
        time.sleep(2)
        with open(ENGINE_LOG, "rb") as f:
            f.seek(log_pos)
            log = f.read().decode("utf-8", errors="replace")
        acc = re.findall(r"draft acceptance = ([\d.]+) \(\s*(\d+) accepted /\s*(\d+) generated\), mean len =\s*([\d.]+)", log)
        spec_lines = [l.strip()[:150] for l in log.splitlines()
                      if re.search(r"speculative|adding speculative|draft context|draft acceptance|unused tensor .*nextn", l, re.I)]
        j("DELETE", "/api/conversations/%s" % conv["id"])
        j("POST", "/api/unload")
        time.sleep(1.5)
        mean_tps = sum(x["tps"] for x in rows) / len(rows)
        return {"mtp": mtp_st, "vram": vram, "ctx_loaded": ctx_loaded, "rows": rows, "mean_tps": mean_tps,
                "acceptance": acc, "spec_lines": spec_lines[:14]}

    print("== A. draft-mtp 开启（自动：MTP 模型触发）")
    A = run_phase("", True)
    RESULTS["spec"]["draft-mtp"] = A
    print("   平均 tps=%.2f | vram=%.2fGB | ctx=%s" % (A["mean_tps"], (A["vram"] or 0) / 1e9, A["ctx_loaded"]))
    for l in A["spec_lines"][:6]:
        print("   |", l)
    check("MTP 模式：探测确认启用", A["mtp"]["detected"] is True, A["mtp"]["evidence"])
    check("MTP 模式：日志有 adding speculative implementation 'draft-mtp'",
          any("'draft-mtp'" in l for l in A["spec_lines"]))
    if A["acceptance"]:
        accs = [float(a[0]) for a in A["acceptance"]]
        lens = [float(a[3]) for a in A["acceptance"]]
        A["acceptance_summary"] = {"runs": len(accs), "mean_accept": sum(accs) / len(accs), "mean_len": sum(lens) / len(lens)}
        print("   草稿接受率: %d 次, 平均 %.1f%%, 平均接受长度 %.2f tok" % (
            len(accs), A["acceptance_summary"]["mean_accept"] * 100, A["acceptance_summary"]["mean_len"]))
    else:
        print("   （debug 日志中未捕获 draft acceptance 行）")

    print("== B. MTP 关闭（ui.mtp_auto=false → 无推测解码）")
    Bm = run_phase("", False)
    RESULTS["spec"]["none"] = Bm
    print("   平均 tps=%.2f | vram=%.2fGB" % (Bm["mean_tps"], (Bm["vram"] or 0) / 1e9))
    check("关闭模式：探测确认未启用", Bm["mtp"]["detected"] is False, Bm["mtp"]["evidence"])

    # 输出 token 数应一致（贪心解码）
    outs_a = [x["out"] for x in A["rows"]]
    outs_b = [x["out"] for x in Bm["rows"]]
    check("两轮输出 token 数一致（贪心解码可复现）", outs_a == outs_b, "%s vs %s" % (outs_a, outs_b))

    diff = A["mean_tps"] - Bm["mean_tps"]
    pct = diff / Bm["mean_tps"] * 100 if Bm["mean_tps"] else 0
    RESULTS["compare"] = {"mtp_tps": A["mean_tps"], "plain_tps": Bm["mean_tps"], "diff": diff, "pct": pct}
    print("== 对比：MTP %.2f tok/s vs 普通 %.2f tok/s → %+.2f (%+.1f%%)" % (A["mean_tps"], Bm["mean_tps"], diff, pct))

    print("== C. 强制 draft-mtp 对无 MTP 模型的影响（qwen3.5:2b）")
    j("PATCH", "/api/settings", json={"engine": {"spec_type": "draft-mtp"}})
    wait(lambda: any(x["engine"]["status"] in ("running", "stopped") for x in j("GET", "/api/partitions") if x["is_default"]), 60)
    time.sleep(1)
    j("POST", "/api/load", json={"partition_id": pid, "model": "qwen3.5:2b", "num_ctx": NUM_CTX})
    st2 = wait(lambda: (lambda s: s if s["status"] in ("loaded", "error") else None)(j("GET", "/api/load")), 300)
    # 预期：llama.cpp 直接拒绝（context type MTP requested but model doesn't contain MTP layers）
    check("无 MTP 模型 + 强制 draft-mtp：被引擎拒绝（证明必须按模型能力自动启用）",
          st2 and st2["status"] == "error" and "MTP" in (st2.get("error") or ""), st2 and (st2["status"], (st2.get("error") or "")[:90]))
    RESULTS["forced_on_non_mtp"] = {"load": st2["status"] if st2 else "?", "error": (st2 or {}).get("error", "")}

    # 恢复用户设置
    j("PATCH", "/api/settings", json={"context": {"num_ctx": ORIG["num_ctx"], "max_output": ORIG["max_output"]},
                                      "engine": {"spec_type": ORIG["spec_type"], "debug": ORIG["debug"]},
                                      "ui": {"mtp_auto": ORIG["mtp_auto"]}})
    check("测试后设置已恢复", j("GET", "/api/settings")["context"]["num_ctx"] == ORIG["num_ctx"])
finally:
    if started_here:
        try:
            requests.post(B + "/api/app/shutdown", timeout=5)
        except Exception:
            pass

with open(os.path.join(ROOT, "runtime", "mtp_ab_results.json"), "w", encoding="utf-8") as f:
    json.dump(RESULTS, f, ensure_ascii=False, indent=2)
print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for x in FAIL:
    print("  失败：", x)
sys.exit(1 if FAIL else 0)
