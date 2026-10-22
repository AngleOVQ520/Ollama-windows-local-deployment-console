"""后台任务：从 Ollama 拉取模型（ollama pull/run 到指定分区）、导入本地 GGUF。

导入 GGUF 时优先使用硬链接（同盘、零拷贝、秒级完成），跨盘时复制并显示进度。
"""
import hashlib
import os
import re
import shutil
import threading
import time
import uuid

from ..core import gguf
from .. import paths
from ..i18n import T
from .registry import guess_category, normalize_name


def _non_ascii(s):
    return any(ord(c) > 127 for c in s or "")


class Job:
    def __init__(self, kind, partition_id, target, label=""):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind  # pull / import
        self.partition_id = partition_id
        self.target = target
        self.label = label or target
        self.status = "queued"  # queued/running/done/error/cancelled
        self.stage = T("排队中")
        self.completed = 0
        self.total = 0
        self.speed = 0.0
        self.eta = None
        self.message = ""
        self.created_at = time.time()
        self.finished_at = None
        self.cancel_evt = threading.Event()
        self.resp = None
        self.layers = {}
        self.model_id = None

    def to_dict(self):
        pct = (self.completed / self.total * 100) if self.total else (100.0 if self.status == "done" else 0.0)
        return {"id": self.id, "kind": self.kind, "partition_id": self.partition_id, "target": self.target,
                "label": self.label, "status": self.status, "stage": self.stage, "completed": self.completed,
                "total": self.total, "percent": round(pct, 2), "speed": self.speed, "eta": self.eta,
                "message": self.message, "created_at": self.created_at, "finished_at": self.finished_at,
                "model_id": self.model_id}


