"""命令行启动动画验证：阶段齐全、时长符合预期、可切快速模式，最后无缝进入仪表盘。
用法：python tests/console_pty.py
"""
import json
import os
import re
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "devlib"))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
os.environ["TEMP"] = os.environ["TMP"] = os.path.join(ROOT, "runtime", "tmp")
os.environ["PYTHONIOENCODING"] = "utf-8"
from winpty import PtyProcess  # noqa: E402
import requests  # noqa: E402

PORT = 8858
OUT = os.path.join(ROOT, "runtime", "shots")
os.makedirs(OUT, exist_ok=True)
PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def clean(text):
    text = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)
    return re.sub(r"\x1b\][^\x07]*\x07", "", text)


def run_once(tag, expect_ready_in=None):
    """启动 app-cn.py，采样直到出现 READY，再等到仪表盘，返回（文本, READY 出现时刻）。"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    env.pop("TERM", None)  # 真实 Windows 终端不设置 TERM
    proc = PtyProcess.spawn([sys.executable, "-u", os.path.join(ROOT, "app-cn.py"), "--no-browser", "--port", str(PORT)],
                            env=env, dimensions=(46, 150))
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
    ready_at = None
    while time.time() - t0 < 40:
        text = clean("".join(buf))
        if ready_at is None and "系统就绪" in text:
            ready_at = time.time() - t0
        if ready_at and "实时日志" in text:
            break
        time.sleep(0.08)
    time.sleep(0.6)
    text = clean("".join(buf))
    stop.set()
    try:
        proc.terminate(force=True)
    except Exception:
        pass
    time.sleep(1.0)
    open(os.path.join(OUT, "boot-%s.txt" % tag), "w", encoding="utf-8").write(text)
    return text, (ready_at or 0)


def set_mode(mode):
    """临时起一个实例，把开机动画模式写进设置（数据库 + 镜像都会同步），然后关掉它。"""
    import subprocess
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "app-cn.py"), "--no-browser", "--plain", "--port", "8860"],
                         cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    url = "http://127.0.0.1:8860"
    try:
        for _ in range(60):
            try:
                requests.patch(url + "/api/settings", json={"ui": {"boot_animation": mode}}, timeout=3)
                break
            except Exception:
                time.sleep(0.3)
        try:
            requests.post(url + "/api/app/shutdown", timeout=3)
        except Exception:
            pass
        try:
            p.wait(timeout=20)
        except Exception:
            p.terminate()
    finally:
        time.sleep(1.0)
    got = json.load(open(os.path.join(ROOT, "data", "settings.json"), encoding="utf-8"))["ui"]["boot_animation"]
    print("   （开机动画已设为：%s，镜像确认：%s）" % (mode, got))
    return got


try:
    print("== 1. 完整模式：阶段齐全 + 时长 + 无缝切仪表盘")
    text, ready_at = run_once("full")
    phases = ["[1/6] 内核引导", "[2/6] 加载标识", "[3/6] 版本信息", "[4/6] 系统自检",
              "[5/6] 硬件扫描", "[6/6] 推理核心"]
    for p in phases:
        check("阶段出现：" + p, p in text)
    check("数据流装饰行", any(ch in text for ch in "◆◇▪▫×÷"), )
    check("Logo 高光/渐变字符", "████" in text)
    check("版本徽章", "▌控制台▐" in text and "LOCAL LLM COMMAND CENTER" in text)
    check("副标题打字", "本地推理 · 分区模型" in text)
    check("四角描边", "┌" in text and "┐" in text)
    for label in ["载入设置与数据库", "探测 Ollama 引擎", "启动界面服务", "启动 API 服务", "启动分区引擎"]:
        check("自检任务：" + label, label in text)
    check("任务完成标记", "✔" in text)
    check("无渲染异常", "渲染异常" not in text)
    check("硬件扫描：波形 + 真实数值", re.search(r"CPU\s+[▁-█]{8,}\s+[\d.]+%", text) is not None,
          (re.search(r"CPU[^\r\n]{0,80}", text) or [""])[0][:70])
    check("硬件扫描：显存读数", re.search(r"显存\s+[▁-█]{8,}\s+[\d.]+%", text) is not None)
    check("充能进度条到 100%", "100%" in text and "推理核心已就绪" in text)
    check("READY：系统摘要", all(k in text for k in ["界面地址", "API 地址", "设置存储"]) and re.search(r"已登记模型\s+\d+ 个", text) is not None)
    check("READY：呼吸状态灯与提示", "系统就绪" in text and "Ctrl+C 退出" in text)
    check("无缝切入实时仪表盘", all(k in text for k in ["⚙ 系统", "◈ 当前模型", "⛁ 引擎", "▤ 用量与任务", "≋ 实时日志"]))
    check("完整模式时长 6~12 秒", 6.0 <= ready_at <= 12.0, "READY 用时 %.1fs" % ready_at)

    print("== 2. 快速模式：阶段仍在但明显更快")
    check("设置落库为 quick", set_mode("quick") == "quick")
    text2, ready2 = run_once("quick")
    check("快速模式仍有全部阶段", all(p in text2 for p in ["[1/6] 内核引导", "[4/6] 系统自检", "[6/6] 推理核心"]))
    check("快速模式明显更快", ready2 < ready_at - 1.5, "quick %.1fs vs full %.1fs" % (ready2, ready_at))
    check("快速模式也进入仪表盘", "实时日志" in text2)
    check("快速模式时长 1.5~5.5 秒", 1.5 <= ready2 <= 5.5, "%.1fs" % ready2)

    print("== 3. 关闭动画：直接进仪表盘")
    check("设置落库为 off", set_mode("off") == "off")
    text3, ready3 = run_once("off")
    check("关闭动画后仍进入仪表盘", "实时日志" in text3)
    check("关闭动画后用时很短", ready3 <= 3.0, "%.1fs" % ready3)

    print("== 4. 恢复为完整模式")
    check("设置恢复为 full", set_mode("full") == "full")
    text4, ready4 = run_once("full-restored")
    check("完整模式恢复后动画再次完整播放", "[6/6] 推理核心" in text4 and ready4 >= 6.0, "%.1fs" % ready4)
finally:
    try:
        requests.post("http://127.0.0.1:%d/api/app/shutdown" % PORT, timeout=3)
    except Exception:
        pass

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
