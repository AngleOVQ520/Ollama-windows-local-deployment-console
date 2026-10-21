"""MTP 端到端实测：
1. 导入 IQ4_NL MTP 模型
2. 加载并抓取引擎日志中的 speculative 证据
3. 开/关对比：MTP 模型自身（有无 MTP 生效由引擎决定，这里实测"生效时的表现"）
4. 采集 draft acceptance 与 tps
用法：python tests/mtp_e2e.py
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
GGUF = os.path.join(ROOT, "Qwen3.5-9B-The-Defiant-Fable-Uncnr-Heretic-NEO-MAX-MTP-IQ4_NL.gguf")
ENGINE_LOG = os.path.join(ROOT, "runtime", "logs", "engine-p1.log")
PASS, FAIL = [], []
RESULTS = {"import": {}, "load": {}, "bench": [], "mtp": {}, "ui_note": ""}


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def j(method, path, **kw):
    r = S.request(method, B + path, timeout=kw.pop("timeout", 300), **kw)
    d = r.json()
    if not d.get("ok"):
        raise AssertionError("%s %s -> %s" % (method, path, str(d)[:300]))
    return d.get("data")


def wait(pred, timeout=300, step=0.3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


S = requests.Session()
S.trust_env = False

# 确保后端在运行
try:
    requests.get(B + "/api/bootstrap", timeout=3)
    started_here = False
except Exception:
    import subprocess
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    p_proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "app-cn.py"), "--no-browser", "--plain"],
                              cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    started_here = True
    for _ in range(120):
        try:
            if requests.get(B + "/api/bootstrap", timeout=2).json()["data"]["app"]["ready"]:
                break
        except Exception:
            pass
        time.sleep(0.5)

try:
    print("== 1. 导入 MTP 模型（硬链接）")
    parts = j("GET", "/api/partitions")
    pid = next(x["id"] for x in parts if x["is_default"])
    info = j("POST", "/api/gguf/inspect", json={"path": GGUF})
    check("GGUF 解析成功", info["architecture"] == "qwen35", "arch=%s 张量=%s" % (info["architecture"], info["tensor_count"]))
    check("MTP 识别：has_mtp=True", info["has_mtp"] is True, "mtp_tensor_count=%s mtp_layers=%s" % (info.get("mtp_tensor_count"), info.get("mtp_layers")))
    check("MTP 层数声明键被读出", info.get("mtp_layers") == 1, info.get("mtp_metadata_keys"))
    RESULTS["import"] = {k: info.get(k) for k in ("architecture", "tensor_count", "mtp_tensor_count", "mtp_layers", "has_mtp", "file_size", "params_label")}
    print("   解析结果:", json.dumps(RESULTS["import"], ensure_ascii=False))

    existing = [m for m in j("GET", "/api/models") if m["name"] == "qwen35-9b-defiant-mtp:iq4_nl"]
    if not existing:
        job = j("POST", "/api/jobs/import", json={"partition_id": pid, "path": GGUF,
                                                   "name": "qwen35-9b-defiant-mtp:iq4_nl", "remark": "MTP 实测用"})
        done = wait(lambda: next((x for x in j("GET", "/api/jobs") if x["id"] == job["id"] and x["status"] in ("done", "error")), None), 300, 1)
        check("导入完成", done and done["status"] == "done", done and done["message"])
    m = next(m for m in j("GET", "/api/models") if m["name"] == "qwen35-9b-defiant-mtp:iq4_nl")
    check("模型列表 MTP 标记", m.get("has_mtp") == 1 and m.get("mtp_tensor_count", 0) > 0,
          "has_mtp=%s tensors=%s" % (m.get("has_mtp"), m.get("mtp_tensor_count")))

    print("== 2. 加载（记录加载前日志位置）")
    log_pos = os.path.getsize(ENGINE_LOG) if os.path.isfile(ENGINE_LOG) else 0
    j("POST", "/api/unload")
    time.sleep(1.5)
    j("POST", "/api/load", json={"partition_id": pid, "model": m["name"]})
    st = wait(lambda: (lambda s: s if s["status"] in ("loaded", "error") else None)(j("GET", "/api/load")), 400)
    check("模型加载成功", st and st["status"] == "loaded", st and (st["num_ctx"], st["error"]))
    RESULTS["load"] = {"load_ms": st["load_ms"], "num_ctx": st["num_ctx"], "size_vram": st["size_vram"]}

    print("== 3. 等待 MTP 探测（20 秒窗口）")
    mtp_st = wait(lambda: (lambda s: s["mtp"] if s["mtp"] else None)(j("GET", "/api/load")), 40)
    RESULTS["mtp"] = mtp_st or {"detected": False, "evidence": "探测超时"}
    check("MTP 探测有结论", mtp_st is not None, RESULTS["mtp"])
    check("MTP 生效判定", mtp_st and mtp_st["detected"] is True, RESULTS["mtp"]["evidence"])

    print("== 4. 引擎日志原文取证")
    time.sleep(1)
    with open(ENGINE_LOG, "rb") as f:
        f.seek(log_pos)
        new_log = f.read().decode("utf-8", errors="replace")
    spec_lines = [l.strip() for l in new_log.splitlines()
                  if re.search(r"speculative|draft|nextn|mtp", l, re.I) and "llama_server" not in l]
    RESULTS["log_lines"] = spec_lines[:25]
    for l in spec_lines[:10]:
        print("   |", l[:150])
    check("日志出现 speculative/MTP 相关行", len(spec_lines) > 0, "%d 行" % len(spec_lines))

    print("== 5. 生成测试（短对话验证统计行 + 采集接受率）")
    conv = j("POST", "/api/conversations", json={})
    rid = j("POST", "/api/conversations/%s/send" % conv["id"],
            json={"content": "用三句话介绍长城。", "partition_id": pid, "model": m["name"], "think": "off"})["run_id"]
    out = {"content": ""}
    done_evt = None
    r = S.get(B + "/api/runs/%s/stream" % rid, stream=True, timeout=600)
    ev = None
    for line in r.iter_lines(decode_unicode=True):
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            d = json.loads(line[5:])
            if ev == "content":
                out["content"] += d["t"]
            if ev == "done":
                done_evt = d
                break
    r.close()
    s = done_evt["stats"]
    check("生成成功", done_evt["status"] == "ok" and out["content"].strip(), out["content"][:60].replace("\n", " "))
    print("   统计: 输入=%s 输出=%s tps=%.1f ttft=%.0fms" % (s["input_tokens"], s["output_tokens"], s["tps"], s["ttft_ms"]))
    RESULTS["bench"].append({"prompt": "用三句话介绍长城。", "stats": {k: s.get(k) for k in ("input_tokens", "output_tokens", "tps", "ttft_ms", "total_ms")}})
    time.sleep(1)
    with open(ENGINE_LOG, "rb") as f:
        f.seek(log_pos)
        log2 = f.read().decode("utf-8", errors="replace")
    acc = re.findall(r"draft acceptance = ([\d.]+) \((\d+) accepted / (\d+) generated\), mean len = ([\d.]+)", log2)
    RESULTS["acceptance"] = acc
    if acc:
        print("   草稿接受率:", acc[-5:])
        check("draft acceptance 统计出现（推测解码确实在跑）", len(acc) > 0, acc[-1])

    # 多轮采集
    print("== 6. 多轮基准（3 轮生成类 prompt）")
    for prompt in ["写一首关于秋天的短诗，四行。", "解释什么是递归，两段以内。", "列出五个中国的世界遗产，每个一句话。"]:
        rid = j("POST", "/api/conversations/%s/send" % conv["id"],
                json={"content": prompt, "partition_id": pid, "model": m["name"], "think": "off"})["run_id"]
        r = S.get(B + "/api/runs/%s/stream" % rid, stream=True, timeout=600)
        ev, content, dd = None, "", None
        for line in r.iter_lines(decode_unicode=True):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                d = json.loads(line[5:])
                if ev == "content":
                    content += d["t"]
                if ev == "done":
                    dd = d
                    break
        r.close()
        ss = dd["stats"]
        RESULTS["bench"].append({"prompt": prompt, "stats": {k: ss.get(k) for k in ("input_tokens", "output_tokens", "tps", "ttft_ms", "total_ms")}})
        print("   [%s] tps=%.1f out=%s ttft=%.0fms" % (prompt[:14], ss["tps"], ss["output_tokens"], ss["ttft_ms"]))
    time.sleep(1.5)
    with open(ENGINE_LOG, "rb") as f:
        f.seek(log_pos)
        log3 = f.read().decode("utf-8", errors="replace")
    acc_all = re.findall(r"draft acceptance = ([\d.]+) \((\d+) accepted / (\d+) generated\), mean len = ([\d.]+)", log3)
    RESULTS["acceptance"] = acc_all
    if acc_all:
        accs = [float(a[0]) for a in acc_all]
        lens = [float(a[3]) for a in acc_all]
        RESULTS["acceptance_summary"] = {"runs": len(accs), "mean_accept": sum(accs) / len(accs), "mean_len": sum(lens) / len(lens)}
        print("   接受率汇总: %d 次验证, 平均接受率 %.1f%%, 平均接受长度 %.2f tokens" % (
            len(accs), RESULTS["acceptance_summary"]["mean_accept"] * 100, RESULTS["acceptance_summary"]["mean_len"]))

    # 清理测试对话
    j("DELETE", "/api/conversations/%s" % conv["id"])
finally:
    print("== 清理：卸载模型")
    try:
        j("POST", "/api/unload")
    except Exception:
        pass
    time.sleep(2)
    try:
        st = requests.get(B + "/api/load", timeout=5).json()["data"]
        run = requests.get(B + "/api/running", timeout=5).json()["data"]
        check("模型已卸载", st["status"] == "idle" and len(run) == 0, (st["status"], run))
        RESULTS["cleanup"] = {"status": st["status"], "running": len(run)}
    except Exception as e:
        print("清理检查失败：", e)
    if started_here:
        try:
            requests.post(B + "/api/app/shutdown", timeout=5)
        except Exception:
            pass

with open(os.path.join(ROOT, "runtime", "mtp_e2e_results.json"), "w", encoding="utf-8") as f:
    json.dump(RESULTS, f, ensure_ascii=False, indent=2)
print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for x in FAIL:
    print("  失败：", x)
sys.exit(1 if FAIL else 0)
