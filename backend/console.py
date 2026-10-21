"""后端命令行界面：启动动画（ConsoleUI）+ 实时仪表盘（rich）。"""
import json
import math
import os
import sys
import threading
import time

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__, paths
from .i18n import T

LOGO = r"""
  ██████╗ ██╗     ██╗      █████╗ ███╗   ███╗ █████╗
 ██╔═══██╗██║     ██║     ██╔══██╗████╗ ████║██╔══██╗
 ██║   ██║██║     ██║     ███████║██╔████╔██║███████║
 ██║   ██║██║     ██║     ██╔══██║██║╚██╔╝██║██╔══██║
 ╚██████╔╝███████╗███████╗██║  ██║██║ ╚═╝ ██║██║  ██║
  ╚═════╝ ╚══════╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝
"""
# 青绿 → 青色渐变（避开蓝紫与金色）
GRADIENT = ["#10b981", "#14c39a", "#19cda3", "#2dd4bf", "#22d3c5", "#06b6d4"]
ACCENT = "#2dd4bf"
DIM = "#5b6b73"
LEVEL_STYLE = {"info": "#94a3b8", "ok": "#34d399", "warn": "#fb923c", "error": "#f87171", "debug": DIM}
LEVEL_ICON = {"info": "•", "ok": "✔", "warn": "▲", "error": "✖", "debug": "·"}


def fmt_bytes(n):
    if not n:
        return "0 B"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return ("%.1f %s" % (n, u)) if u != "B" else "%d B" % n
        n /= 1024.0


def fmt_dur(s):
    s = int(s)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return "%02d:%02d:%02d" % (h, m, s)


