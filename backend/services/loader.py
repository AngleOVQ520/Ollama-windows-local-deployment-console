"""模型加载状态机。

需求：
- 选择模型后立刻开始加载，下方进度条实时显示进度；
- 加载过程中切换模型：立即中断当前加载（断开请求 + 结束 runner），开始加载新模型；
- 对话输出中切换模型：记为待切换，等输出完成或用户停止后再加载新模型。

进度来源：Ollama 没有加载进度 API，这里读取 llama-server 进程的磁盘读取字节数 / 模型文件大小
（权重读取阶段，占 0~90%），读完后进入"初始化计算图/上下文"阶段（90~99%），请求返回即 100%。
"""
import os
import threading
import time

from .. import paths
from ..i18n import T

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


class LoadState:
    def __init__(self):
        self.model_key = None  # (partition_id, name)
        self.status = "idle"  # idle/loading/loaded/error/cancelled
        self.progress = 0.0
        self.stage = ""
        self.error = ""
        self.started_at = 0
        self.loaded_at = 0
        self.load_ms = 0
        self.num_ctx = 0
        self.size_vram = 0
        self.size = 0
        self.pending = None  # 对话中切换：等待加载的目标
        self.mtp = None      # MTP/推测解码状态：None=未知, dict={"detected":bool,"evidence":str}

    def to_dict(self):
        pid, name = self.model_key if self.model_key else (None, "")
        p = self.pending
        return {"partition_id": pid, "model": name, "status": self.status, "progress": round(self.progress, 1),
                "stage": self.stage, "error": self.error, "started_at": self.started_at, "loaded_at": self.loaded_at,
                "load_ms": self.load_ms, "num_ctx": self.num_ctx, "size_vram": self.size_vram, "size": self.size,
                "mtp": self.mtp,
                "elapsed": (time.time() - self.started_at) if self.status == "loading" else 0,
                "pending": {"partition_id": p[0], "model": p[1]} if p else None}


