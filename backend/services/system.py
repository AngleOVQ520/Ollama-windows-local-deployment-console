"""系统监控（CPU/内存/GPU/磁盘）与本地文件浏览（用于选择分区目录与 GGUF 文件）。"""
import os
import string
import threading
import time

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

try:
    import pynvml
except ImportError:  # pragma: no cover
    pynvml = None


class SystemMonitor:
    def __init__(self, bus, interval=1.5):
        self.bus = bus
        self.interval = interval
        self.latest = {}
        self.history = []
        self._nv = False
        self._stop = threading.Event()
        if pynvml is not None:
            try:
                pynvml.nvmlInit()
                self._nv = True
            except Exception:
                self._nv = False
        if psutil:
            psutil.cpu_percent(None)

    def gpus(self):
        out = []
        if not self._nv:
            return out
        try:
            for i in range(pynvml.nvmlDeviceGetCount()):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                util = pynvml.nvmlDeviceGetUtilizationRates(h)
                name = pynvml.nvmlDeviceGetName(h)
                try:
                    temp = pynvml.nvmlDeviceGetTemperature(h, 0)
                except Exception:
                    temp = None
                try:
                    power = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
                except Exception:
                    power = None
                out.append({"index": i, "name": name.decode() if isinstance(name, bytes) else name,
                            "mem_total": mem.total, "mem_used": mem.used, "util": util.gpu, "temp": temp, "power": power})
        except Exception:
            pass
        return out

    def sample(self):
        s = {"ts": time.time()}
        if psutil:
            vm = psutil.virtual_memory()
            s.update({"cpu": psutil.cpu_percent(None), "mem_total": vm.total, "mem_used": vm.total - vm.available,
                      "mem_percent": vm.percent, "cpu_count": psutil.cpu_count()})
        s["gpus"] = self.gpus()
        return s

    def run(self):
        while not self._stop.is_set():
            try:
                s = self.sample()
                self.latest = s
                self.history.append({"ts": s["ts"], "cpu": s.get("cpu", 0), "mem": s.get("mem_percent", 0),
                                     "gpu": s["gpus"][0]["util"] if s["gpus"] else 0,
                                     "vram": (s["gpus"][0]["mem_used"] / s["gpus"][0]["mem_total"] * 100) if s["gpus"] else 0})
                self.history = self.history[-120:]
                self.bus.publish("system", s, sticky=True)
            except Exception:
                pass
            self._stop.wait(self.interval)

    def start(self):
        threading.Thread(target=self.run, daemon=True, name="sysmon").start()

    def stop(self):
        self._stop.set()


def list_drives():
    out = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            root = letter + ":\\"
            if os.path.exists(root):
                info = {"path": root, "name": letter + ":"}
                try:
                    import shutil
                    du = shutil.disk_usage(root)
                    info.update({"total": du.total, "free": du.free})
                except OSError:
                    pass
                out.append(info)
    else:
        out.append({"path": "/", "name": "/"})
    return out


def browse(path, mode="dir", exts=(".gguf",)):
    """列出目录内容。mode=dir 只列文件夹；mode=file 同时列出指定扩展名的文件。"""
    if not path:
        return {"path": "", "parent": None, "drives": list_drives(), "entries": []}
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise ValueError("文件夹不存在")
    entries = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.name.startswith("$") or e.name in ("System Volume Information",):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        entries.append({"name": e.name, "path": e.path, "type": "dir"})
                    elif mode == "file" and e.name.lower().endswith(tuple(exts)):
                        entries.append({"name": e.name, "path": e.path, "type": "file", "size": e.stat().st_size,
                                        "mtime": e.stat().st_mtime})
                except OSError:
                    continue
    except PermissionError:
        raise ValueError("没有权限访问该文件夹")
    entries.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
    parent = os.path.dirname(path.rstrip("\\/"))
    if parent == path.rstrip("\\/") or not parent:
        parent = ""
    elif len(parent) == 2 and parent[1] == ":":
        parent += "\\"
    return {"path": path, "parent": parent, "entries": entries[:2000], "drives": list_drives()}


def scan_gguf(path, max_depth=3):
    """递归查找 GGUF 文件（用于"扫描文件夹"批量导入）。"""
    found = []
    path = os.path.abspath(path)
    base_depth = path.rstrip("\\/").count(os.sep)
    for root, dirs, files in os.walk(path):
        if root.count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d not in ("blobs", "manifests", "manifests-v2", "node_modules", ".git")]
        for f in files:
            if f.lower().endswith(".gguf"):
                p = os.path.join(root, f)
                try:
                    found.append({"path": p, "name": f, "size": os.path.getsize(p)})
                except OSError:
                    pass
        if len(found) > 500:
            break
    return found