class Dashboard:
    def __init__(self, ctx, url):
        self.ctx = ctx
        self.url = url
        self.console = Console(highlight=False)
        self.frame = 0

    # ---------------- 开机动画 ----------------
    def splash(self):
        c = self.console
        c.clear()
        lines = LOGO.strip("\n").splitlines()
        for i, line in enumerate(lines):
            t = Text(line, style="bold " + GRADIENT[i % len(GRADIENT)])
            c.print(Align.center(t))
            time.sleep(0.04)
        sub = Text.assemble((T("  最 终 兵 器  "), "bold #e2e8f0 on #0f766e"), ("   v%s  ·  Local LLM Command Center" % __version__, DIM))
        c.print(Align.center(sub))
        c.print()

    def step(self, text, ok=True):
        icon = "[#34d399]✔[/]" if ok else "[#f87171]✖[/]"
        self.console.print("   %s  %s" % (icon, text))

    # ---------------- 面板 ----------------
    def _header(self):
        spin = "◐◓◑◒"[self.frame % 4]
        ready = self.ctx.ready.is_set()
        t = Table.grid(expand=True)
        t.add_column(justify="left", ratio=1)
        t.add_column(justify="right")
        left = Text.assemble((" ◆ OLLAMA ", "bold #0b1215 on " + ACCENT), (T("  控制台 "), "bold #e2e8f0"),
                             ("v%s" % __version__, DIM))
        right = Text.assemble(((spin + T(" 初始化中  ")) if not ready else T("● 运行中  "), "bold #34d399" if ready else "bold #fb923c"),
                              ("UI ", DIM), (self.url, "bold underline " + ACCENT), ("   ⏱ " + fmt_dur(time.time() - self.ctx.started_at), DIM))
        t.add_row(left, right)
        return Panel(t, box=box.HEAVY, border_style=ACCENT, padding=(0, 1))

    def _bar(self, pct, width=18, color=ACCENT):
        """用块字符绘制进度条，任何终端下都清晰可辨。"""
        pct = max(0.0, min(100.0, float(pct or 0)))
        filled = int(round(width * pct / 100.0))
        return Text.assemble((("█" * filled), color), (("░" * (width - filled)), "#26343a"))

    def _system(self):
        s = self.ctx.system.latest or {}
        t = Table.grid(padding=(0, 1))
        t.add_column(style=DIM, width=6)
        t.add_column()
        t.add_column(justify="right", width=16)
        t.add_row("CPU", self._bar(s.get("cpu", 0)), "%5.1f%%" % s.get("cpu", 0))
        t.add_row(T("内存"), self._bar(s.get("mem_percent", 0), color="#34d399"),
                  "%s/%s" % (fmt_bytes(s.get("mem_used", 0)), fmt_bytes(s.get("mem_total", 0))))
        for g in s.get("gpus", [])[:2]:
            vp = g["mem_used"] / g["mem_total"] * 100 if g["mem_total"] else 0
            t.add_row("GPU", self._bar(g["util"], color="#22d3ee"), "%3d%%  %s℃" % (g["util"], g["temp"] if g["temp"] is not None else "-"))
            t.add_row(T("显存"), self._bar(vp, color="#2dd4bf"), "%s/%s" % (fmt_bytes(g["mem_used"]), fmt_bytes(g["mem_total"])))
        gname = s.get("gpus", [{}])[0].get("name", "") if s.get("gpus") else ""
        gname = gname or T("未检测到 NVIDIA GPU")
        return Panel(t, title="[bold]⚙ %s[/]" % T("系统"), subtitle="[%s]%s[/]" % (DIM, gname), border_style="#1f3a3a", box=box.ROUNDED)

    def _model(self):
        st = self.ctx.loader.current()
        t = Table.grid(padding=(0, 1))
        t.add_column(style=DIM, width=6)
        t.add_column()
        status_map = {"idle": ("○ " + T("未加载"), DIM), "loading": ("◌ " + T("加载中"), "#fb923c"),
                      "loaded": ("● " + T("就绪"), "#34d399"),
                      "error": ("✖ " + T("失败"), "#f87171"), "cancelled": ("○ " + T("已取消"), DIM)}
        label, color = status_map.get(st["status"], (st["status"], DIM))
        t.add_row(T("模型"), Text(st["model"] or "—", style="bold #e2e8f0"))
        t.add_row(T("状态"), Text(label, style="bold " + color))
        if st["status"] == "loading":
            g = Table.grid(padding=(0, 1))
            g.add_row(self._bar(st["progress"], width=24, color="#fb923c"), Text("%.0f%%" % st["progress"], style="#fb923c"))
            t.add_row(T("进度"), g)
            t.add_row(T("阶段"), Text(st["stage"], style=DIM))
        elif st["status"] == "loaded":
            t.add_row(T("上下文"), Text("%s tokens" % st["num_ctx"]))
            t.add_row(T("显存"), Text(fmt_bytes(st["size_vram"])))
            t.add_row(T("耗时"), Text("%.1f s" % (st["load_ms"] / 1000)))
        elif st["status"] == "error":
            t.add_row(T("原因"), Text(st["error"][:60], style="#f87171"))
        if st.get("pending"):
            t.add_row(T("待切换"), Text(st["pending"]["model"], style="#fb923c"))
        active = len(self.ctx.chat.active)
        t.add_row(T("对话"), Text(T("{n} 个生成中", n=active) if active else T("空闲"), style="#34d399" if active else DIM))
        return Panel(t, title="[bold]◈ %s[/]" % T("当前模型"), border_style="#1f3a3a", box=box.ROUNDED)

    def _engines(self):
        t = Table(box=box.SIMPLE_HEAD, expand=True, header_style="bold " + DIM, pad_edge=False)
        t.add_column(T("分区"))
        t.add_column(T("端口"), justify="right")
        t.add_column(T("状态"))
        engines = self.ctx.engines.list()
        if not engines:
            t.add_row("—", "", Text(T("未启动"), style=DIM))
        status_names = {"running": T("运行"), "starting": T("启动中"), "error": T("错误"), "stopped": T("停止")}
        for e in engines:
            color = {"running": "#34d399", "starting": "#fb923c", "error": "#f87171"}.get(e["status"], DIM)
            t.add_row(e["name"], str(e["port"] or "-"), Text("● " + status_names.get(e["status"], e["status"]), style=color))
        api = self.ctx.api_server.status() if self.ctx.api_server else {}
        foot = Text.assemble(("API  ", DIM), ((api.get("url") or T("未启用")) + ("/v1" if api.get("url") else ""), ACCENT if api.get("running") else DIM))
        return Panel(Group(t, foot), title="[bold]⛁ %s[/]" % T("引擎"), border_style="#1f3a3a", box=box.ROUNDED)

    def _usage(self):
        try:
            o = self.ctx.usage._summary(self.ctx.usage._since(1))
            a = self.ctx.usage._summary(0)
        except Exception:
            o = a = {}
        t = Table.grid(padding=(0, 2), expand=True)
        for _ in range(4):
            t.add_column()

        def cell(label, value, color="#e2e8f0"):
            return Text.assemble((label + "\n", DIM), (str(value), "bold " + color))
        t.add_row(cell(T("今日调用"), o.get("calls", 0), ACCENT), cell(T("今日输入"), o.get("input", 0)), cell(T("今日输出"), o.get("output", 0)),
                  cell(T("平均速度"), "%.1f t/s" % (o.get("avg_tps") or 0), "#34d399"))
        t.add_row(cell(T("累计调用"), a.get("calls", 0)), cell(T("累计输入"), a.get("input", 0)), cell(T("累计输出"), a.get("output", 0)),
                  cell(T("首Token"), "%.0f ms" % (o.get("avg_ttft") or 0), "#22d3ee"))
        jobs = [j for j in self.ctx.jobs.list() if j["status"] in ("queued", "running")]
        items = [t]
        for j in jobs[:3]:
            g = Table.grid(padding=(0, 1))
            g.add_row(Text(("⇣ " if j["kind"] == "pull" else "⇪ ") + j["label"][:22], style="#e2e8f0"), self._bar(j["percent"], 16, "#22d3ee"),
                      Text("%.0f%% %s" % (j["percent"], (fmt_bytes(j["speed"]) + "/s") if j["speed"] else j["stage"][:10]), style=DIM))
            items.append(g)
        return Panel(Group(*items), title="[bold]▤ %s[/]" % T("用量与任务"), border_style="#1f3a3a", box=box.ROUNDED)

    def _logs(self, n):
        rows = self.ctx.log.recent(n)
        t = Table.grid(padding=(0, 1))
        t.add_column(style=DIM, width=8)
        t.add_column(width=2)
        t.add_column(style=DIM, width=8)
        t.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
        for r in rows:
            st = LEVEL_STYLE.get(r["level"], "white")
            t.add_row(time.strftime("%H:%M:%S", time.localtime(r["ts"])), Text(LEVEL_ICON.get(r["level"], "•"), style=st),
                      r["source"][:8], Text(r["msg"], style=st if r["level"] in ("warn", "error", "ok") else "#cbd5e1"))
        return Panel(t, title="[bold]≋ %s[/]" % T("实时日志"),
                     subtitle="[%s]%s[/]" % (DIM, T("Ctrl+C 退出 · 浏览器关闭不影响后台")),
                     border_style="#1f3a3a", box=box.ROUNDED)

    def render(self):
        self.frame += 1
        h = self.console.size.height
        lay = Layout()
        lay.split_column(Layout(self._header(), size=3), Layout(name="mid", size=11), Layout(name="bot", size=8),
                         Layout(self._logs(max(3, h - 3 - 11 - 8 - 2)), name="logs"))
        lay["mid"].split_row(Layout(self._system(), ratio=5), Layout(self._model(), ratio=5), Layout(self._engines(), ratio=4))
        lay["bot"].update(self._usage())
        return lay

    def run(self, stop_evt):
        """兼容入口：非全屏时走简洁模式（全屏由 ConsoleUI 统一管理）。"""
        ConsoleUI(self.ctx).run_simple(stop_evt)

    def run_simple(self, stop_evt):
        ConsoleUI(self.ctx).run_simple(stop_evt)

    def _simple_loop(self, stop_evt):
        ConsoleUI(self.ctx).run_simple(stop_evt)


