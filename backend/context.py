"""应用上下文：组装所有服务（依赖注入的唯一位置）。"""
import os
import shutil
import threading
import time

from . import paths
from .i18n import T
from .core.config import Config
from .core.db import Database
from .core.events import EventBus, LogBuffer
from .services.chat import ChatService
from .services.engines import EngineManager, find_ollama
from .services.imagegen import ImageGenService
from .services.jobs import JobService
from .services.loader import ModelLoader
from .services.registry import Registry
from .services.system import SystemMonitor
from .services.usage import UsageService


class AppContext:
    def __init__(self):
        paths.ensure_dirs()
        self.started_at = time.time()
        self.bus = EventBus()
        self.log = LogBuffer()
        self.log.bus = self.bus
        self.db = Database()
        # 设置以 SQLite 为真源（首次运行会从 settings.json 迁移），保证重启后原样恢复
        self.config = Config(db=self.db)
        self.engines = EngineManager(self.config, self.log, self.bus)
        self.registry = Registry(self.db, self.engines, self.log, self.bus)
        self.usage = UsageService(self.db, self.bus)
        self.loader = ModelLoader(self.registry, self.engines, self.config, self.log, self.bus)
        self.jobs = JobService(self.db, self.registry, self.engines, self.log, self.bus)
        self.image = ImageGenService(self.db, self.config, self.loader, self.log, self.bus)
        self.chat = ChatService(self.db, self.registry, self.engines, self.loader, self.config, self.usage, self.log, self.bus)
        self.system = SystemMonitor(self.bus)
        self.api_server = None
        self.ready = threading.Event()
        self.config.on_change(self._on_config)
        self.stats = {"requests": 0, "api_requests": 0}

    def ollama_exe(self):
        return find_ollama(self.config.get("engine.ollama_path"))

    def boot(self):
        """后台初始化：启动默认分区引擎、同步模型、自动加载上次模型。"""
        self.system.start()
        if self.config.get("data.auto_backup"):
            self.backup(auto=True)
        self.usage.prune(int(self.config.get("data.usage_retention_days") or 0))
        try:
            n = self.image.prune()
            if n:
                self.log.info("boot", T("已清理 %d 个过期生图任务") % n)
        except Exception as e:
            self.log.warn("boot", T("清理生图产物失败：%s") % e)
        exe = self.ollama_exe()
        if not exe:
            self.log.error("boot", T("未找到 ollama.exe，请在 设置 → 引擎 中指定路径"))
        else:
            self.log.info("boot", "Ollama: %s" % exe)
        for p in self.db.query("SELECT * FROM partitions ORDER BY sort, id"):
            if not os.path.isdir(p["path"]):
                self.log.warn("boot", T("分区「%s」路径不存在：%s") % (p["name"], p["path"]))
                continue
            has_models = os.path.isdir(os.path.join(p["path"], "manifests")) or os.path.isdir(os.path.join(p["path"], "manifests-v2"))
            if p["is_default"] or has_models:
                self.engines.get(p, start=True)
        n = self.registry.sync()
        self.log.ok("boot", T("模型同步完成（%d 项更新，共 %d 个模型）") % (n, len(self.registry.models())))
        last = self.config.get("chat.last_model") or ""
        if self.config.get("chat.auto_load_last") and "|" in last:
            pid, name = last.split("|", 1)
            try:
                if self.registry.find(int(pid), name):
                    self.loader.select(int(pid), name)
            except Exception as e:
                self.log.warn("boot", T("自动加载上次模型失败：%s") % e)
        self.ready.set()

    def _on_config(self, changed):
        eng_keys = {"keep_alive", "flash_attention", "kv_cache_type", "num_parallel", "gpu_overhead_mb", "load_timeout",
                    "no_cloud", "sched_spread", "ollama_path", "base_port", "spec_type", "debug"}
        if set(changed.get("engine", [])) & eng_keys:
            self.log.info("config", T("引擎配置已变更，重启引擎…"))
            threading.Thread(target=self._restart_engines, daemon=True).start()
        if "api" in changed:
            # 仅监听相关的变化需要重启 API 服务；密钥 / 鉴权 / 跨域等参数是每次请求实时读取的
            if set(changed["api"]) & {"enabled", "port", "lan"} and self.api_server is not None:
                threading.Thread(target=self.api_server.restart, daemon=True).start()

    def _restart_engines(self):
        self.loader.unload()
        self.engines.restart_all()

    def backup(self, auto=False):
        os.makedirs(paths.BACKUP_DIR, exist_ok=True)
        name = "%s-%s" % ("auto" if auto else "manual", time.strftime("%Y%m%d-%H%M%S"))
        dest = os.path.join(paths.BACKUP_DIR, name)
        os.makedirs(dest, exist_ok=True)
        self.db.backup(os.path.join(dest, "app.db"))
        shutil.copy2(paths.SETTINGS_PATH, os.path.join(dest, "settings.json"))
        # 自动备份只保留最近 5 份
        autos = sorted(d for d in os.listdir(paths.BACKUP_DIR) if d.startswith("auto-"))
        for d in autos[:-5]:
            shutil.rmtree(os.path.join(paths.BACKUP_DIR, d), ignore_errors=True)
        return name

    def backups(self):
        if not os.path.isdir(paths.BACKUP_DIR):
            return []
        out = []
        for d in sorted(os.listdir(paths.BACKUP_DIR), reverse=True):
            p = os.path.join(paths.BACKUP_DIR, d, "app.db")
            if os.path.isfile(p):
                out.append({"name": d, "size": os.path.getsize(p), "ts": os.path.getmtime(p)})
        return out

    def shutdown(self):
        self.log.info("app", T("正在关闭…"))
        self.system.stop()
        for r in list(self.chat.active.values()):
            r.stop()
        try:
            if self.image._current:
                self.image.cancel(self.image._current["id"])
        except Exception:
            pass
        if self.config.get("engine.stop_on_exit"):
            self.engines.stop_all()
        if self.api_server is not None:
            self.api_server.stop()
