"""生图服务：封装 stable-diffusion.cpp（sd-cli.exe）子进程。

能力：文生图、图生图（参考图 / 参考图 + 指令编辑、多参考图）。
说明：Ollama/llama.cpp 只支持语言模型，Qwen-Image 这类扩散模型必须由
stable-diffusion.cpp 推理，因此这里独立管理一个子进程，不与 Ollama 引擎混用。
"""
import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

from .. import paths
from ..i18n import T

SD_BIN = os.path.join(paths.SDCPP_DIR, "bin")
SD_CUDA = os.path.join(paths.SDCPP_DIR, "cuda")
SD_CLI = os.path.join(SD_BIN, "sd-cli.exe")

CREATE_NO_WINDOW = 0x08000000

# 采样进度：|====>| 3/24 - 3.2s/it（快于 1s/步时引擎会写成 5.16it/s）
RE_SAMPLE = re.compile(r"\|\s*(\d+)/(\d+)\s*-\s*([\d.]+)\s*s/it")
RE_SAMPLE_IPS = re.compile(r"\|\s*(\d+)/(\d+)\s*-\s*([\d.]+)\s*it/s")
# 解码进度：|####>| 32/128 - 12.8MB/s
RE_DECODE = re.compile(r"\|\s*(\d+)/(\d+)\s*-\s*([\d.]+)\s*MB/s")
RE_SAVED = re.compile(r"save result image \d+ to '([^']+)'")


def _guess_kind(name):
    low = name.lower()
    if "vae" in low:
        return "vae"
    if "mmproj" in low or "vision" in low:
        return "vision"
    if "text_encoder" in low or "text-encoder" in low or "qwen3vl" in low or "qwen3.5" in low or "llm" in low:
        return "llm"
    return "diffusion"


def _human(n):
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return ""