class JobService:
    def __init__(self, db, registry, engines, log, bus):
        self.db = db
        self.registry = registry
        self.engines = engines
        self.log = log
        self.bus = bus
        self.jobs = {}
        self._lock = threading.Lock()

    def list(self):
        return [j.to_dict() for j in sorted(self.jobs.values(), key=lambda j: -j.created_at)]

    def _emit(self, job, force=False):
        now = time.time()
        if not force and now - getattr(job, "_last_emit", 0) < 0.25:
            return
        job._last_emit = now
        self.bus.publish("job", job.to_dict())

    def _finish(self, job, status, msg=""):
        job.status = status
        job.message = msg
        job.finished_at = time.time()
        job.speed = 0
        job.eta = None
        if status == "done":
            job.stage = T("完成")
        elif status == "cancelled":
            job.stage = T("已取消")
        else:
            job.stage = T("失败")
        self.db.execute("INSERT OR REPLACE INTO jobs(id, kind, partition_id, target, status, message, created_at, finished_at) VALUES (?,?,?,?,?,?,?,?)",
                        (job.id, job.kind, job.partition_id, job.target, status, msg, job.created_at, job.finished_at))
        self._emit(job, force=True)

    def cancel(self, jid):
        j = self.jobs.get(jid)
        if not j:
            raise KeyError(T("任务不存在"))
        j.cancel_evt.set()
        if j.resp is not None:
            try:
                j.resp.close()
            except Exception:
                pass
        return j.to_dict()

    def clear(self):
        with self._lock:
            for k in [k for k, j in self.jobs.items() if j.status in ("done", "error", "cancelled")]:
                self.jobs.pop(k, None)

    def _speed(self, job, samples):
        now = time.time()
        samples.append((now, job.completed))
        while samples and now - samples[0][0] > 4:
            samples.pop(0)
        if len(samples) >= 2 and samples[-1][0] > samples[0][0]:
            job.speed = max(0.0, (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0]))
            job.eta = (job.total - job.completed) / job.speed if job.speed > 0 and job.total else None

    # ---------------- 拉取 ----------------
    def start_pull(self, partition_id, model, remark=""):
        model = (model or "").strip()
        for prefix in ("ollama run ", "ollama pull "):
            if model.lower().startswith(prefix):
                model = model[len(prefix):].strip()
        model = model.split()[0] if model else ""
        if not model:
            raise ValueError(T("请输入模型 ID，例如 qwen3.5:2b"))
        p = self.registry.partition(partition_id)
        if not p:
            raise KeyError(T("分区不存在"))
        for j in self.jobs.values():
            if j.status in ("queued", "running") and j.partition_id == partition_id and j.target == normalize_name(model):
                raise ValueError(T("该模型正在下载中"))
        job = Job("pull", partition_id, normalize_name(model), label=model)
        job.remark = remark
        self.jobs[job.id] = job
        self._emit(job, force=True)
        threading.Thread(target=self._run_pull, args=(job, p), daemon=True).start()
        return job.to_dict()

    def _run_pull(self, job, p):
        job.status = "running"
        job.stage = T("启动引擎")
        self._emit(job, force=True)
        self.log.info("pull", T("开始拉取 %s → 分区「%s」") % (job.target, p["name"]))
        try:
            eng = self.engines.get(p)
            if eng.status != "running":
                raise RuntimeError(eng.error or T("引擎未就绪"))
            job.stage = T("获取清单")
            self._emit(job, force=True)
            resp, it = eng.client.stream("/api/pull", {"model": job.target, "stream": True}, timeout=(10, 120))
            job.resp = resp
            samples = []
            for d in it:
                if job.cancel_evt.is_set():
                    break
                st = d.get("status", "")
                if d.get("digest") and d.get("total"):
                    job.layers[d["digest"]] = (d.get("completed") or 0, d["total"])
                    job.total = sum(t for _, t in job.layers.values())
                    job.completed = sum(c for c, _ in job.layers.values())
                    job.stage = T("下载中 %s") % d["digest"][7:19]
                    self._speed(job, samples)
                elif st:
                    job.stage = {"pulling manifest": T("获取清单"), "verifying sha256 digest": T("校验数据"),
                                 "writing manifest": T("写入清单"), "removing any unused layers": T("清理旧层"),
                                 "success": T("完成")}.get(st, st)
                self._emit(job)
                if st == "success":
                    break
            resp.close()
            if job.cancel_evt.is_set():
                self._finish(job, "cancelled", T("用户取消（已下载部分会保留，再次下载可续传）"))
                self.log.warn("pull", T("已取消 %s") % job.target)
                return
            job.completed = job.total
            m = self.registry.register(p["id"], job.target, "ollama", remark=getattr(job, "remark", ""))
            job.model_id = m["id"]
            self._finish(job, "done", T("已安装到 %s") % p["path"])
            self.log.ok("pull", T("%s 下载完成") % job.target)
        except Exception as e:
            if job.cancel_evt.is_set():
                self._finish(job, "cancelled", T("用户取消（已下载部分会保留，再次下载可续传）"))
                return
            msg = str(e)
            if "file does not exist" in msg or "not found" in msg.lower():
                msg = T("Ollama 仓库中不存在该模型：%s") % job.target
            self._finish(job, "error", msg)
            self.log.error("pull", T("%s 下载失败: %s") % (job.target, msg))

    # ---------------- 导入 GGUF ----------------
    def inspect_gguf(self, path):
        path = os.path.abspath((path or "").strip().strip('"'))
        if not os.path.isfile(path):
            raise ValueError(T("文件不存在"))
        info = gguf.read_gguf(path)
        s = gguf.summarize(info)
        s["path"] = path
        s["file_size"] = os.path.getsize(path)
        s["suggest_name"] = suggest_model_name(path, s)
        s["category"] = guess_category(os.path.basename(path), s["name"], s["basename"], arch=s["architecture"])
        s["exists"] = bool(self.registry.db.one("SELECT id FROM models WHERE source_path=? AND present=1", (path,)))
        s["params_label"] = s["size_label"] or gguf.format_params(s["param_count"])
        return s

    def suggest_import_name(self, partition_id, path, summary, name=None):
        """导入建议：未指定名称时按文件名生成并查重；返回 (模型名, 备注名)。

        纯中文文件名规范化后会丢信息，用原文件名短哈希保证可辨识且唯一；
        同分区已有同名模型时自动追加序号，避免静默覆盖。
        """
        p = self.registry.partition(partition_id)
        if not p:
            raise KeyError(T("分区不存在"))
        bank = self._name_bank(p)
        if name:
            base = normalize_name(sanitize_model_name(name))
            if base in bank:
                raise ValueError(T("该分区已有同名模型 %s，请确认覆盖或换一个名字") % base)
            return base, ""
        base = normalize_name(sanitize_model_name(suggest_model_name(path, summary)))
        disp = os.path.splitext(os.path.basename(path))[0]
        # 纯中文名规范化后仅剩参数量/量化，再追加原文件名短哈希便于区分
        if _non_ascii(os.path.splitext(os.path.basename(path))[0]):
            short = hashlib.sha1(os.path.basename(path).encode("utf-8")).hexdigest()[:6]
            if short not in base:
                base = "%s-%s%s" % (base.partition(":")[0], short, base[len(base.partition(":")[0]):])
        m = re.match(r"^(.*?)(?::([^:]+))$", base)
        stem, tag = (m.group(1), m.group(2)) if m else (base, "latest")
        uniq, i = base, 2
        while uniq in bank:
            uniq = "%s-%d:%s" % (stem, i, tag)
            i += 1
        return uniq, disp

    def _name_bank(self, p):
        """同分区已占用的名称：引擎现有模型 + 库中记录 + 排队/运行中的导入。"""
        bank = set()
        eng = self.engines.peek(p["id"])
        if eng is not None and eng.alive() and eng.status == "running":
            try:
                bank.update(t["name"] for t in eng.client.tags())
            except Exception:
                pass
        for r in self.registry.db.query("SELECT name FROM models WHERE partition_id=?", (p["id"],)):
            bank.add(r["name"])
        bank.update(j.target for j in self.jobs.values()
                    if j.kind == "import" and j.partition_id == p["id"] and j.status in ("queued", "running"))
        return bank

    def start_import(self, partition_id, path, name, remark="", category="", mode="auto", options=None, confirm_overwrite=False):
        p = self.registry.partition(partition_id)
        if not p:
            raise KeyError(T("分区不存在"))
        path = os.path.abspath((path or "").strip().strip('"'))
        if not os.path.isfile(path):
            raise ValueError(T("GGUF 文件不存在"))
        try:
            gguf.read_gguf(path, with_tensors=False)
        except Exception as e:
            raise ValueError(T("不是有效的 GGUF 文件：%s") % e)
        name = normalize_name(sanitize_model_name(name or suggest_model_name(path, {})))
        if name in self._name_bank(p):
            if not confirm_overwrite:
                raise ValueError(T("该分区已有同名模型 %s，请确认覆盖或换一个名字") % name)
            # 明确确认覆盖：先删掉旧定义，避免引擎侧覆盖后旧权重变成孤儿文件
            old = self.registry.find(p["id"], name)
            if old:
                self.registry.delete_model(old["id"])
                self.log.warn("import", T("已覆盖同名模型 %s") % name)
        job = Job("import", partition_id, name, label=os.path.basename(path))
        job.src = path
        job.remark = remark or os.path.splitext(os.path.basename(path))[0]
        job.category = category
        job.mode = mode
        job.options = options or {}
        job.overwrite = bool(confirm_overwrite)
        self.jobs[job.id] = job
        self._emit(job, force=True)
        threading.Thread(target=self._run_import, args=(job, p), daemon=True).start()
        return job.to_dict()

    def _run_import(self, job, p):
        job.status = "running"
        self.log.info("import", T("导入 %s → 分区「%s」为 %s") % (job.src, p["name"], job.target))
        blobs = os.path.join(p["path"], "blobs")
        dst = None
        created = False  # 本次新建（而非复用）的 blob 才能回滚，避免误删其它模型共享的权重
        created_model = False
        # 拖拽上传的临时文件：成功后（硬链接）删除，失败时也必须删掉，不能留在临时目录
        src = os.path.normcase(os.path.normpath(job.src))
        uploaded = src.startswith(os.path.normcase(os.path.normpath(os.path.join(paths.TMP_DIR, "uploads"))) + os.sep)
        try:
            eng = self.engines.get(p)
            if eng.status != "running":
                raise RuntimeError(eng.error or T("引擎未就绪"))
            size = os.path.getsize(job.src)
            # 1) 计算 sha256
            job.stage = T("计算校验值")
            job.total = size
            job.completed = 0
            samples = []
            h = hashlib.sha256()
            with open(job.src, "rb") as f:
                while True:
                    if job.cancel_evt.is_set():
                        return self._finish(job, "cancelled", T("用户取消"))
                    b = f.read(16 << 20)
                    if not b:
                        break
                    h.update(b)
                    job.completed += len(b)
                    self._speed(job, samples)
                    self._emit(job)
            digest = "sha256:" + h.hexdigest()
            os.makedirs(blobs, exist_ok=True)
            dst = os.path.join(blobs, digest.replace(":", "-"))
            # 2) 放入分区 blobs（硬链接 > 复制）
            if not (os.path.isfile(dst) and os.path.getsize(dst) == size):
                linked = False
                if job.mode in ("auto", "link"):
                    try:
                        os.link(job.src, dst)
                        linked = True
                        created = True
                        job.stage = T("已硬链接（零拷贝）")
                    except OSError:
                        if job.mode == "link":
                            raise RuntimeError(T("无法创建硬链接（源文件与分区不在同一磁盘）"))
                if not linked:
                    job.stage = T("复制到分区")
                    job.completed = 0
                    samples = []
                    tmp = dst + ".partial"
                    with open(job.src, "rb") as fi, open(tmp, "wb") as fo:
                        while True:
                            if job.cancel_evt.is_set():
                                fo.close()
                                os.remove(tmp)
                                return self._finish(job, "cancelled", T("用户取消"))
                            b = fi.read(16 << 20)
                            if not b:
                                break
                            fo.write(b)
                            job.completed += len(b)
                            self._speed(job, samples)
                            self._emit(job)
                    os.replace(tmp, dst)
                    created = True
            job.completed = job.total
            # 3) 创建模型
            job.stage = T("创建模型")
            self._emit(job, force=True)
            body = {"model": job.target, "files": {os.path.basename(job.src): digest}, "stream": True}
            opts = {k: v for k, v in (job.options or {}).items() if v not in (None, "", [])}
            if opts.get("system"):
                body["system"] = opts.pop("system")
            if opts.get("template"):
                body["template"] = opts.pop("template")
            if opts:
                body["parameters"] = opts
            resp, it = eng.client.stream("/api/create", body, timeout=(10, 900))
            created_model = True  # create 一旦成功，引擎里就已有同名定义，失败后需要撤销
            for d in it:
                job.stage = {"parsing GGUF": T("解析 GGUF"), "writing manifest": T("写入清单"), "success": T("完成")}.get(d.get("status"), d.get("status") or job.stage)
                self._emit(job)
            resp.close()
            m = self.registry.register(p["id"], job.target, "gguf",
                                       source_path=("" if uploaded else job.src), remark=job.remark)
            if job.category:
                self.registry.update_model(m["id"], {"category": job.category})
            job.model_id = m["id"]
            self._finish(job, "done", T("已导入到分区「%s」") % p["name"])
            self.log.ok("import", T("GGUF 导入完成：%s") % job.target)
        except Exception as e:
            self._rollback_import(job, p, dst, created, created_model)
            self._finish(job, "error", str(e))
            self.log.error("import", T("导入失败：%s") % e)
        finally:
            if uploaded:
                try:
                    os.remove(job.src)
                except OSError:
                    pass

    def _rollback_import(self, job, p, dst, created, created_model):
        """失败回滚：撤销本次创建的模型与本次新建的 blob，不碰共享 blob 与历史孤儿。"""
        if created_model:
            try:
                eng = self.engines.get(p)
                eng.client.delete(job.target)
            except Exception:
                pass
        if created and dst and os.path.isfile(dst):
            try:
                os.remove(dst)
                self.log.warn("import", T("已回滚本次导入的 blob"))
            except OSError as e:
                self.log.warn("import", T("回滚 blob 失败: %s") % e)


def sanitize_model_name(name):
    name = (name or "").strip().lower()
    base, _, tag = name.partition(":")
    if _non_ascii(base):
        base = re.sub(r"[^a-z0-9._/\-]+", "-", base).strip("-._/")
        # 纯中文名规范化后只剩标点，信息全丢：用原文件名短哈希作为稳定且唯一的标识
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:6] if not base else None
        base = (base + "-" + digest) if digest else base
    else:
        base = re.sub(r"[^a-z0-9._/\-]+", "-", base).strip("-._/")
    base = base or "model"
    tag = re.sub(r"[^a-z0-9._\-]+", "-", tag).strip("-.") if tag else ""
    return base + (":" + tag if tag else "")


def suggest_model_name(path, summary):
    stem = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r"[-_.]((?:IQ|Q|F|BF)\d[\w]*)$", stem, re.I)
    if m:
        base, tag = stem[:m.start()], m.group(1)
    else:
        base, tag = stem, (summary.get("file_type") or "latest")
    return sanitize_model_name("%s:%s" % (base, tag))
