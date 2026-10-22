"""引擎管理：每个分区一个独立的 `ollama serve` 进程，模型目录指向分区文件夹。

所有引擎的 HOME/APPDATA/TEMP 都被重定向到项目 runtime 目录，不会在项目外写文件。
"""
import os
import shutil
import socket
import subprocess
import threading
import time

from .. import paths
from ..core import winjob
from ..core.ollama_client import OllamaClient
from ..i18n import T

CANDIDATE_PATHS = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
    r"C:\Program Files\Ollama\ollama.exe",
]


def find_ollama(custom=""):
    if custom and os.path.isfile(custom):
        return custom
    for p in CANDIDATE_PATHS:
        if p and os.path.isfile(p):
            return p
    return shutil.which("ollama") or ""


def port_free(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) != 0


class Engine:
    def __init__(self, manager, partition):
        self.m = manager
        self.pid_ = partition["id"]
        self.models_dir = partition["path"]
        self.name = partition["name"]
        self.port = None
        self.proc = None
        self.client = None
        self.version = ""
        self.status = "stopped"  # stopped / starting / running / error
        self.error = ""
        self.started_at = 0
        self.current_spec = None  # 当前推测解码类型；None = 跟随全局配置
        self._lock = threading.RLock()
        self._log_fp = None

    def set_spec(self, spec_type):
        """设置推测解码类型（"" = 关闭；在下次 start() 时生效）。"""
        self.current_spec = spec_type if spec_type else ""

    @property
    def base_url(self):
        return "http://127.0.0.1:%d" % self.port if self.port else ""

    def env(self):
        cfg = self.m.config.section("engine")
        env = paths.sandbox_env()
        env.pop("OLLAMA_HOST", None)
        env.update({
            "OLLAMA_MODELS": self.models_dir,
            "OLLAMA_HOST": "127.0.0.1:%d" % self.port,
            "OLLAMA_KEEP_ALIVE": cfg.get("keep_alive") or "30m",
            "OLLAMA_NUM_PARALLEL": str(max(1, int(cfg.get("num_parallel") or 1))),
            "OLLAMA_MAX_LOADED_MODELS": "1",
            "OLLAMA_LOAD_TIMEOUT": cfg.get("load_timeout") or "5m",
            "OLLAMA_FLASH_ATTENTION": "1" if cfg.get("flash_attention") else "0",
            "OLLAMA_KV_CACHE_TYPE": cfg.get("kv_cache_type") or "f16",
        })
        # 不设置 OLLAMA_ORIGINS：保持 Ollama 默认（只允许本机来源），
        # 浏览器侧全部经 Flask 代理访问，任意网页不能跨域直读本机引擎端口。
        env.pop("OLLAMA_ORIGINS", None)
        if cfg.get("no_cloud"):
            env["OLLAMA_NO_CLOUD"] = "1"
        if cfg.get("sched_spread"):
            env["OLLAMA_SCHED_SPREAD"] = "1"
        if int(cfg.get("gpu_overhead_mb") or 0) > 0:
            env["OLLAMA_GPU_OVERHEAD"] = str(int(cfg["gpu_overhead_mb"]) * 1024 * 1024)
        # MTP / 推测解码：llama-server 读取 LLAMA_ARG_* 环境变量。
        # current_spec 由 loader 按模型 MTP 能力动态设置（自动模式）；
        # current_spec 为 None 时回退到全局配置 engine.spec_type（手动覆盖）。
        spec_type = self.current_spec
        if spec_type is None:
            spec_type = (cfg.get("spec_type") or "").strip()
        if spec_type and spec_type != "none":
            env["LLAMA_ARG_SPEC_TYPE"] = spec_type
        if cfg.get("debug"):
            env["OLLAMA_DEBUG"] = "1"
        else:
            env.pop("OLLAMA_DEBUG", None)
        env.pop("OLLAMA_CONTEXT_LENGTH", None)
        return env

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, wait=True):
        with self._lock:
            if self.alive() and self.status == "running":
                return True
            elif self.alive():
                # 旧进程仍存活（如上次就绪等待超时）：先停掉，保证同一时刻只有一个引擎进程
                self.stop()
            exe = find_ollama(self.m.config.get("engine.ollama_path"))
            if not exe:
                self.status, self.error = "error", T("未找到 ollama.exe，请在设置中指定路径")
                self.m.publish()
                return False
            os.makedirs(self.models_dir, exist_ok=True)
            self.port = self.m.alloc_port(self.pid_)
            self.status, self.error = "starting", ""
            self.m.publish()
            log_path = os.path.join(paths.LOG_DIR, "engine-p%d.log" % self.pid_)
            self._log_fp = open(log_path, "ab")
            flags = 0
            if os.name == "nt":
                flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            self.proc = subprocess.Popen([exe, "serve"], env=self.env(), cwd=paths.RUNTIME_DIR,
                                         stdout=self._log_fp, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, creationflags=flags)
            winjob.assign(self.proc.pid)
            self.client = OllamaClient(self.base_url)
            self.started_at = time.time()
        if not wait:
            threading.Thread(target=self._wait_ready, daemon=True).start()
            return True
        return self._wait_ready()

    def _wait_ready(self, timeout=40):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.status == "running":
                return True
            if not self.alive():
                self.status = "error"
                self.error = T("引擎进程意外退出（详见 runtime/logs/engine-p%d.log）") % self.pid_
                self.m.log.error("engine", "%s: %s" % (self.name, self.error))
                self.m.publish()
                return False
            try:
                self.version = self.client.version(timeout=1)
                self.status = "running"
                self.error = ""
                self.m.log.ok("engine", T("分区「%s」引擎就绪 :%d  v%s") % (self.name, self.port, self.version))
                self.m.publish()
                return True
            except Exception:
                time.sleep(0.25)
        self.status, self.error = "error", T("引擎启动超时")
        self.m.publish()
        return False

    def stop(self):
        with self._lock:
            p = self.proc
            self.proc = None
            if p and p.poll() is None:
                try:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        p.terminate()
                    p.wait(timeout=10)
                except Exception:
                    pass
            if self._log_fp:
                try:
                    self._log_fp.close()
                except OSError:
                    pass
                self._log_fp = None
            self.status = "stopped"
            self.current_spec = None  # 重新启动时回到全局配置，loader 会按需覆盖
            self.m.publish()

    def ensure(self):
        if self.alive() and self.status == "running":
            return True
        return self.start(wait=True)

    def runner_pids(self):
        """返回该引擎下 llama-server 子进程的 pid 列表。"""
        if not self.alive():
            return []
        try:
            import psutil
            return [c.pid for c in psutil.Process(self.proc.pid).children(recursive=True)]
        except Exception:
            return []

    def info(self):
        return {"partition_id": self.pid_, "name": self.name, "port": self.port, "status": self.status,
                "error": self.error, "version": self.version, "pid": self.proc.pid if self.alive() else None,
                "uptime": time.time() - self.started_at if self.alive() else 0, "models_dir": self.models_dir}


