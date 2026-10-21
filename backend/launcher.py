"""启动流程实现：app-cn.py / app-en.py / APP-NO.py 共用。

运行环境沙箱化（依赖从项目内加载、缓存与临时文件写入 runtime）必须在本模块
导入任何第三方库之前完成，因此这些代码放在模块级别执行。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYLIB = os.path.join(ROOT, "runtime", "pylib")

# 1) 运行环境沙箱化：依赖从项目内加载，缓存/临时文件写入项目 runtime 目录
sys.dont_write_bytecode = False
os.environ["PYTHONPYCACHEPREFIX"] = os.path.join(ROOT, "runtime", "pycache")
sys.pycache_prefix = os.environ["PYTHONPYCACHEPREFIX"]
for _k in ("TEMP", "TMP"):
    os.environ[_k] = os.path.join(ROOT, "runtime", "tmp")
os.makedirs(os.environ["TEMP"], exist_ok=True)
import tempfile  # noqa: E402

tempfile.tempdir = os.environ["TEMP"]
if PYLIB not in sys.path:
    sys.path.insert(0, PYLIB)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.i18n import set_lang, T  # noqa: E402


def ensure_deps():
    """缺少依赖时自动安装到 runtime/pylib（不污染系统 Python）。"""
    missing = []
    for mod in ("flask", "requests", "rich", "psutil", "pynvml"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if not missing:
        return
    import subprocess
    print(T("首次运行，正在安装依赖到 runtime/pylib …"), flush=True)
    req = os.path.join(ROOT, "requirements.txt")
    subprocess.check_call([sys.executable, "-m", "pip", "--isolated", "install", "--no-cache-dir", "--disable-pip-version-check",
                           "--target", PYLIB, "-r", req])
    import importlib
    importlib.invalidate_caches()


ensure_deps()

import argparse  # noqa: E402
import logging  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import webbrowser  # noqa: E402

from werkzeug.serving import make_server  # noqa: E402


def parse_args(desc=None, extra=()):
    ap = argparse.ArgumentParser(description=desc or T("Ollama 控制台"))
    ap.add_argument("--no-browser", action="store_true", help=T("不自动打开浏览器"))
    ap.add_argument("--port", type=int, default=0, help=T("界面端口（默认读取设置）"))
    ap.add_argument("--plain", action="store_true", help=T("纯日志输出，不使用仪表盘"))
    ap.add_argument("--lang", choices=("zh", "en"), default=None,
                    help="语言 / language（覆盖启动入口的默认值）")
    for a in extra:
        ap.add_argument(a[0], action=a[1], help=a[2] if len(a) > 2 else None)
    return ap.parse_args()


def pick_port(host, preferred, avoid=()):
    import socket
    for p in [preferred] + list(range(preferred + 1, preferred + 40)):
        if p in avoid or p in (1,) or p < 1024:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    raise SystemExit(T("无可用端口"))


def run(lang="zh"):
    """启动入口。lang 决定命令行动画与浏览器界面的默认语言。"""
    lang = set_lang(lang)
    args = parse_args()
    if args.lang:
        lang = set_lang(args.lang)

    from backend import __version__
    from backend import console as con
    from backend.context import AppContext
    from backend.routes import create_app
    from backend.services.api_server import ApiServer

    con.enable_vt()
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    # 启动动画：先进入全屏备用屏幕开始播放，再在动画中完成真实初始化
    ui = con.ConsoleUI()
    if args.plain:
        ui.fullscreen = False
    else:
        ui.detect()
    ui.start()
    if not ui.fullscreen:
        print("\n  ◆ %s v%s  ·  Local LLM Command Center\n" % (T("Ollama 控制台"), __version__), flush=True)

    ui.task(T("载入设置与数据库"))
    ctx = AppContext()
    ui.bind_ctx(ctx)
    ui.done(T("载入设置与数据库"), T("SQLite · WAL · 设置真源 data/app.db"))

    ui.task(T("探测 Ollama 引擎"))
    exe = ctx.ollama_exe()
    ui.done(T("探测 Ollama 引擎"), exe or T("未找到，请在设置中指定"), bool(exe))

    ui.task(T("启动界面服务"))
    host = ctx.config.get("server.host") or "127.0.0.1"
    api_port = int(ctx.config.get("api.port") or 8849) if ctx.config.get("api.enabled") else 0
    port = pick_port(host, args.port or int(ctx.config.get("server.port") or 8848), avoid=(api_port,))
    app = create_app(ctx)
    server = make_server(host, port, app, threaded=True)
    url = "http://%s:%d" % ("127.0.0.1" if host in ("0.0.0.0", "") else host, port)
    ui.done(T("启动界面服务"), url)

    ui.task(T("启动 API 服务"))
    ctx.api_server = ApiServer(ctx)
    if ctx.config.get("api.enabled"):
        api_ok = ctx.api_server.start()
        ui.done(T("启动 API 服务"), ctx.api_server.url() + "/v1" if api_ok else ctx.api_server.error, api_ok)
    else:
        ui.done(T("启动 API 服务"), T("已关闭"), True)

    ui.task(T("启动分区引擎"))
    threading.Thread(target=server.serve_forever, daemon=True, name="ui-server").start()

    def boot_worker():
        ctx.boot()
        ui.done(T("启动分区引擎"), T("后台就绪"))

    threading.Thread(target=boot_worker, daemon=True, name="boot").start()
    ctx.log.ok("app", T("界面服务已启动 {url}（设置已写入数据库）", url=url))

    if not args.no_browser and ctx.config.get("server.open_browser"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        ui.task(T("打开浏览器"))
        ui.done(T("打开浏览器"), url)

    ui.url = url
    ui.attach_dashboard(con.Dashboard(ctx, url))
    ui.ready()          # READY 爆破 → 无缝切换为实时仪表盘

    stop_evt = threading.Event()
    try:
        ui.loop(stop_evt)
    except KeyboardInterrupt:
        pass
    finally:
        stop_evt.set()
        ui.close()
        print("\n" + T("正在关闭引擎与服务 …"), flush=True)
        try:
            ctx.shutdown()
            server.shutdown()
        except Exception:
            pass
        print(T("已退出。再见 👋"), flush=True)
        os._exit(0)


__all__ = ["run", "ROOT", "PYLIB", "pick_port"]