class ImageGenService:
    def __init__(self, db, config, loader, log, bus):
        self.db = db
        self.config = config
        self.loader = loader
        self.log = log
        self.bus = bus
        self.jobs = {}          # 内存中的活动/近期任务
        self._queue = []
        self._lock = threading.RLock()
        self._worker = None
        self._proc = None
        self._current = None
        self._cancel = set()
        paths.ensure_dirs()

    # ---------------- 环境与资产 ----------------
    def engine(self):
        ok = os.path.isfile(SD_CLI)
        return {"available": ok, "cli": SD_CLI if ok else "",
                "cuda": os.path.isdir(SD_CUDA),
                "version": self._version() if ok else ""}

    def _version(self):
        try:
            p = subprocess.run([SD_CLI, "--help"], capture_output=True, timeout=20,
                               creationflags=CREATE_NO_WINDOW)
            head = (p.stdout or p.stderr).decode("utf-8", errors="replace").splitlines()
            return head[0].strip() if head else ""
        except Exception:
            return ""

    def assets(self):
        """扫描 models/image 下的生图资产（扩散模型 / VAE / 文本编码器 / 视觉投影）。"""
        out = []
        for p in sorted(glob.glob(os.path.join(paths.IMAGE_ASSET_DIR, "*"))):
            if not os.path.isfile(p) or not p.lower().endswith((".gguf", ".safetensors", ".ckpt", ".pt")):
                continue
            out.append({"path": p, "name": os.path.basename(p), "kind": _guess_kind(os.path.basename(p)),
                        "size": os.path.getsize(p), "size_label": _human(os.path.getsize(p))})
        # 项目根目录下用户直接放入的扩散模型也算候选
        for p in sorted(glob.glob(os.path.join(paths.ROOT, "*.gguf"))):
            if "image" in os.path.basename(p).lower() or "qwen_image" in os.path.basename(p).lower():
                out.append({"path": p, "name": os.path.basename(p), "kind": "diffusion",
                            "size": os.path.getsize(p), "size_label": _human(os.path.getsize(p))})
        return out

    def _pick(self, want, assets, prefer_kind=None):
        val = (self.config.get("image.%s" % want) or "").strip()
        if val and os.path.isfile(val):
            return val
        cands = [a for a in assets if a["kind"] == prefer_kind] if prefer_kind else []
        if not cands:
            return ""
        # VAE / vision 只有一个时直接选；文本编码器优先最小的（省显存）
        if prefer_kind == "llm":
            multi = [a for a in cands if a["name"].lower().endswith(".gguf")]
            return (multi or cands)[0]["path"]
        return cands[0]["path"]

    def resolve(self):
        assets = self.assets()
        r = {
            "diffusion_model": self._pick("diffusion_model", assets, "diffusion"),
            "vae": self._pick("vae", assets, "vae"),
            "llm": self._pick("llm", assets, "llm"),
            "llm_vision": self._pick("llm_vision", assets, "vision"),
        }
        missing = [k for k, v in r.items() if not v and k != "llm_vision"]
        return r, missing, assets

    def status(self):
        r, missing, assets = self.resolve()
        return {"engine": self.engine(), "resolved": r, "missing": missing, "assets": assets,
                "active": self._current["id"] if self._current else "",
                "queue": len(self._queue) + (1 if self._current else 0)}

    # ---------------- 任务 ----------------
    def list_jobs(self, limit=40):
        rows = self.db.query("SELECT * FROM image_jobs ORDER BY created_at DESC LIMIT ?", (int(limit),))
        return [self._row_out(r) for r in rows]

    def get_job(self, jid):
        live = self.jobs.get(jid)
        if live:
            return live
        r = self.db.one("SELECT * FROM image_jobs WHERE id=?", (jid,))
        return self._row_out(r) if r else None

    @staticmethod
    def _row_out(r):
        if not r:
            return None
        out = dict(r)
        out["params"] = json.loads(out.pop("params_json") or "{}")
        out["refs"] = json.loads(out.pop("refs_json") or "[]")
        out["outputs"] = json.loads(out.pop("outputs_json") or "[]")
        return out

    def submit(self, payload):
        if not self.config.get("image.enabled", True):
            raise ValueError(T("生图功能已在设置中关闭"))
        if not os.path.isfile(SD_CLI):
            raise ValueError(T("未找到生图引擎 sd-cli.exe（runtime/sdcpp/bin）"))
        prompt = (payload.get("prompt") or "").strip()
        if not prompt:
            raise ValueError(T("提示词不能为空"))
        r, missing, _ = self.resolve()
        if missing:
            raise ValueError(T("缺少生图资产：%s（请放到 models/image 目录）") % "、".join(missing))
        refs = [p for p in (payload.get("refs") or []) if p and os.path.isfile(p)]
        if refs and not r["llm_vision"]:
            raise ValueError(T("图生图需要视觉投影模型（mmproj-*.gguf），请放到 models/image 目录"))

        p = self.config.section("image")
        width = self._clamp(int(payload.get("width") or p["width"]), 256, 2048)
        height = self._clamp(int(payload.get("height") or p["height"]), 256, 2048)
        # 扩散模型要求边长是 32 的倍数
        width, height = width // 32 * 32, height // 32 * 32
        seed = int(payload.get("seed", p["seed"]))
        if seed < 0:
            seed = int(time.time() * 1000) % 2147483647

        job = {
            "id": uuid.uuid4().hex[:12],
            "kind": "edit" if refs else "t2i",
            "prompt": prompt,
            "negative": (payload.get("negative") or "").strip(),
            "refs": refs,
            "params": {
                "width": width, "height": height,
                "steps": self._clamp(int(payload.get("steps") or p["steps"]), 1, 100),
                "cfg_scale": float(payload.get("cfg_scale", p["cfg_scale"])),
                "seed": seed,
                "sampling": payload.get("sampling") or p["sampling"],
                "scheduler": payload.get("scheduler", p["scheduler"]) or "",
                "flow_shift": float(payload.get("flow_shift", p["flow_shift"])),
                "batch": self._clamp(int(payload.get("batch") or p["batch"]), 1, 4),
                "strength": float(payload.get("strength", p["strength"])),
                "img_cfg_scale": float(payload.get("img_cfg_scale", p["img_cfg_scale"])),
                "guidance": float(payload.get("guidance", p["guidance"])),
                "slg_scale": float(payload.get("slg_scale", p["slg_scale"])),
                "clip_skip": self._clamp(int(payload.get("clip_skip") or p["clip_skip"]), 1, 12),
                "preview": payload.get("preview") or p["preview"] or "none",
                "vae_tiling": bool(payload.get("vae_tiling", p["vae_tiling"])),
                "diffusion_model": r["diffusion_model"], "vae": r["vae"], "llm": r["llm"],
                "llm_vision": r["llm_vision"],
            },
            "status": "queued", "stage": T("排队中"), "progress": 0, "step": 0, "total_steps": 0,
            "it_s": 0, "eta_s": 0, "outputs": [], "error": "", "log_tail": [],
            "created_at": time.time(), "started_at": 0, "finished_at": 0, "elapsed_ms": 0,
        }
        self.db.insert("image_jobs", {
            "id": job["id"], "kind": job["kind"], "prompt": job["prompt"], "negative": job["negative"],
            "params_json": json.dumps(job["params"], ensure_ascii=False),
            "refs_json": json.dumps(job["refs"], ensure_ascii=False), "outputs_json": "[]",
            "status": "queued", "stage": T("排队中"), "created_at": job["created_at"],
        })
        with self._lock:
            self.jobs[job["id"]] = job
            self._queue.append(job["id"])
            if not self._worker or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._loop, daemon=True)
                self._worker.start()
        self._emit(job)
        return job

    def cancel(self, jid):
        with self._lock:
            self._cancel.add(jid)
            if jid in self._queue:
                self._queue.remove(jid)
                job = self.jobs.get(jid)
                if job:
                    job["status"] = "cancelled"
                    job["stage"] = T("已取消")
                    self._finish(job)
                return True
        if self._current and self._current["id"] == jid and self._proc:
            self._current["log_tail"].append(T("收到取消请求，正在终止…"))
            try:
                self._proc.terminate()
            except OSError:
                pass
            return True
        return False

    def delete(self, jid):
        job = self.jobs.get(jid)
        if job and job["status"] == "running":
            raise ValueError(T("任务正在运行，请先取消"))
        for o in (job or {}).get("outputs", []):
            f = o.get("file")
            if f and os.path.isfile(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        row = self.db.one("SELECT outputs_json FROM image_jobs WHERE id=?", (jid,))
        if row:
            for o in json.loads(row["outputs_json"] or "[]"):
                f = o.get("file")
                if f and os.path.isfile(f):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
        self.db.execute("DELETE FROM image_jobs WHERE id=?", (jid,))
        self.jobs.pop(jid, None)
        return True

    # ---------------- 执行 ----------------
    @staticmethod
    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))

    def _loop(self):
        while True:
            with self._lock:
                if not self._queue:
                    self._worker = None
                    return
                jid = self._queue.pop(0)
                if jid in self._cancel:
                    self._cancel.discard(jid)
                    continue
                job = self.jobs.get(jid)
            if not job:
                continue
            try:
                self._run(job)
            except Exception as e:  # 兜底：任何异常都要让任务收尾
                job["status"] = "error"
                job["error"] = str(e)
                job["stage"] = T("失败")
                self.log.error("image", T("生图失败：%s") % e)
                self._finish(job)

    def _run(self, job):
        p = job["params"]
        outdir = os.path.join(paths.IMAGE_OUT_DIR, job["id"])
        os.makedirs(outdir, exist_ok=True)
        n = p["batch"]
        outfile = os.path.join(outdir, "out-%d.png") if n > 1 else os.path.join(outdir, "out.png")

        # 显存不足时 Ollama 模型与扩散模型无法共存，按设置先卸载
        if self.config.get("image.unload_llm", True):
            st = self.loader.state
            if getattr(st, "status", "") == "loaded":
                self.log.info("image", T("生图前卸载当前语言模型以释放显存"))
                try:
                    self.loader.unload()
                except Exception as e:
                    self.log.warn("image", T("卸载模型失败：%s") % e)

        args = [SD_CLI, "--diffusion-model", p["diffusion_model"], "--vae", p["vae"], "--llm", p["llm"]]
        if job["refs"]:
            args += ["--llm_vision", p["llm_vision"]]
            for r in job["refs"]:
                args += ["-r", r]
        args += ["-p", job["prompt"]]
        if job["negative"]:
            args += ["-n", job["negative"]]
        args += ["--cfg-scale", str(p["cfg_scale"]), "--sampling-method", p["sampling"],
                 "-W", str(p["width"]), "-H", str(p["height"]), "--steps", str(p["steps"]),
                 "--seed", str(p["seed"]), "-o", outfile]
        if p["scheduler"]:
            args += ["--scheduler", p["scheduler"]]
        if p["flow_shift"]:
            args += ["--flow-shift", str(p["flow_shift"])]
        if p["guidance"]:
            args += ["--guidance", str(p["guidance"])]
        if p["slg_scale"]:
            args += ["--slg-scale", str(p["slg_scale"])]
        if p["clip_skip"] and p["clip_skip"] > 1:
            args += ["--clip-skip", str(p["clip_skip"])]
        if job["refs"]:
            if p["img_cfg_scale"]:
                args += ["--img-cfg-scale", str(p["img_cfg_scale"])]
            if p["strength"] and p["strength"] < 1.0:
                args += ["--strength", str(p["strength"])]
        if p["preview"] and p["preview"] != "none":
            args += ["--preview", p["preview"], "--preview-path",
                     os.path.join(outdir, "preview.png"), "--preview-interval", "1"]
        if p["vae_tiling"]:
            args.append("--vae-tiling")
        if n > 1:
            args += ["-b", str(n)]
        if self.config.get("image.offload_to_cpu", True):
            args.append("--offload-to-cpu")

        env = paths.sandbox_env()
        env["PATH"] = SD_BIN + os.pathsep + SD_CUDA + os.pathsep + env.get("PATH", "")
        env["PYTHONIOENCODING"] = "utf-8"

        job["status"] = "running"
        job["stage"] = T("加载模型")
        job["started_at"] = time.time()
        job["progress"] = 0
        self._emit(job, force=True)
        self.log.info("image", T("开始生图 %s：%dx%d %d 步%s") % (
            job["id"], p["width"], p["height"], p["steps"], T("（参考图 %d 张）") % len(job["refs"]) if job["refs"] else ""))

        proc = subprocess.Popen(args, cwd=paths.ROOT, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, bufsize=0, creationflags=CREATE_NO_WINDOW)
        self._proc = proc
        self._current = job
        try:
            self._pump(proc, job)
            code = proc.wait()
        finally:
            self._proc = None
            self._current = None

        if job["id"] in self._cancel:
            self._cancel.discard(job["id"])
            job["status"] = "cancelled"
            job["stage"] = T("已取消")
            self._finish(job)
            return

        outputs = []
        for f in sorted(glob.glob(os.path.join(outdir, "out*.png"))):
            try:
                size = os.path.getsize(f)
            except OSError:
                continue
            if size < 2048:      # 明显是空图/损坏
                continue
            outputs.append({"file": f, "name": os.path.basename(f), "size": size,
                            "url": "/api/image/file/%s/%s" % (job["id"], os.path.basename(f)),
                            "width": p["width"], "height": p["height"]})

        if code != 0 or not outputs:
            job["status"] = "error"
            job["stage"] = T("失败")
            tail = "\n".join(job["log_tail"][-12:])
            job["error"] = self._friendly_error(tail) or (T("生图进程退出码 %s") % code)
            self.log.error("image", T("生图失败 %s：%s") % (job["id"], job["error"]))
        else:
            job["outputs"] = outputs
            job["status"] = "done"
            job["stage"] = T("完成")
            job["progress"] = 100
            self.log.ok("image", T("生图完成 %s（%d 张，%.1f 秒）") % (
                job["id"], len(outputs), (time.time() - job["started_at"])))
        self._finish(job)

    @staticmethod
    def _friendly_error(tail):
        low = (tail or "").lower()
        if "out of memory" in low or "alloc" in low and "fail" in low:
            return T("显存不足：请降低分辨率/步数，或在设置中开启「权重卸载到内存」")
        if "unknown model architecture" in low:
            return T("该扩散模型架构不被当前 sd-cli 支持（请更新 runtime/sdcpp）")
        if "failed to load" in low:
            return T("模型加载失败：请检查模型文件是否完整、VAE/文本编码器是否匹配")
        if "no such file" in low:
            return T("找不到模型文件")
        return ""

    def _pump(self, proc, job):
        """读取子进程输出。

        sd-cli 的进度条用 \\r 覆盖同一行，且与普通日志在同一路输出里交错，
        按行解析容易漏；这里同时维护一个滚动文本窗口做正则扫描，保证不漏步。
        """
        buf = b""
        tail = ""
        while True:
            chunk = proc.stdout.read(2048)
            if not chunk:
                break
            buf += chunk
            while True:
                idxs = [i for i in (buf.find(b"\n"), buf.find(b"\r")) if i >= 0]
                if not idxs:
                    break
                i = min(idxs)
                line = buf[:i].decode("utf-8", errors="replace").strip()
                buf = buf[i + 1:]
                if line:
                    self._on_line(job, line)
            tail = (tail + chunk.decode("utf-8", errors="replace"))[-4096:]
            self._scan_progress(job, tail)
        if buf:
            self._on_line(job, buf.decode("utf-8", errors="replace").strip())

    def _scan_progress(self, job, text):
        """从滚动文本窗口里取「最后一条」进度。

        取位置最靠后的匹配：加载权重与 VAE 解码都会输出 MB/s 进度条，
        若按正则类型优先级取，会把旧的权重加载进度误当成当前阶段。
        """
        best = None
        for m in RE_SAMPLE.finditer(text):
            best = (m.start(), "sample", int(m.group(1)), int(m.group(2)), float(m.group(3)))
        for m in RE_SAMPLE_IPS.finditer(text):
            ips = float(m.group(3)) or 1.0
            cand = (m.start(), "sample", int(m.group(1)), int(m.group(2)), 1.0 / ips)
            if not best or cand[0] >= best[0]:
                best = cand
        for m in RE_DECODE.finditer(text):
            cand = (m.start(), "decode", int(m.group(1)), int(m.group(2)), 0.0)
            if not best or cand[0] >= best[0]:
                best = cand
        if not best:
            return
        _, kind, step, total, it = best
        if kind == "sample":
            if step < job.get("step", 0) and total == job.get("total_steps"):
                return
            job["step"], job["total_steps"], job["it_s"] = step, total, it
            job["eta_s"] = max(0, (total - step) * it)
            job["stage"] = T("采样")
            job["progress"] = round(step / max(1, total) * 96.0, 1)
        else:
            job["stage"] = T("VAE 解码")
            job["progress"] = max(job["progress"], round(96 + step / max(1, total) * 4.0, 1))
        self._emit(job)

    def _on_line(self, job, line):
        low = line.lower()
        job["log_tail"].append(line[:300])
        if len(job["log_tail"]) > 120:
            del job["log_tail"][:-120]
        if "loading model" in low or "loading tensors" in low or "load model" in low:
            if job["stage"] in (T("排队中"), T("准备中"), T("加载模型")):
                job["stage"] = T("加载模型")
                self._emit(job)
        elif "encoding" in low or ("encode" in low and "text" in low):
            job["stage"] = T("文本编码")
            self._emit(job, force=True)
        elif "sampling" in low and "completed" not in low:
            job["stage"] = T("采样")
        elif "decoding" in low:
            job["stage"] = T("VAE 解码")
        elif "error" in low or "failed" in low:
            job["error"] = job["error"] or line[:300]

    def _emit(self, job, force=False):
        now = time.time()
        if not force and now - job.get("_last_emit", 0) < 0.25:
            return
        job["_last_emit"] = now
        self.bus.publish("image", {
            "id": job["id"], "status": job["status"], "stage": job["stage"],
            "progress": job["progress"], "step": job["step"], "total_steps": job["total_steps"],
            "it_s": job["it_s"], "eta_s": job["eta_s"], "queued": len(self._queue),
            "elapsed": round(now - job["started_at"], 1) if job.get("started_at") else 0,
            "error": job["error"],
        })

    def _finish(self, job):
        job["finished_at"] = time.time()
        job["elapsed_ms"] = (job["finished_at"] - (job["started_at"] or job["created_at"])) * 1000
        public_outputs = [{k: v for k, v in o.items() if k != "file"} for o in job.get("outputs", [])]
        self.db.execute(
            "UPDATE image_jobs SET status=?, stage=?, outputs_json=?, error=?, finished_at=?, elapsed_ms=? WHERE id=?",
            (job["status"], job["stage"], json.dumps(public_outputs, ensure_ascii=False),
             job.get("error", ""), job["finished_at"], job["elapsed_ms"], job["id"]))
        self.bus.publish("image_done", {
            "id": job["id"], "status": job["status"], "error": job.get("error", ""),
            "outputs": public_outputs, "elapsed_ms": job["elapsed_ms"],
        })
        self._emit(job, force=True)

    # ---------------- 维护 ----------------
    def prune(self, keep_days=None):
        days = int(keep_days if keep_days is not None else self.config.get("image.keep_days") or 0)
        if days <= 0 or not os.path.isdir(paths.IMAGE_OUT_DIR):
            return 0
        cutoff = time.time() - days * 86400
        n = 0
        for d in os.listdir(paths.IMAGE_OUT_DIR):
            p = os.path.join(paths.IMAGE_OUT_DIR, d)
            if not os.path.isdir(p):
                continue
            if os.path.getmtime(p) < cutoff:
                shutil.rmtree(p, ignore_errors=True)
                self.db.execute("DELETE FROM image_jobs WHERE id=?", (d,))
                n += 1
        return n

    def upload(self, file_storage):
        name = os.path.basename(file_storage.filename or "ref.png")
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
            raise ValueError(T("只支持 png / jpg / webp / bmp 图片"))
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:60] or "ref.png"
        dest = os.path.join(paths.IMAGE_UPLOAD_DIR, "%s-%s" % (uuid.uuid4().hex[:10], safe))
        os.makedirs(paths.IMAGE_UPLOAD_DIR, exist_ok=True)
        file_storage.save(dest)
        return {"path": dest, "name": name, "size": os.path.getsize(dest),
                "url": "/api/image/refs/%s" % os.path.basename(dest)}
