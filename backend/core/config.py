"""设置存储：默认值 + 深度合并 + SQLite 持久化（settings.json 作为可读镜像）+ 变更回调。"""
import copy
import json
import os
import threading
import time

from .. import paths
from .. import __version__

APP_TAG = "ollama-ultimate/%s" % __version__

THINK_LEVELS = ["off", "mini", "low", "medium", "high", "x-high", "max", "ultra"]

DEFAULTS = {
    "server": {"host": "127.0.0.1", "port": 8848, "open_browser": True},
    "api": {"enabled": True, "port": 8849, "lan": False, "require_key": False, "api_key": "", "cors": True,
            "record_usage": True},
    "engine": {
        "ollama_path": "", "base_port": 11500, "keep_alive": "30m", "flash_attention": True,
        "kv_cache_type": "f16", "num_parallel": 1, "gpu_overhead_mb": 0, "load_timeout": "5m",
        "no_cloud": True, "sched_spread": False, "stop_on_exit": True,
        "spec_type": "", "debug": False,
    },
    "chat": {
        "system_prompt": "", "send_key": "enter", "auto_title": "first", "show_stats": True,
        "render_math": True, "render_mermaid": True, "html_default": "code", "code_wrap": False,
        "default_think": "off", "auto_load_last": False, "last_model": "", "confirm_delete": True,
    },
    "params": {
        "temperature": 0.7, "top_p": 0.9, "top_k": 40, "min_p": 0.0, "typical_p": 1.0,
        "repeat_penalty": 1.1, "repeat_last_n": 64, "presence_penalty": 0.0, "frequency_penalty": 0.0,
        "seed": -1, "mirostat": 0, "mirostat_tau": 5.0, "mirostat_eta": 0.1, "stop": [],
        "num_thread": 0, "num_batch": 512, "num_gpu": -1, "use_model_defaults": False,
    },
    "context": {"num_ctx": 8192, "max_output": 4096, "max_input": 6144, "history_turns": 0},
    "thinking": {"budgets": {"mini": 256, "low": 1024, "medium": 2048, "high": 4096,
                             "x-high": 8192, "max": 16384, "ultra": 0}},
    "ui": {"theme": "dark", "accent": "emerald", "language": "auto", "font_size": 14, "animations": True,
           "anim_speed": 1.0, "msg_width": 860, "sidebar_open": True, "density": "comfortable",
           "boot_animation": "full", "mtp_auto": True},
    "data": {"usage_retention_days": 0, "auto_backup": True},
    # 生图（stable-diffusion.cpp）：模型路径留空时自动在 models/image 中挑选
    "image": {
        "enabled": True, "diffusion_model": "", "vae": "", "llm": "", "llm_vision": "",
        # 提示词：前端保存后必须落库（不在 DEFAULTS 里会被 sanitize 静默丢弃）
        "prompt": "", "negative": "",
        "width": 1024, "height": 1024, "steps": 24, "cfg_scale": 4.0, "seed": -1,
        "sampling": "euler", "scheduler": "", "flow_shift": 3.0, "batch": 1,
        # 图生图专用
        "strength": 0.75, "img_cfg_scale": 0.0,
        # 高级
        "guidance": 0.0, "slg_scale": 0.0, "clip_skip": 1,
        "preview": "none", "vae_tiling": False,
        "offload_to_cpu": True, "unload_llm": True, "keep_days": 30,
    },
}


def deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _coerce(default, value):
    """按默认值的类型校正输入，非法值回退默认。"""
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default
    if isinstance(default, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, str):
        return "" if value is None else str(value)
    if isinstance(default, list):
        if isinstance(value, str):
            return [s for s in (x.strip() for x in value.split(",")) if s]
        return list(value) if isinstance(value, (list, tuple)) else default
    return value


def sanitize(defaults, data):
    out = {}
    for k, dv in defaults.items():
        if k not in data:
            out[k] = copy.deepcopy(dv)
        elif isinstance(dv, dict):
            sub = data[k] if isinstance(data[k], dict) else {}
            # 字典默认值为空或键不固定（如 budgets）时按键合并
            out[k] = sanitize(dv, sub) if dv else dict(sub)
        else:
            out[k] = _coerce(dv, data[k])
    return out


class Config:
    """设置存储：SQLite 为唯一真源，data/settings.json 只作为可读镜像（便于备份/查看）。

    启动时若数据库里还没有设置，会从 settings.json（或默认值）迁移一次；
    之后所有修改都先写数据库，再同步镜像文件，因此重启后一定恢复原样。
    """

    def __init__(self, path=paths.SETTINGS_PATH, db=None):
        self.path = path
        self.db = db
        self._lock = threading.RLock()
        self._listeners = []
        self.data = copy.deepcopy(DEFAULTS)
        self.source = "defaults"  # db / json / defaults
        self.load()

    # ---------------- 存储层 ----------------
    def _read_db(self):
        if self.db is None:
            return {}
        rows = self.db.query("SELECT key, value FROM settings WHERE key <> '__meta__'")
        out = {}
        for r in rows:
            try:
                out[r["key"]] = json.loads(r["value"])
            except (TypeError, ValueError):
                continue
        return out

    def _write_db(self):
        if self.db is None:
            return
        now = time.time()
        for sec, val in self.data.items():
            self.db.execute("INSERT INTO settings(key, value, updated_at) VALUES (?,?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                            (sec, json.dumps(val, ensure_ascii=False), now))
        self.db.execute("INSERT INTO settings(key, value, updated_at) VALUES ('__meta__', ?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                        (json.dumps({"app": APP_TAG, "at": now}, ensure_ascii=False), now))

    def _read_json(self):
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _write_json(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass  # 镜像写入失败不影响主流程（真源在数据库）

    # ---------------- 生命周期 ----------------
    def load(self):
        with self._lock:
            raw = self._read_db()
            if raw:
                self.source = "db"
            else:
                raw = self._read_json()
                self.source = "json" if raw else "defaults"
            self.data = sanitize(DEFAULTS, deep_merge(DEFAULTS, raw))
            self._write_db()      # 首次运行或迁移时落库
            self._write_json()

    def save(self):
        with self._lock:
            self._write_db()
            self._write_json()

    # ---------------- 读写 ----------------
    def get(self, dotted, default=None):
        cur = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def section(self, name):
        with self._lock:
            return copy.deepcopy(self.data.get(name, {}))

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self.data)

    def update(self, patch):
        """合并补丁并持久化，返回 {section: [changed keys]}。"""
        with self._lock:
            old = copy.deepcopy(self.data)
            self.data = sanitize(DEFAULTS, deep_merge(self.data, patch or {}))
            self.save()
            changed = {}
            for sec, val in self.data.items():
                if isinstance(val, dict):
                    keys = [k for k in val if old.get(sec, {}).get(k) != val[k]]
                    if keys:
                        changed[sec] = keys
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(changed)
            except Exception:  # 监听器异常不影响保存
                pass
        return changed

    def reset(self, section=None):
        if section:
            return self.update({section: copy.deepcopy(DEFAULTS.get(section, {}))})
        with self._lock:
            self.data = copy.deepcopy(DEFAULTS)
            self.save()
        return {k: list(v) for k, v in DEFAULTS.items() if isinstance(v, dict)}

    def on_change(self, fn):
        self._listeners.append(fn)
