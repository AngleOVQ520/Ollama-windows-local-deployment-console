"""中英双语文案：命令行启动动画、实时仪表盘、后端日志与接口提示。

约定：
  - 源码里始终写中文原文，用 T("中文") 取当前语言的文案；
  - 中文模式下 T 直接返回传入的原文（零开销、零维护成本）；
  - 英文模式下查 EN 表；缺条目时回退原文，不会出现空字符串。

语言来源分两层：
  - 命令行（启动动画 / 仪表盘 / 日志）：由启动入口决定（app-cn.py / app-en.py），
    运行期可用 --lang 覆盖；
  - HTTP 请求（接口错误、日志、阶段名）：由请求头 X-Lang 或 ?lang= 决定，
    这样浏览器界面切到中文/英文时，后端返回的文案也跟着切。

带占位符的文案统一用 % 风格（沿用原有代码写法）：T("A %s") % x。
表里没有的键原样返回，便于渐进式补齐。
"""
from __future__ import annotations

import os
import threading

ZH = "zh"
EN = "en"

_launch = {"lang": ZH}      # 启动入口 / 命令行语言
_req = threading.local()    # 每个 HTTP 请求各自的语言


def normalize(lang) -> str:
    """把任意写法归一到 zh / en。"""
    s = str(lang or "").strip().lower()
    return EN if s.startswith("en") else ZH


def set_lang(lang) -> str:
    """设置启动入口（命令行）语言。"""
    _launch["lang"] = normalize(lang)
    return _launch["lang"]


def get_launcher_lang() -> str:
    """启动入口语言：页面首帧注入与 bootstrap 下发用它（与请求语言无关）。"""
    return _launch["lang"]


def set_request_lang(lang):
    """设置当前 HTTP 请求的语言；传空表示回落到启动语言。"""
    _req.lang = normalize(lang) if str(lang or "").strip() else None


def reset_request_lang():
    _req.lang = None


def get_lang() -> str:
    """当前生效语言：请求语言优先，其次启动语言。"""
    return getattr(_req, "lang", None) or _launch["lang"]


def is_en() -> bool:
    return get_lang() == EN