def enable_vt():
    """Windows 控制台启用 ANSI/UTF-8。"""
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleOutputCP(65001)
            k.SetConsoleCP(65001)
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)
            k.SetConsoleTitleW("%s · %s" % (T("Ollama 控制台"), T("后端控制台")))
        except Exception:
            pass


SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SHINE = "#f0fff9"
BLOCKS = "▁▂▃▄▅▆▇█"
STREAM = "0123456789ABCDEF◆◇▪▫+×÷=<>·"


def _mix(hex_a, hex_b, k):
    """两个十六进制颜色按比例混合（k=0 → a，1 → b）。支持 #abc 与 #aabbcc 两种写法。"""
    def rgb(h):
        h = (h or "").lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        h = (h + "000000")[:6]
        try:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return (255, 255, 255)

    a, b = rgb(hex_a), rgb(hex_b)
    k = max(0.0, min(1.0, float(k)))
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


class ConsoleUI:
    """启动动画 + 仪表盘的一体化控制台界面。

    分阶段电影式启动动画（每阶段都可用设置里的「开机动画」调快调慢或关闭）：
      1 内核引导（数据流 + 电源线展开）
      2 Logo 逐行显影 + 高光横扫
      3 版本徽章 + 副标题打字 + 四角描边
      4 系统自检（旋转光标 → ✔，完成闪一下）
      5 硬件扫描（CPU / 内存 / GPU / 显存 + 波形）
      6 充能进度条 → READY 爆破 → 无缝切实时仪表盘

    非全屏终端（哑终端 / 管道 / 小窗口 / --plain）自动降级为逐行文本输出。
    """

    MIN_W, MIN_H = 76, 26
    # 各阶段起始时间（秒，会按速度倍率缩放）
    PH = {"boot": 0.0, "logo": 0.9, "badge": 2.7, "check": 3.6, "scan": 5.6, "charge": 6.9}
    MIN_SPIN = 0.5      # 每个自检任务最少转圈时长，保证"逐项点亮"的节奏感

    def __init__(self, ctx=None, url="", boot_mode=None):
        self.ctx = ctx
        self.url = url
        self.console = Console(highlight=False)
        self.fullscreen = False
        self.live = None
        self.dash = None
        self.tasks = []          # [{"label","state","detail","done"}]
        self.mode = "boot"
        self.t0 = time.time()
        self.ready_at = 0.0
        self.spin = 0
        self.frame = 0
        self.lock = threading.RLock()
        self.boot_mode = boot_mode or self._read_boot_mode()
        self.scale = {"full": 1.0, "quick": 0.4, "off": 0.0}.get(self.boot_mode, 1.0)
        self.min_spin = self.MIN_SPIN * (self.scale or 1.0)

    def _read_boot_mode(self):
        """动画开始得比配置加载更早，这里直接读 settings.json 镜像（数据库仍是真源）。"""
        try:
            with open(paths.SETTINGS_PATH, "r", encoding="utf-8") as f:
                return (json.load(f).get("ui") or {}).get("boot_animation", "full")
        except Exception:
            return "full"

    def phase(self, name, el):
        """返回某阶段的本地时间（未到则为负）。"""
        return el - self.PH[name] * self.scale

    def total_boot_time(self):
        return self.PH["charge"] * self.scale + 1.1 * self.scale

    # ---------------- 能力检测 ----------------
    def detect(self):
        self.fullscreen = self._can_fullscreen()
        return self.fullscreen

    def _can_fullscreen(self):
        if not sys.stdout.isatty():
            return False
        if self.console.is_terminal is False:
            return False
        term = (os.environ.get("TERM") or "").strip().lower()
        if term in ("dumb", "unknown"):
            return False
        try:
            size = self.console.size
            if size.height < self.MIN_H or size.width < self.MIN_W:
                return False
        except Exception:
            return False
        return True

    # ---------------- 生命周期 ----------------
    def start(self):
        """进入备用屏幕，开始播放启动动画。"""
        if not self.fullscreen:
            return False
        self.t0 = time.time()
        self.mode = "boot"
        # 必须通过 get_renderable 传入可调用对象：rich 的 Live 对静态 renderable 不会逐帧重新求值
        self.live = Live(console=self.console, refresh_per_second=25, screen=True,
                         transient=False, vertical_overflow="crop", get_renderable=self._render)
        self.live.__enter__()
        return True

    def task(self, label):
        """登记一个任务（出现在自检列表里，带旋转光标）。"""
        with self.lock:
            row = {"label": label, "state": "run", "detail": "", "done": None}
            self.tasks.append(row)
            if not self.fullscreen:
                print("   ▶  %s" % label, flush=True)
        return row

    def done(self, label, detail="", ok=True):
        with self.lock:
            row = next((t for t in self.tasks if t["label"] == label and t["state"] == "run"), None)
            if row:
                row["state"] = "ok" if ok else "fail"
                row["detail"] = detail
                row["done"] = time.time()
            else:
                self.tasks.append({"label": label, "state": "ok" if ok else "fail", "detail": detail, "done": time.time()})
            if not self.fullscreen:
                print("   %s  %s%s" % ("✔" if ok else "✖", label, ("  " + detail) if detail else ""), flush=True)

    def step_line(self, label, detail="", ok=True):
        """一步到位的任务（登记 + 完成）。"""
        self.task(label)
        self.done(label, detail, ok)

    def ready(self, stop_evt=None):
        """播放 READY 爆破，然后把画面交给仪表盘（自动补足启动动画的最短时长）。"""
        if not self.fullscreen:
            self.console.print(Text.assemble((T("   ● 系统就绪  "), "bold #34d399"),
                                             (T("设置已存入数据库，重启后自动恢复"), DIM)))
            return True
        if self.scale > 0:  # 让全部阶段播完（动画关闭时直接进仪表盘）
            while self.live and time.time() - self.t0 < self.total_boot_time():
                time.sleep(0.02)
        with self.lock:
            self.mode = "ready"
            self.ready_at = time.time()
        while self.live and time.time() - self.ready_at < 1.6:
            time.sleep(0.02)
        with self.lock:
            self.mode = "dash"
        if self.live:  # 进入仪表盘后不需要 25fps，降低刷新以省 CPU
            self.live.refresh_per_second = 4
        return True

    def attach_dashboard(self, dash):
        self.dash = dash

    def bind_ctx(self, ctx):
        """把应用上下文交给界面（READY 面板与简洁模式状态行需要读取真实状态）。"""
        self.ctx = ctx

    def loop(self, stop_evt):
        """主循环：仪表盘模式刷新；非全屏时打印状态行。"""
        if not self.fullscreen:
            self.live = None
            self._simple_loop(stop_evt)
            return
        while not stop_evt.is_set():
            stop_evt.wait(0.25)

    def close(self):
        if self.live:
            try:
                self.live.__exit__(None, None, None)
            except Exception:
                pass
            self.live = None

    # ---------------- 渲染 ----------------
    def _render(self):
        try:
            self.frame += 1
            self.spin = (self.spin + 1) % (len(SPINNER) * 2)
            if self.mode == "boot":
                return self._render_boot()
            if self.mode == "ready":
                return self._render_ready()
            return self.dash.render() if self.dash else self._render_boot()
        except Exception as e:  # 渲染异常不能让动画线程静默死掉
            return Align.center(Text(T("界面渲染异常：{err}", err=e), style="bold #f87171"))

    def _logo_rows(self):
        return [l for l in LOGO.strip("\n").splitlines()]

    # ---------- 动画素材 ----------
    def _stream_row(self, width, tick, dim=0.55):
        """顶部的数据流装饰行：每隔几帧换一批字符，像滚动的数据总线。"""
        base = (tick // 3) * 7
        out = Text("  ")
        for i in range(min(width, 96)):
            ch = STREAM[(i * 13 + base * 5) % len(STREAM)]
            k = 0.25 + 0.75 * (0.5 + 0.5 * math.sin((i * 0.45) - (tick * 0.35)))
            out.append(ch, style=_mix("#0d1a1c", ACCENT, k * dim))
        return out

    def _wave(self, phase, n=34, color=ACCENT):
        """波形/柱状条：用块字符生成一条流动的曲线，作为扫描动画。"""
        out = Text("")
        for i in range(n):
            v = 0.5 + 0.5 * math.sin(phase * 2.1 + i * 0.55) * math.sin(phase * 0.7 + i * 0.13)
            out.append(BLOCKS[min(len(BLOCKS) - 1, int(v * len(BLOCKS)))], style=_mix("#0f2a2e", color, 0.35 + v * 0.65))
        return out

    def _bracket_line(self, width, k, color=ACCENT):
        """四角描边动画：先画四个角，再把边补上。"""
        w = max(24, min(width, 64))
        prog = min(1.0, k)
        horiz = int((w - 2) * prog / 2)
        edge = "─" * max(0, horiz - 1)
        if prog < 0.35:
            return Text.assemble(("  ┌", color), (" " * max(0, w - 4), ""), ("┐  ", color))
        if prog < 0.7:
            return Text.assemble(("  ┌" + edge, color), (" " * max(0, w - 4 - 2 * len(edge)), ""), (edge + "┐  ", color))
        return Text.assemble(("  ┌" + "─" * (w - 4) + "┐  ", color))

    def _render_boot(self):
        """分阶段启动动画：引导 → Logo → 徽章 → 自检 → 硬件扫描 → 充能。"""
        el = time.time() - self.t0
        tick = self.frame
        parts = []
        # ===== 顶部：数据流 + 章节指示 =====
        chapters = [(T("内核引导"), "boot"), (T("加载标识"), "logo"), (T("版本信息"), "badge"),
                    (T("系统自检"), "check"), (T("硬件扫描"), "scan"), (T("推理核心"), "charge")]
        cur_i = 0
        for i, (_, key) in enumerate(chapters):
            if self.phase(key, el) >= 0:
                cur_i = i
        parts.append(self._stream_row(96, tick))
        head = Text.assemble(("  ◆ ", "bold " + ACCENT), (T("OLLAMA 控制台"), "bold #e2e8f0"),
                             ("  ", ""), ("[%d/6] %s" % (cur_i + 1, chapters[cur_i][0]), "bold " + ACCENT),
                             ("   " + SPINNER[self.spin % len(SPINNER)], ACCENT))
        parts.append(head)
        parts.append(Text(""))

        # ===== 阶段 1：内核引导（电源线从中间展开）=====
        b = self.phase("boot", el)
        if b >= 0:
            grow = int(44 * min(1.0, b / 0.75))
            half = grow // 2
            core = 0.5 + 0.5 * math.sin(el * 9)
            parts.append(Text.assemble(("  ", ""), (" " * (22 - half), ""),
                                       ("━" * max(1, half), "bold " + _mix(ACCENT, SHINE, core)),
                                       ("◆", "bold " + _mix(ACCENT, SHINE, core)),
                                       ("━" * max(1, half), "bold " + _mix(ACCENT, SHINE, core))))
            parts.append(Text(""))

        # ===== 阶段 2：Logo 逐行显影 + 高光横扫 =====
        rows = self._logo_rows()
        lg = self.phase("logo", el)
        if lg >= 0:
            n = len(rows)
            width = max(len(r) for r in rows)
            reveal = (lg / 1.15) * n
            shine = (lg / 1.5) * (width + 60) - 30
            for i, line in enumerate(rows):
                if i > reveal:
                    parts.append(Text(" " * 2))
                    continue
                c1 = GRADIENT[i % len(GRADIENT)]
                dim = _mix(c1, "#0b1013", 0.6)
                base = c1 if i <= reveal - 1 else _mix(dim, c1, max(0.0, reveal - int(reveal)))
                dl, dr = int(shine - 10), int(shine + 10)
                seg = Text("  ")
                seg.append(line[:max(0, dl)], style="bold " + dim)
                seg.append(line[max(0, dl):max(0, dr)], style="bold " + SHINE)
                seg.append(line[max(0, dr):], style="bold " + base)
                parts.append(seg)
            parts.append(Text(""))
        else:
            parts.extend([Text("")] * 7)

        # ===== 阶段 3：版本徽章 + 副标题打字 + 四角描边 =====
        bd = self.phase("badge", el)
        if bd >= 0:
            flash = 1.0 if bd < 0.22 else 0.0
            parts.append(Text.assemble(("  ", ""),
                                       (T(" ▌控制台▐ "), "bold %s on %s" % ("#04120d", _mix(ACCENT, SHINE, flash))),
                                       ("  v%s" % __version__, "bold " + _mix(ACCENT, SHINE, 0.3 + flash)),
                                       ("   LOCAL LLM COMMAND CENTER", DIM)))
            sub = T("  本地推理 · 分区模型 · 深度思考 · 用量统计 · 全参数可控")
            parts.append(Text(sub[:int(bd / 0.035)], style=DIM))
            parts.append(self._bracket_line(64, bd / 0.8))
            parts.append(Text(""))
        else:
            parts.extend([Text("")] * 2)

        # ===== 阶段 4：系统自检（逐项点亮，完成闪一下）=====
        ck = self.phase("check", el)
        tasks = list(self.tasks)
        if ck >= 0 and tasks:
            for i, t in enumerate(tasks):
                shown_at = i * self.min_spin
                if ck < shown_at:
                    break
                state = t["state"]
                # 保证每项至少转圈 min_spin 的一半，节奏更像"逐项检测"
                if state == "ok" and ck < shown_at + self.min_spin * 0.55:
                    state = "run"
                age = ck - shown_at
                if state == "run":
                    t2 = Text.assemble(("   ", ""), (SPINNER[self.spin % len(SPINNER)] + " ", "bold " + ACCENT),
                                       (t["label"], "bold #e2e8f0"), ("   ···", DIM))
                elif state == "ok":
                    flash = age < self.min_spin * 0.75
                    t2 = Text.assemble(("   ", ""), ("✔ ", "bold " + ("#ffffff" if flash else "#34d399")),
                                       (t["label"], "bold #e2e8f0" if flash else "#cbd5e1"),
                                       (("  " + t["detail"]) if t["detail"] else "", SHINE if flash else DIM))
                else:
                    t2 = Text.assemble(("   ", ""), ("✖ ", "bold #f87171"), (t["label"], "bold #f87171"),
                                       (("  " + t["detail"]) if t["detail"] else "", DIM))
                parts.append(t2)
            parts.append(Text(""))
        else:
            parts.append(Text(""))
            parts.append(Text(""))

        # ===== 阶段 5：硬件扫描（CPU / 内存 / GPU / 显存 + 波形）=====
        sc = self.phase("scan", el)
        if sc >= 0:
            s = (self.ctx.system.latest if (self.ctx and self.ctx.system) else None) or {}
            gpu = (s.get("gpus") or [{}])[0]
            rows_hw = [
                ("CPU", s.get("cpu"), "%", ACCENT),
                ("内存", s.get("mem_percent"), "%", "#34d399"),
                ("GPU", gpu.get("util"), "%", "#22d3ee"),
                ("显存", (gpu["mem_used"] / gpu["mem_total"] * 100) if gpu.get("mem_total") else None, "%", "#2dd4bf"),
            ]
            for i, (name, val, unit, color) in enumerate(rows_hw):
                if sc < i * 0.28:
                    break
                wave = self._wave(el * 1.4 + i * 1.7, 34, color)
                shown = val is not None
                vt = Text("%5.1f%s" % (val, unit) if shown else T(" 扫描中"), style=("bold " + color) if shown else DIM)
                parts.append(Text.assemble(("   ", ""), ("%-4s " % name, DIM), wave, ("  ", ""), vt))
            for _ in range(len(rows_hw) - min(len(rows_hw), max(0, int(sc / 0.28) + 1))):
                parts.append(Text(""))
            parts.append(Text(""))
        else:
            parts.extend([Text("")] * 5)

        # ===== 阶段 6：充能进度条 =====
        ch = self.phase("charge", el)
        pct = 0 if ch < 0 else min(100, int(ch / 0.9 * 100))
        filled = int(48 * pct / 100)
        glow = pct >= 100 and (el * 6) % 2 < 1
        parts.append(Text.assemble(("   ", ""), ("█" * filled, "bold " + (_mix(ACCENT, SHINE, 0.7) if glow else ACCENT)),
                                   ("░" * (48 - filled), "#26343a"), ("  %3d%%  " % pct, "#94a3b8"),
                                   (T("装载模型引擎 · 就绪后自动打开界面") if pct < 100 else T("推理核心已就绪"), DIM)))
        return Align.center(Group(*parts))

    def _render_ready(self):
        """就绪爆破：中心光带展开 + 系统摘要面板 + 呼吸式状态灯。"""
        k = time.time() - self.ready_at
        c = self.ctx
        pulse = 0.5 + 0.5 * math.sin(k * math.pi * 2.2)
        lit = _mix(ACCENT, SHINE, pulse * 0.75)
        parts = [self._stream_row(96, self.frame), Text("")]
        rows = self._logo_rows()
        for i, line in enumerate(rows):
            parts.append(Text("  " + line, style="bold " + _mix(GRADIENT[i % len(GRADIENT)], SHINE, pulse * 0.4)))
        parts.append(Text(""))
        # 中心展开的光带
        width = 62
        grow = int(width * min(1.0, k / 0.5))
        half = grow // 2
        band = " " * (width // 2 - half) + "━" * max(1, half) + "●" + "━" * max(1, half)
        parts.append(Text(band, style="bold " + lit))
        parts.append(Text(""))
        engines = c.engines.list() if c else []
        run_n = sum(1 for e in engines if e["status"] == "running")
        try:
            parts_n = c.db.scalar("SELECT COUNT(*) FROM partitions") if c else 0
            info = [
                (T("界面地址"), self.url or "-"),
                (T("API 地址"), (c.api_server.url() + "/v1") if (c and c.api_server and c.api_server.server) else T("未启用")),
                (T("分区 / 引擎"), T("{n} 个分区 · {m} 个引擎已运行", n=parts_n, m=run_n)),
                (T("已登记模型"), T("{n} 个", n=len(c.registry.models())) if c else "-"),
                (T("设置存储"), T("SQLite · data/app.db") + (T("（本次由 settings.json 迁移）") if c and c.config.source == "json" else "")),
            ]
        except Exception:
            info = [(T("界面地址"), self.url or "-")]
        for label, value in info:
            parts.append(Text.assemble(("      ", ""), ("∙ ", DIM), ("%-10s" % label, DIM), ("  " + value, "#cbd5e1")))
        parts.append(Text(""))
        parts.append(Text.assemble(("        ", ""), ("● ", "bold " + lit), (T("系统就绪"), "bold " + lit),
                                   ("      " + T("所有参数已写入数据库，重启后自动恢复"), DIM)))
        parts.append(Text.assemble(("        ", ""), (T("Ctrl+C 退出   ·   浏览器关闭不影响后台运行"), DIM)))
        return Align.center(Group(*parts))

    def _status_line(self):
        """简洁模式的一行状态：引擎 / 模型 / 今日用量 / 生成中。"""
        ctx = self.ctx
        if ctx is None:
            return T("启动中…")
        try:
            engines = ctx.engines.list()
            run_n = sum(1 for e in engines if e["status"] == "running")
            st = ctx.loader.current()
            model = st["model"] or T("未加载")
            if st["status"] == "loading":
                model = T("{model} 加载中 {pct}%", model=model, pct="%.0f" % st["progress"])
            o = ctx.usage._summary(ctx.usage._since(1))
            usage = T("{n} 次 · {tps} tok/s", n=o.get("calls", 0), tps="%.1f" % (o.get("avg_tps") or 0))
            busy = len(ctx.chat.active)
            return T("引擎 {n}/{m} · 模型 {model} · 今日 {usage}{busy}",
                     n=run_n, m=len(engines), model=model, usage=usage,
                     busy=(T("  · 生成中 {n}", n=busy) if busy else ""))
        except Exception:
            return T("运行中…")

    def _simple_loop(self, stop_evt):
        """哑终端 / 管道 / 小窗口 / --plain：定期打印状态与新增日志。"""
        self.console.print(Text(T("提示：当前终端不支持全屏动画，已切换为简洁模式（--plain 可关闭状态行）。"), style=DIM))
        last_log = time.time()
        last_status = 0.0
        while not stop_evt.is_set():
            now = time.time()
            if now - last_status >= 10:
                last_status = now
                self.console.print(Text.assemble((time.strftime("[%H:%M:%S] "), DIM), (self._status_line(), "#cbd5e1")))
            if self.ctx is not None:
                for r in self.ctx.log.recent(120):
                    if r["ts"] > last_log:
                        st = LEVEL_STYLE.get(r["level"], "white")
                        self.console.print(Text.assemble((time.strftime("%H:%M:%S ", time.localtime(r["ts"])), DIM),
                                                         (LEVEL_ICON.get(r["level"], "•") + " ", st),
                                                         ("%s: " % r["source"], DIM), (r["msg"], st)))
            last_log = max(last_log, now)
            stop_evt.wait(0.5)
