"""按用户的真实方式启动：python app-cn.py（自动打开浏览器 + 全屏仪表盘），验证后关闭。
用法：python tests/launch_real.py
"""
import os
import re
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "devlib"))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
os.environ["TEMP"] = os.environ["TMP"] = os.path.join(ROOT, "runtime", "tmp")
from winpty import PtyProcess  # noqa: E402
import requests  # noqa: E402

env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
env.pop("TERM", None)
proc = PtyProcess.spawn([sys.executable, "-u", os.path.join(ROOT, "app-cn.py")], env=env, dimensions=(44, 150))
buf, stop = [], threading.Event()


def reader():
    while not stop.is_set():
        try:
            d = proc.read(65536)
        except Exception:
            return
        if d:
            buf.append(d)


threading.Thread(target=reader, daemon=True).start()
joined = ""
t0 = time.time()
try:
    while time.time() - t0 < 60:
        joined = "".join(buf)
        if "run" in joined and "引擎" in joined:
            break
        time.sleep(1)
    checks = []
    clean = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", joined)
    checks.append(("启动步骤全部完成", all(k in clean for k in ("配置载入", "数据库就绪", "Ollama 引擎", "界面服务", "API 服务"))))
    checks.append(("自动打开浏览器", "正在打开浏览器" in clean))
    checks.append(("全屏仪表盘生效", "实时日志" in clean and "当前模型" in clean and "用量与任务" in clean))
    try:
        r = requests.get("http://127.0.0.1:8848/", timeout=5)
        checks.append(("界面可访问", r.status_code == 200 and "Ollama 控制台" in r.text))
        api = requests.get("http://127.0.0.1:8849/v1/models", timeout=5).json()
        checks.append(("两个模型就绪", len(api["data"]) == 2, str([m["id"] for m in api["data"]])))
        bs = requests.get("http://127.0.0.1:8848/api/bootstrap", timeout=5).json()["data"]
        checks.append(("分区与引擎运行", bs["engines"] and bs["engines"][0]["status"] == "running", str(bs["engines"])))
    except Exception as e:
        checks.append(("界面可访问", False, str(e)))
        checks.append(("两个模型就绪", False, ""))
        checks.append(("分区与引擎运行", False, ""))
    ok = True
    for c in checks:
        name, cond = c[0], c[1]
        info = c[2] if len(c) > 2 else ""
        print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + info if info else ""))
        ok = ok and cond
finally:
    stop.set()
    try:
        proc.terminate(force=True)
    except Exception:
        pass
    time.sleep(1.5)
    # 优雅关闭引擎
    try:
        requests.post("http://127.0.0.1:8848/api/app/shutdown", timeout=5)
    except Exception:
        pass
    time.sleep(2)
print("结果：", "全部通过" if ok else "有失败项")
sys.exit(0 if ok else 1)