# 中文原文 → 英文（启动流程 / 命令行界面 / 仪表盘）。用 {} 占位符配合 T("…", n=1) 做插值。
EN_BUILTIN = {
    # ---------------- 启动流程（launcher） ----------------
    "Ollama 控制台": "Ollama Console",
    "不自动打开浏览器": "do not open the browser automatically",
    "界面端口（默认读取设置）": "UI port (defaults to the value in settings)",
    "纯日志输出，不使用仪表盘": "plain log output, no dashboard",
    "首次运行，正在安装依赖到 runtime/pylib …": "First run: installing dependencies into runtime/pylib …",
    "无可用端口": "No free port available",
    "载入设置与数据库": "Loading settings & database",
    "SQLite · WAL · 设置真源 data/app.db": "SQLite · WAL · source of truth: data/app.db",
    "探测 Ollama 引擎": "Probing Ollama engine",
    "未找到，请在设置中指定": "not found — specify it in Settings",
    "启动界面服务": "Starting web UI",
    "启动 API 服务": "Starting API service",
    "已关闭": "disabled",
    "启动分区引擎": "Starting partition engines",
    "后台就绪": "ready in background",
    "打开浏览器": "Opening browser",
    "正在关闭引擎与服务 …": "Shutting down engines and services …",
    "已退出。再见 👋": "Exited. See you 👋",
    "界面服务已启动 {url}（设置已写入数据库）": "Web UI started at {url} (settings persisted to the database)",

    # ---------------- 启动动画（ConsoleUI） ----------------
    "内核引导": "Kernel boot",
    "加载标识": "Loading emblem",
    "版本信息": "Version banner",
    "系统自检": "Self-check",
    "硬件扫描": "Hardware scan",
    "推理核心": "Inference core",
    "OLLAMA 控制台": "OLLAMA CONSOLE",
    "  控制台 ": "  Console ",
    " ▌控制台▐ ": " ▌CONSOLE▐ ",
    "  本地推理 · 分区模型 · 深度思考 · 用量统计 · 全参数可控":
        "  Local inference · Partitioned models · Deep thinking · Usage stats · Full control",
    "  最 终 兵 器  ": "  C O N S O L E  ",
    "初始化中  ": "initializing  ",
    "● 运行中  ": "● running  ",
    "装载模型引擎 · 就绪后自动打开界面": "Loading model engines · UI opens automatically when ready",
    "推理核心已就绪": "Inference core is ready",
    "   ● 系统就绪  ": "   ● System ready  ",
    "设置已存入数据库，重启后自动恢复": "Settings saved to the database and restored on restart",
    "界面渲染异常：{err}": "UI render error: {err}",

    # ---------------- 就绪面板 ----------------
    "系统就绪": "System ready",
    "所有参数已写入数据库，重启后自动恢复": "All settings persisted to the database and restored on restart",
    "Ctrl+C 退出   ·   浏览器关闭不影响后台运行":
        "Ctrl+C to quit   ·   closing the browser does not stop the backend",
    "Ctrl+C 退出 · 浏览器关闭不影响后台":
        "Ctrl+C to quit · closing the browser does not stop the backend",
    "界面地址": "UI address",
    "API 地址": "API address",
    "分区 / 引擎": "Partitions / engines",
    "已登记模型": "Registered models",
    "设置存储": "Settings store",
    "未启用": "disabled",
    "{n} 个分区 · {m} 个引擎已运行": "{n} partition(s) · {m} engine(s) running",
    "SQLite · data/app.db": "SQLite · data/app.db",
    "（本次由 settings.json 迁移）": " (migrated from settings.json this time)",

    # ---------------- 仪表盘面板 ----------------
    "后端控制台": "Backend Console",
    "系统": "System",
    "引擎": "Engines",
    "用量与任务": "Usage & Jobs",
    "实时日志": "Live log",
    "当前模型": "Current model",
    "未检测到 NVIDIA GPU": "No NVIDIA GPU detected",
    "分区": "Partition",
    "端口": "Port",
    "状态": "Status",
    "模型": "Model",
    "内存": "Memory",
    "显存": "VRAM",
    "进度": "Progress",
    "阶段": "Stage",
    "上下文": "Context",
    "耗时": "Time",
    "原因": "Reason",
    "待切换": "Pending",
    "对话": "Chats",
    "未启动": "not started",
    "运行": "running",
    "启动中": "starting",
    "错误": "error",
    "停止": "stopped",
    "未加载": "not loaded",
    "加载中": "loading",
    "就绪": "ready",
    "失败": "failed",
    "已取消": "cancelled",
    "空闲": "idle",
    "{n} 个生成中": "{n} generating",
    "○ 未加载": "○ not loaded",
    "◌ 加载中": "◌ loading",
    "● 就绪": "● ready",
    "✖ 失败": "✖ failed",
    "○ 已取消": "○ cancelled",
    "今日调用": "Calls today",
    "今日输入": "Input today",
    "今日输出": "Output today",
    "平均速度": "Avg speed",
    "累计调用": "Total calls",
    "累计输入": "Total input",
    "累计输出": "Total output",
    "首Token": "First token",
    " 扫描中": " scanning",

    # ---------------- 简洁模式 ----------------
    "提示：当前终端不支持全屏动画，已切换为简洁模式（--plain 可关闭状态行）。":
        "Note: this terminal does not support the full-screen animation; switched to simple mode (use --plain to disable the status line).",
    "启动中…": "Starting…",
    "运行中…": "Running…",
    "引擎 {n}/{m} · 模型 {model} · 今日 {usage}{busy}":
        "Engines {n}/{m} · Model {model} · Today {usage}{busy}",
    "  · 生成中 {n}": "  · {n} generating",
    "{model} 加载中 {pct}%": "{model} loading {pct}%",
    "{n} 次 · {tps} tok/s": "{n} calls · {tps} tok/s",
}


def _load_parts() -> dict:
    """汇总 backend/i18n_parts/*.py 里各业务模块的词表（模块级 TABLE 字典）。

    拆成多个小文件是为了让日志 / 阶段名 / 接口提示等文案各自维护、互不冲突；
    单文件出错时只跳过该文件，不影响其它词表与程序运行。
    """
    merged = {}
    parts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n_parts")
    if not os.path.isdir(parts_dir):
        return merged
    import importlib
    for fn in sorted(os.listdir(parts_dir)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        try:
            mod = importlib.import_module(".i18n_parts." + fn[:-3], __package__)
        except Exception:
            continue
        merged.update(getattr(mod, "TABLE", None) or {})
    return merged


EN_TABLE = dict(EN_BUILTIN)
EN_TABLE.update(_load_parts())


def T(key: str, **kw) -> str:
    """取当前语言文案。

    - 带命名占位符时用 T("…{n}", n=1)；
    - 沿用 % 风格的文案用 T("…%s") % x（不传 kw，原样返回模板）。
    """
    if get_lang() == ZH:
        text = key
    else:
        text = EN_TABLE.get(key, key)
    if kw:
        try:
            return text.format(**kw)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def zh_en(key: str) -> str:
    """返回该条目的英文（用于服务端下发给前端的默认语言文案）。"""
    return EN_TABLE.get(key, key)