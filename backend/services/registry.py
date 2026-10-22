"""分区与模型登记：分区 CRUD、扫描引擎模型、解析元数据、自动分类。"""
import os
import re
import time

from .. import paths
from ..core import gguf
from ..core.db import jdumps, jloads
from ..i18n import T

CATEGORY_RULES = [
    ("DeepSeek", r"deepseek"), ("千问 Qwen", r"qwen|qwq|qvq"), ("Llama", r"llama|codellama"),
    ("Gemma", r"gemma"), ("Mistral", r"mistral|mixtral|codestral|devstral|magistral"), ("Phi", r"\bphi"),
    ("GLM 智谱", r"glm|chatglm"), ("Yi 零一", r"\byi[-_:.\d]|^yi$"), ("InternLM 书生", r"internlm"),
    ("Baichuan 百川", r"baichuan"), ("MiniCPM", r"minicpm"), ("Kimi", r"kimi|moonshot"),
    ("GPT-OSS", r"gpt-oss|gptoss"), ("Granite", r"granite"), ("Command-R", r"command-r|cohere|aya"),
    ("SmolLM", r"smollm"), ("Falcon", r"falcon"), ("StarCoder", r"starcoder"), ("Hunyuan 混元", r"hunyuan"),
    ("Embedding", r"embed|bge|nomic|mxbai|e5-"), ("LLaVA 视觉", r"llava|bakllava|moondream"),
]

ARCH_CATEGORY = {"qwen": "千问 Qwen", "qwen2": "千问 Qwen", "qwen3": "千问 Qwen", "qwen35": "千问 Qwen",
                 "qwen3moe": "千问 Qwen", "qwen2moe": "千问 Qwen", "qwen2vl": "千问 Qwen", "qwen25vl": "千问 Qwen",
                 "deepseek2": "DeepSeek", "deepseek": "DeepSeek", "llama": "Llama", "llama4": "Llama",
                 "gemma": "Gemma", "gemma2": "Gemma", "gemma3": "Gemma", "gemma3n": "Gemma", "phi3": "Phi",
                 "phi2": "Phi", "glm4": "GLM 智谱", "chatglm": "GLM 智谱", "mistral3": "Mistral",
                 "gptoss": "GPT-OSS", "granite": "Granite", "command-r": "Command-R", "falcon": "Falcon",
                 "bert": "Embedding", "nomic-bert": "Embedding", "internlm2": "InternLM 书生", "minicpm": "MiniCPM"}

CATEGORIES = [c for c, _ in CATEGORY_RULES] + ["其他"]


def guess_category(*texts, arch=""):
    blob = " ".join(t for t in texts if t).lower()
    for cat, pat in CATEGORY_RULES:
        if re.search(pat, blob):
            return cat
    return ARCH_CATEGORY.get((arch or "").lower(), "其他")


def parse_params_label(label):
    m = re.match(r"^\s*([\d.]+)\s*([KMBT])", label or "", re.I)
    if not m:
        return None
    mul = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(2).upper()]
    return int(float(m.group(1)) * mul)


def normalize_name(name):
    """ollama 名称规范化：缺省 tag 补 :latest。"""
    name = (name or "").strip()
    if not name:
        return name
    last = name.rsplit("/", 1)[-1]
    if ":" not in last:
        name += ":latest"
    return name