class EngineManager:
    def __init__(self, config, log, bus):
        self.config = config
        self.log = log
        self.bus = bus
        self.engines = {}
        self._lock = threading.RLock()
        self._ports = {}

    def alloc_port(self, partition_id):
        with self._lock:
            base = int(self.config.get("engine.base_port") or 11500)
            used = {p for k, p in self._ports.items() if k != partition_id}
            cur = self._ports.get(partition_id)
            if cur and cur not in used and port_free(cur):
                return cur
            port = base + partition_id
            while port in used or not port_free(port):
                port += 1
            self._ports[partition_id] = port
            return port

    def get(self, partition, start=True):
        with self._lock:
            e = self.engines.get(partition["id"])
            if e is None or e.models_dir != partition["path"]:
                if e:
                    e.stop()
                e = Engine(self, partition)
                e.name = partition["name"]
                self.engines[partition["id"]] = e
            e.name = partition["name"]
        if start:
            e.ensure()
        return e

    def peek(self, partition_id):
        return self.engines.get(partition_id)

    def remove(self, partition_id):
        with self._lock:
            e = self.engines.pop(partition_id, None)
            self._ports.pop(partition_id, None)
        if e:
            e.stop()

    def stop_all(self):
        for e in list(self.engines.values()):
            e.stop()

    def restart_all(self):
        for e in list(self.engines.values()):
            was = e.alive()
            e.stop()
            if was:
                e.start(wait=False)

    def list(self):
        return [e.info() for e in self.engines.values()]

    def publish(self):
        self.bus.publish("engines", self.list(), sticky=True)