class ModelLoader:
    def __init__(self, registry, engines, config, log, bus):
        self.registry = registry
        self.engines = engines
        self.config = config
        self.log = log
        self.bus = bus
        self.state = LoadState()
        self._lock = threading.RLock()
        self._gen = 0  # 每次加载的代号，过期线程据此退出
        self._resp = None
        self._busy = 0  # 正在进行的对话数
        self._busy_cv = threading.Condition(self._lock)

    # ---------------- 对外 ----------------
    def publish(self):
        self.bus.publish("load", self.state.to_dict(), sticky=True)

    def current(self):
        return self.state.to_dict()

    def chat_begin(self):
        with self._lock:
            self._busy += 1

    def chat_end(self):
        with self._lock:
            self._busy = max(0, self._busy - 1)
            pending = self.state.pending if self._busy == 0 else None
            if pending:
                self.state.pending = None
        if pending:
            self.log.info("loader", T("对话结束，开始切换到 %s") % pending[1])
            self.select(pending[0], pending[1], force=True)

    def select(self, partition_id, name, force=False, num_ctx=None):
        """选择模型：立即开始加载（对话中则延后）。"""
        p = self.registry.partition(partition_id)
        if not p:
            raise KeyError(T("分区不存在"))
        m = self.registry.find(partition_id, name)
        if not m:
            raise KeyError(T("模型不存在：%s") % name)
        key = (partition_id, m["name"])
        num_ctx = int(num_ctx or self.config.get("context.num_ctx") or 8192)
        with self._lock:
            st = self.state
            if self._busy and not force:
                if st.model_key == key:
                    st.pending = None
                else:
                    st.pending = key
                    self.log.info("loader", T("正在输出，%s 将在本次回复结束后加载") % m["name"])
                self.publish()
                return st.to_dict()
            # 已在加载/已就绪且上下文一致：无需重复加载（force=True 时强制走一遍，用于应用 MTP 等设置变更）
            if not force and st.model_key == key and st.status in ("loading", "loaded") and st.num_ctx == num_ctx:
                st.pending = None
                self.publish()
                return st.to_dict()
            prev_key, prev_status = st.model_key, st.status
            self._gen += 1
            gen = self._gen
            # 中断正在进行的加载请求
            if self._resp is not None:
                try:
                    self._resp.close()
                except Exception:
                    pass
                self._resp = None
            st.model_key = key
            st.status, st.progress, st.stage, st.error = "loading", 0.0, T("准备中"), ""
            st.started_at, st.loaded_at, st.load_ms = time.time(), 0, 0
            st.num_ctx, st.size, st.size_vram, st.pending = num_ctx, m["size"] or 0, 0, None
            st.mtp = None  # 新一次加载，MTP 探测结果作废，等本次重新检测
            self.config.update({"chat": {"last_model": "%d|%s" % key}})
        self.publish()
        threading.Thread(target=self._load, args=(gen, p, m, prev_key, prev_status, num_ctx), daemon=True).start()
        return self.state.to_dict()

    def unload(self):
        with self._lock:
            self._gen += 1
            if self._resp is not None:
                try:
                    self._resp.close()
                except Exception:
                    pass
            key = self.state.model_key
            self.state = LoadState()
        if key:
            self._unload_key(key, kill=True)
            self.log.info("loader", T("已卸载 %s") % key[1])
        self.publish()

    def ensure_loaded(self, partition_id, name, timeout=600):
        """对话前调用：确保目标模型已加载（若正在加载则等待）。"""
        key = (partition_id, name)
        if self.state.model_key != key or self.state.status in ("idle", "error", "cancelled"):
            self.select(partition_id, name, force=True)
        t0 = time.time()
        while time.time() - t0 < timeout:
            st = self.state
            if st.model_key != key:
                raise RuntimeError(T("加载目标已被切换"))
            if st.status == "loaded":
                return True
            if st.status == "error":
                raise RuntimeError(st.error or T("模型加载失败"))
            time.sleep(0.1)
        raise RuntimeError(T("模型加载超时"))

    # ---------------- 内部 ----------------
    def _stale(self, gen):
        return gen != self._gen

    def _unload_key(self, key, kill=False):
        p = self.registry.partition(key[0])
        if not p:
            return
        eng = self.engines.peek(p["id"])
        if not eng or not eng.alive():
            return
        if kill:
            self._kill_runners(eng)
        try:
            eng.client.unload(key[1], timeout=15)
        except Exception:
            pass

    def _kill_runners(self, eng):
        if psutil is None:
            return
        for pid in eng.runner_pids():
            try:
                psutil.Process(pid).kill()
            except Exception:
                pass

    def _runner(self, eng, model_path):
        if psutil is None:
            return None
        for pid in eng.runner_pids():
            try:
                pr = psutil.Process(pid)
                cl = pr.cmdline()
                if not model_path or any(os.path.normcase(model_path) == os.path.normcase(x) for x in cl):
                    return pr
            except Exception:
                continue
        return None

    def _load(self, gen, p, m, prev_key, prev_status, num_ctx):
        st = self.state
        try:
            # 1) 卸载上一个模型（加载中被切换时直接结束 runner）
            if prev_key and prev_key != (p["id"], m["name"]):
                st.stage = T("卸载 %s") % prev_key[1]
                self.publish()
                self._unload_key(prev_key, kill=(prev_status == "loading"))
            elif prev_key == (p["id"], m["name"]) and prev_status == "loading":
                peng = self.engines.peek(p["id"])
                if peng:
                    self._kill_runners(peng)
            if self._stale(gen):
                return
            # 2) 引擎
            st.stage = T("启动分区引擎")
            self.publish()
            eng = self.engines.get(p)
            if eng.status != "running":
                raise RuntimeError(eng.error or T("引擎启动失败"))
            # 同引擎内其他已驻留模型也卸载，保证显存只给当前模型
            try:
                for r in eng.client.ps():
                    if r["name"] != m["name"]:
                        eng.client.unload(r["name"], timeout=15)
            except Exception:
                pass
            # 其他分区引擎中驻留的模型也卸载
            for other in list(self.engines.engines.values()):
                if other is eng or not other.alive():
                    continue
                try:
                    for r in other.client.ps():
                        other.client.unload(r["name"], timeout=15)
                except Exception:
                    pass
            if self._stale(gen):
                return
            # 2.5) MTP 自动启用：带 MTP 头的模型 → 以 draft-mtp 模式重启引擎（ui.mtp_auto 开启时）。
            # llama-server 在每次模型加载时被 Ollama 拉起并继承引擎环境变量，因此 spec 类型在引擎重启后生效。
            # 单个模型可在「参数」浮窗里单独关闭 MTP（models.mtp_enabled = 0）。
            desired_spec = ""
            model_mtp_allowed = int(m.get("mtp_enabled", 1) or 0) == 1
            if self.config.get("ui.mtp_auto") and m.get("has_mtp") and model_mtp_allowed:
                desired_spec = "draft-mtp"
            manual = (self.config.get("engine.spec_type") or "").strip()
            if manual:  # 手动覆盖优先
                desired_spec = manual
            if (eng.current_spec or "") != desired_spec:
                st.stage = T("以 MTP 模式启动引擎") if desired_spec == "draft-mtp" else T("启动引擎（推测解码关闭）")
                self.log.info("loader", T("推测解码设置变更：%r → %r（重启引擎）") % (eng.current_spec or "", desired_spec))
                self.publish()
                eng.stop()
                eng.set_spec(desired_spec)
                if not eng.start(wait=True):
                    raise RuntimeError(eng.error or T("引擎重启失败"))
            if self._stale(gen):
                return
            # 3) 发起加载请求（流式请求，可随时断开）
            st.stage = T("读取权重")
            self.publish()
            # 记录本次加载开始时的日志位置，MTP 探测只看这之后新增的内容（避免读到上次加载的证据）
            log_pos = 0
            try:
                lp = os.path.join(paths.LOG_DIR, "engine-p%d.log" % eng.pid_)
                log_pos = os.path.getsize(lp) if os.path.isfile(lp) else 0
            except OSError:
                log_pos = 0
            model_path = m.get("blob_path") or ""
            file_size = os.path.getsize(model_path) if model_path and os.path.isfile(model_path) else (m["size"] or 0)
            body = {"model": m["name"], "keep_alive": self.config.get("engine.keep_alive") or "30m",
                    "options": {"num_ctx": num_ctx}, "stream": True}
            ngpu = int(self.config.get("params.num_gpu") if self.config.get("params.num_gpu") is not None else -1)
            if ngpu >= 0:
                body["options"]["num_gpu"] = ngpu
            result = {}

            def do_request():
                try:
                    resp, it = eng.client.stream("/api/generate", body, timeout=(10, 900))
                    with self._lock:
                        if self._stale(gen):
                            resp.close()
                            return
                        self._resp = resp
                    for d in it:
                        if d.get("done"):
                            result["ok"] = d
                            break
                    resp.close()
                except Exception as e:
                    result["err"] = e
                finally:
                    result["finished"] = True

            th = threading.Thread(target=do_request, daemon=True)
            t0 = time.time()
            th.start()
            runner = None
            base_read = 0
            read_done_at = None
            while not result.get("finished"):
                if self._stale(gen):
                    return
                if runner is None or not runner.is_running():
                    r = self._runner(eng, model_path)
                    if r is not None and (runner is None or r.pid != runner.pid):
                        runner = r
                        try:
                            base_read = 0
                        except Exception:
                            pass
                pct = None
                if runner is not None and file_size:
                    try:
                        rb = runner.io_counters().read_bytes - base_read
                        frac = min(1.0, rb / float(file_size))
                        pct = 3 + frac * 87
                        if frac >= 0.999 and read_done_at is None:
                            read_done_at = time.time()
                    except Exception:
                        pct = None
                if read_done_at is not None:
                    st.stage = T("初始化上下文 / 计算图")
                    pct = min(99.0, 90 + (time.time() - read_done_at) * 4)
                elif pct is None:
                    # 尚未拿到 runner：按时间缓慢推进到 3%
                    pct = min(3.0, (time.time() - t0) * 1.5)
                    st.stage = T("启动推理进程")
                else:
                    st.stage = T("读取权重 %.0f%%") % ((pct - 3) / 87 * 100)
                st.progress = max(st.progress, pct)
                self.publish()
                time.sleep(0.15)
            if self._stale(gen):
                return
            if "err" in result:
                raise result["err"]
            if "ok" not in result:
                raise RuntimeError(T("加载被中断"))
            with self._lock:
                if self._stale(gen):
                    return
                self._resp = None
                st.status, st.progress, st.stage = "loaded", 100.0, T("就绪")
                st.loaded_at = time.time()
                st.load_ms = (st.loaded_at - st.started_at) * 1000
            try:
                for r in eng.client.ps():
                    if r["name"] == m["name"]:
                        st.size_vram = r.get("size_vram") or 0
                        st.size = r.get("size") or st.size
                        st.num_ctx = r.get("context_length") or st.num_ctx
            except Exception:
                pass
            # MTP / 推测解码探测：扫引擎日志找 llama.cpp 的 speculative 证据。
            # 注意：Ollama 0.40.4 没有暴露任何用户开关，是否启用完全由引擎按模型结构自动决定，
            # 这里只做"事后检测"，如实报告，不伪造结果。
            if self.config.get("ui.mtp_auto"):
                threading.Thread(target=self._detect_speculative, args=(eng.pid_, m["name"], log_pos), daemon=True).start()
            self.log.ok("loader", T("%s 加载完成（%.1fs，ctx=%d）") % (m["name"], st.load_ms / 1000, st.num_ctx))
            self.publish()
        except Exception as e:
            if self._stale(gen):
                return
            st.status, st.stage, st.error = "error", T("加载失败"), str(e)
            self.log.error("loader", T("%s 加载失败：%s") % (m["name"], e))
            self.publish()

    def _detect_speculative(self, partition_id, model_name, start_pos=0):
        """在引擎日志中查找推测解码/MTP 证据，结果写入 LoadState.mtp。

        只读取 start_pos（本次加载请求发出时刻）之后的新增日志，避免把上次加载的证据当成这次的结果。
        """
        import os
        import re
        log_path = os.path.join(paths.LOG_DIR, "engine-p%d.log" % partition_id)
        result = None
        try:
            deadline = time.time() + 20
            while time.time() < deadline:
                if os.path.isfile(log_path):
                    with open(log_path, "rb") as f:
                        f.seek(0, 2)
                        size = f.tell()
                        f.seek(max(0, start_pos))
                        new_part = f.read().decode("utf-8", errors="replace")
                    if "speculative decoding context initialized" in new_part:
                        result = {"detected": True, "evidence": "引擎日志：speculative decoding context initialized"}
                        break
                    if "no implementations specified for speculative decoding" in new_part:
                        result = {"detected": False, "evidence": "引擎日志：未启用任何推测解码实现（该模型无 MTP 头或 MTP 已关闭）"}
                        break
                    if "speculative decoding not supported" in new_part:
                        result = {"detected": False, "evidence": "引擎日志：speculative decoding not supported by this context"}
                        break
                    if re.search(r"draft acceptance = ", new_part):
                        result = {"detected": True, "evidence": "引擎日志出现 draft acceptance 统计（推测解码生效中）"}
                        break
                time.sleep(0.5)
        except Exception:
            result = None
        if not result and result is not None:
            pass
        if result is None:
            # 未发现证据：如实报告"未检测到"，避免误导
            result = {"detected": False, "evidence": "加载后 20 秒内引擎日志无 speculative/MTP 证据（或该模型不含 MTP 头）"}
        with self._lock:
            if self.state.model_key and self.state.model_key[1] == model_name and self.state.status == "loaded":
                self.state.mtp = result
                self.log.info("loader", T("MTP/推测解码探测：%s（%s）") % (T("已启用") if result["detected"] else T("未检测到"), result["evidence"]))
                self.publish()