class Registry:
    def __init__(self, db, engines, log, bus):
        self.db = db
        self.engines = engines
        self.log = log
        self.bus = bus
        self._ensure_default_partition()

    # ---------------- 分区 ----------------
    def _ensure_default_partition(self):
        if not self.db.one("SELECT id FROM partitions LIMIT 1"):
            os.makedirs(paths.DEFAULT_PARTITION_DIR, exist_ok=True)
            self.db.insert("partitions", {"name": "默认分区", "path": paths.DEFAULT_PARTITION_DIR, "color": "#34d399",
                                          "sort": 0, "is_default": 1, "created_at": time.time()})

    def partitions(self):
        rows = self.db.query("SELECT * FROM partitions ORDER BY sort, id")
        stats = {r["partition_id"]: r for r in self.db.query(
            "SELECT partition_id, COUNT(*) n, COALESCE(SUM(size),0) sz FROM models WHERE present=1 GROUP BY partition_id")}
        for r in rows:
            s = stats.get(r["id"], {})
            r["model_count"] = s.get("n", 0)
            r["total_size"] = s.get("sz", 0)
            r["exists"] = os.path.isdir(r["path"])
            try:
                import shutil
                du = shutil.disk_usage(r["path"] if r["exists"] else os.path.splitdrive(r["path"])[0] + "\\")
                r["disk_free"], r["disk_total"] = du.free, du.total
            except OSError:
                r["disk_free"] = r["disk_total"] = None
            e = self.engines.peek(r["id"])
            r["engine"] = e.info() if e else {"status": "stopped"}
        return rows

    def partition(self, pid):
        return self.db.one("SELECT * FROM partitions WHERE id=?", (pid,))

    def validate_path(self, path):
        path = os.path.abspath(os.path.expandvars(os.path.expanduser((path or "").strip().strip('"'))))
        if not path or len(path) < 4:
            raise ValueError(T("请填写有效的文件夹路径"))
        drive = os.path.splitdrive(path)[0]
        if drive and not os.path.exists(drive + "\\"):
            raise ValueError(T("磁盘 %s 不存在") % drive)
        return path

    def create_partition(self, name, path, color=""):
        name = (name or "").strip()
        if not name:
            raise ValueError(T("分区名称不能为空"))
        path = self.validate_path(path)
        if self.db.one("SELECT id FROM partitions WHERE lower(path)=lower(?)", (path,)):
            raise ValueError(T("该文件夹已被其他分区使用"))
        os.makedirs(path, exist_ok=True)
        sort = (self.db.scalar("SELECT MAX(sort) FROM partitions") or 0) + 1
        pid = self.db.insert("partitions", {"name": name, "path": path, "color": color or "#34d399", "sort": sort,
                                            "is_default": 0, "created_at": time.time()})
        self.log.ok("registry", T("新建分区「%s」→ %s") % (name, path))
        self.bus.publish("models_changed", {"partition_id": pid})
        return self.partition(pid)

    def update_partition(self, pid, data):
        p = self.partition(pid)
        if not p:
            raise KeyError(T("分区不存在"))
        upd = {}
        if "name" in data:
            if not str(data["name"]).strip():
                raise ValueError(T("分区名称不能为空"))
            upd["name"] = str(data["name"]).strip()
        if "color" in data:
            upd["color"] = str(data["color"])[:20]
        if "sort" in data:
            upd["sort"] = int(data["sort"])
        if "path" in data and data["path"] and os.path.normcase(self.validate_path(data["path"])) != os.path.normcase(p["path"]):
            newp = self.validate_path(data["path"])
            if self.db.one("SELECT id FROM partitions WHERE lower(path)=lower(?) AND id<>?", (newp, pid)):
                raise ValueError(T("该文件夹已被其他分区使用"))
            os.makedirs(newp, exist_ok=True)
            upd["path"] = newp
        self.db.update("partitions", pid, upd)
        if "path" in upd:
            self.engines.remove(pid)
            self.db.execute("UPDATE models SET present=0 WHERE partition_id=?", (pid,))
            self.sync(pid)
        elif "name" in upd:
            e = self.engines.peek(pid)
            if e:
                e.name = upd["name"]
        self.bus.publish("models_changed", {"partition_id": pid})
        return self.partition(pid)

    def delete_partition(self, pid, delete_files=False):
        p = self.partition(pid)
        if not p:
            raise KeyError(T("分区不存在"))
        if self.db.scalar("SELECT COUNT(*) FROM partitions") <= 1:
            raise ValueError(T("至少需要保留一个分区"))
        if delete_files:
            for m in self.db.query("SELECT name FROM models WHERE partition_id=? AND present=1", (pid,)):
                try:
                    self.engines.get(p).client.delete(m["name"])
                except Exception as e:
                    self.log.warn("registry", T("删除模型 %s 失败: %s") % (m["name"], e))
        self.engines.remove(pid)
        self.db.execute("DELETE FROM models WHERE partition_id=?", (pid,))
        self.db.execute("DELETE FROM partitions WHERE id=?", (pid,))
        if p["is_default"]:
            first = self.db.one("SELECT id FROM partitions ORDER BY sort, id LIMIT 1")
            if first:
                self.db.update("partitions", first["id"], {"is_default": 1})
        self.log.warn("registry", T("已删除分区「%s」") % p["name"])
        self.bus.publish("models_changed", {"partition_id": pid})

    # ---------------- 模型 ----------------
    def models(self, partition_id=None):
        sql = "SELECT m.*, p.name partition_name, p.color partition_color FROM models m JOIN partitions p ON p.id=m.partition_id WHERE m.present=1"
        args = []
        if partition_id:
            sql += " AND m.partition_id=?"
            args.append(partition_id)
        sql += " ORDER BY p.sort, p.id, m.favorite DESC, m.added_at DESC"
        rows = self.db.query(sql, args)
        for r in rows:
            r["capabilities"] = jloads(r["capabilities"], [])
            r["thinking_values"] = jloads(r["thinking_values"], None)
            meta = jloads(r.pop("meta_json"), {})
            mtp = meta.get("mtp") or {}
            r["mtp_tensor_count"] = mtp.get("tensors") or 0
            r["mtp_layers"] = mtp.get("layers")
            r["display_category"] = r["category"] or r["category_auto"] or "其他"
        return rows

    def model(self, mid):
        r = self.db.one("SELECT m.*, p.name partition_name, p.path partition_path FROM models m JOIN partitions p ON p.id=m.partition_id WHERE m.id=?", (mid,))
        if r:
            r["capabilities"] = jloads(r["capabilities"], [])
            r["thinking_values"] = jloads(r["thinking_values"], None)
            r["meta"] = jloads(r.pop("meta_json"), {})
            r["display_category"] = r["category"] or r["category_auto"] or "其他"
        return r

    def find(self, partition_id, name):
        return self.db.one("SELECT * FROM models WHERE partition_id=? AND name=? AND present=1", (partition_id, normalize_name(name)))

    def update_model(self, mid, data):
        upd = {}
        for k in ("remark", "category", "notes"):
            if k in data:
                upd[k] = str(data[k] or "")[:200 if k != "notes" else 4000]
        if "favorite" in data:
            upd["favorite"] = 1 if data["favorite"] else 0
        if "mtp_enabled" in data:
            upd["mtp_enabled"] = 1 if data["mtp_enabled"] else 0
        self.db.update("models", mid, upd)
        self.bus.publish("models_changed", {"model_id": mid})
        return self.model(mid)

    def delete_model(self, mid):
        m = self.model(mid)
        if not m:
            raise KeyError(T("模型不存在"))
        p = self.partition(m["partition_id"])
        eng = self.engines.get(p)
        try:
            eng.client.unload(m["name"], timeout=10)
        except Exception:
            pass
        try:
            eng.client.delete(m["name"])
        except Exception as e:
            if getattr(e, "status", None) != 404:
                raise
        self.db.execute("DELETE FROM models WHERE id=?", (mid,))
        self.log.warn("registry", T("已删除模型 %s") % m["name"])
        self.bus.publish("models_changed", {"partition_id": p["id"]})

    def sync(self, partition_id=None, deep=False):
        """以引擎 /api/tags 为准同步数据库。"""
        parts = [self.partition(partition_id)] if partition_id else self.db.query("SELECT * FROM partitions")
        total = 0
        for p in parts:
            if not p or not os.path.isdir(p["path"]):
                continue
            try:
                # 全局同步只处理「已运行」的引擎：peek 不创建、不启动引擎
                eng = self.engines.peek(p["id"])
                if eng is None or not eng.alive() or eng.status != "running":
                    continue
                tags = eng.client.tags()
            except Exception as e:
                self.log.warn("registry", T("同步分区「%s」失败: %s") % (p["name"], e))
                continue
            names = set()
            for t in tags:
                names.add(t["name"])
                exist = self.db.one("SELECT * FROM models WHERE partition_id=? AND name=?", (p["id"], t["name"]))
                if exist and exist["present"] and exist["digest"] == t.get("digest") and not deep and exist["arch"]:
                    continue
                self._upsert_from_engine(p, eng, t, exist)
                total += 1
            for r in self.db.query("SELECT id, name FROM models WHERE partition_id=? AND present=1", (p["id"],)):
                if r["name"] not in names:
                    self.db.execute("UPDATE models SET present=0 WHERE id=?", (r["id"],))
        self.bus.publish("models_changed", {})
        return total

    def _upsert_from_engine(self, p, eng, tag, exist, source=None, source_path=None, extra=None):
        name = tag["name"]
        details = tag.get("details") or {}
        try:
            show = eng.client.show(name)
        except Exception:
            show = {}
        mi = show.get("model_info") or {}
        arch = mi.get("general.architecture") or details.get("family") or ""
        ctx = mi.get("%s.context_length" % arch) if arch else None
        if ctx is None:
            ctx = details.get("context_length")
        params = mi.get("general.parameter_count") or parse_params_label(details.get("parameter_size"))
        blob = ""
        for line in (show.get("modelfile") or "").splitlines():
            if line.startswith("FROM ") and "blobs" in line:
                blob = line[5:].strip()
                break
        if blob and os.path.isfile(blob) and (not params or ctx is None or True):
            try:
                s = gguf.summarize(gguf.read_gguf(blob))
                params = params or s["param_count"]
                ctx = ctx if ctx is not None else s["context_length"]
            except Exception:
                s = {}
        else:
            s = {}
        # MTP 识别：GGUF 里有 mtp.*/nextn.* 张量或显式元数据键；引擎 /api/show 也可能上报
        mtp_tensors = (s or {}).get("mtp_tensor_count") or 0
        mtp_layers = (s or {}).get("mtp_layers")
        if not mtp_tensors:
            mtp_keys = [k for k in mi if "nextn" in k.lower() or "mtp" in k.lower()]
            mtp_layers = mtp_layers or next((mi[k] for k in mtp_keys if isinstance(mi[k], int)), None)
            mtp_tensors = len(mtp_keys) or (1 if mtp_layers else 0)
        caps = show.get("capabilities") or tag.get("capabilities") or []
        th = show.get("thinking")
        meta = {"details": details, "parameters": show.get("parameters") or "", "license": (show.get("license") or "")[:3000],
                "template": (show.get("template") or "")[:6000], "model_info": {k: (v if not isinstance(v, list) or len(v) < 40 else "[%d 项]" % len(v))
                                                                                   for k, v in mi.items() if not k.startswith("tokenizer.ggml")},
                "projector": bool(show.get("projector_info")), "modelfile_from": blob,
                "mtp": {"tensors": mtp_tensors, "layers": mtp_layers,
                        "native_keys": [k for k in mi if "nextn" in k.lower() or "mtp" in k.lower()][:8]}}
        if extra:
            meta.update(extra)
        auto_cat = guess_category(name, mi.get("general.basename") or "", mi.get("general.name") or "", arch=arch)
        import datetime
        try:
            mod = datetime.datetime.fromisoformat(tag.get("modified_at", "").replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            mod = time.time()
        row = {
            "family": details.get("family") or arch, "arch": arch, "params": int(params) if params else None,
            "params_label": details.get("parameter_size") or gguf.format_params(params),
            "quant": details.get("quantization_level") or "", "size": int(tag.get("size") or 0),
            "context_length": int(ctx) if ctx else None, "capabilities": jdumps(caps),
            "thinking_values": jdumps(th) if th else "", "digest": tag.get("digest") or "",
            "blob_path": blob, "modified_at": mod, "meta_json": jdumps(meta), "category_auto": auto_cat, "present": 1,
            "has_mtp": 1 if (mtp_layers or mtp_tensors) else 0,
        }
        if source:
            row["source"] = source
        if source_path:
            row["source_path"] = source_path
        if exist:
            self.db.update("models", exist["id"], row)
            return exist["id"]
        row.update({"partition_id": p["id"], "name": name, "added_at": time.time(),
                    "source": source or "existing", "source_path": source_path or ""})
        return self.db.insert("models", row)

    def register(self, partition_id, name, source, source_path="", remark="", extra=None):
        p = self.partition(partition_id)
        eng = self.engines.get(p)
        name = normalize_name(name)
        tag = next((t for t in eng.client.tags() if t["name"] == name), None)
        if not tag:
            raise RuntimeError(T("引擎中未找到模型 %s") % name)
        exist = self.db.one("SELECT * FROM models WHERE partition_id=? AND name=?", (partition_id, name))
        mid = self._upsert_from_engine(p, eng, tag, exist, source=source, source_path=source_path, extra=extra)
        upd = {"added_at": time.time()}
        if remark:
            upd["remark"] = remark
        self.db.update("models", mid, upd)
        self.bus.publish("models_changed", {"partition_id": partition_id})
        return self.model(mid)

    def grouped(self):
        """首页模型切换器：按分区分组。"""
        out = []
        models = self.models()
        for p in self.db.query("SELECT * FROM partitions ORDER BY sort, id"):
            items = [m for m in models if m["partition_id"] == p["id"]]
            out.append({"id": p["id"], "name": p["name"], "color": p["color"], "models": items})
        return out
