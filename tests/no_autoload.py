"""验证：启动后端时不自动加载任何模型（显存零占用），直到用户自己选择模型。
用法：python tests/no_autoload.py
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
import requests  # noqa: E402

B = "http://127.0.0.1:8848"
PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def start(keep_log=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    out = open(keep_log, "w", encoding="utf-8") if keep_log else subprocess.DEVNULL
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "app-cn.py"), "--no-browser", "--plain"],
                         cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    for _ in range(140):
        try:
            if requests.get(B + "/api/bootstrap", timeout=2).json()["data"]["app"]["ready"]:
                return p
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit("启动失败")


def stop(p):
    try:
        requests.post(B + "/api/app/shutdown", timeout=5)
    except Exception:
        pass
    try:
        p.wait(timeout=20)
    except Exception:
        p.terminate()
    time.sleep(1.5)


# 1) 先把开关关掉（这是本次需求），并确认落库
p = start(os.path.join(ROOT, "runtime", "logs", "no_autoload_1.log"))
try:
    r = requests.patch(B + "/api/settings", json={"chat": {"auto_load_last": False}}, timeout=10).json()["data"]
    check("开关已关闭并落库", r["settings"]["chat"]["auto_load_last"] is False)
    check("上次使用的模型仍被记住（便于手动一键加载）", r["settings"]["chat"]["last_model"] != "")
    # 人为先加载一个模型，制造"上次有模型驻留"的状态
    pid, name = r["settings"]["chat"]["last_model"].split("|", 1)
    requests.post(B + "/api/load", json={"partition_id": int(pid), "model": name}, timeout=30)
    for _ in range(240):
        if requests.get(B + "/api/load", timeout=3).json()["data"]["status"] == "loaded":
            break
        time.sleep(0.5)
    check("先手动加载模型（构造场景）", requests.get(B + "/api/load", timeout=3).json()["data"]["model"] == name,
          requests.get(B + "/api/running", timeout=5).json()["data"])
finally:
    stop(p)

# 2) 重启后：不应自动加载
print("== 重启后端 ==")
p = start(os.path.join(ROOT, "runtime", "logs", "no_autoload_2.log"))
try:
    time.sleep(6)  # 给自动加载留出充足时间（老逻辑会在 3 秒内加载完）
    st = requests.get(B + "/api/load", timeout=5).json()["data"]
    running = requests.get(B + "/api/running", timeout=5).json()["data"]
    check("启动后模型状态为未加载", st["status"] == "idle", (st["status"], st["model"]))
    check("没有模型驻留显存", len(running) == 0, running)
    check("引擎本身已就绪（可随时加载）", requests.get(B + "/api/partitions", timeout=5).json()["data"][0]["engine"]["status"] == "running")
    log_now = open(os.path.join(ROOT, "runtime", "logs", "no_autoload_2.log"), encoding="utf-8").read()
    check("重启后启动日志里没有任何加载模型的记录", "自动加载上次模型" not in log_now and "loader:" not in log_now,
          [l for l in log_now.splitlines() if "loader" in l][:2])
    # 3) 用户手动选择后可以正常加载
    pid, name = requests.get(B + "/api/settings", timeout=5).json()["data"]["chat"]["last_model"].split("|", 1)
    requests.post(B + "/api/load", json={"partition_id": int(pid), "model": name}, timeout=30)
    ok = False
    for _ in range(240):
        if requests.get(B + "/api/load", timeout=3).json()["data"]["status"] == "loaded":
            ok = True
            break
        time.sleep(0.5)
    check("手动选择模型后可正常加载", ok, requests.get(B + "/api/load", timeout=5).json()["data"]["model"])
finally:
    stop(p)

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
