"""验证 TERM=dumb（哑终端）下的简洁模式回退。"""
import os
import re
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "devlib"))
os.environ["TEMP"] = os.environ["TMP"] = os.path.join(ROOT, "runtime", "tmp")
from winpty import PtyProcess  # noqa: E402

env = dict(os.environ, TERM="dumb", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
proc = PtyProcess.spawn([sys.executable, "-u", os.path.join(ROOT, "app-cn.py"), "--no-browser", "--port", "8859"], env=env, dimensions=(40, 140))
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
t0 = time.time()
try:
    while time.time() - t0 < 30:
        if "简洁模式" in "".join(buf) and "引擎" in "".join(buf)[-3000:]:
            break
        time.sleep(0.5)
finally:
    text = "".join(buf)
    stop.set()
    try:
        proc.terminate(force=True)
    except Exception:
        pass
    time.sleep(0.8)
clean = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)
clean = re.sub(r"\x1b\][^\x07]*\x07", "", clean)
out = os.path.join(ROOT, "runtime", "shots", "console-dumb.txt")
open(out, "w", encoding="utf-8").write(clean)
checks = [
    ("明确告知回退", "简洁模式" in clean),
    ("状态行含引擎信息", re.search(r"引擎 \d+/\d+", clean) is not None),
    ("状态行含模型/用量", ("模型" in clean and "今日" in clean)),
    ("日志行输出", "engine" in clean or "boot" in clean or "app" in clean),
]
ok = all(c for _, c in checks)
for n, c in checks:
    print(("  [PASS] " if c else "  [FAIL] ") + n)
print("---- 简洁模式输出片段 ----")
print("\n".join(clean.strip().splitlines()[-8:]))
print("结果：", "全部通过" if ok else "有失败项")
sys.exit(0 if ok else 1)
