"""对外 API 服务（独立端口）：OpenAI 兼容 + Ollama 原生接口代理。

- 模型名可写 "qwen3.5:2b"（自动在所有分区中查找）或 "分区名/qwen3.5:2b"；
- 支持 API Key 鉴权、局域网监听、CORS；
- 所有调用计入用量统计（source=api）。
"""
import json
import threading
import time

import requests
from flask import Flask, Response, jsonify, request, stream_with_context
from werkzeug.serving import make_server

from ..i18n import T


class ApiServer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.server = None
        self.thread = None
        self.error = ""
        self._lock = threading.Lock()
        self._idx_lock = threading.Lock()
        self._idx = None        # (分区行, (分区 id, 模型名) -> 模型行, 模型名 -> 首个模型行)
        self._idx_ver = None    # 构索引时的 models_changed 版本
        self._ver = 0           # 模型变更事件计数，用作失效标记
        self.app = self._build()
        self._listen()

    # ---------------- 生命周期 ----------------
    def url(self):
        cfg = self.ctx.config.section("api")
        return "http://%s:%d" % ("127.0.0.1", cfg.get("port", 8849)) if self.server else ""

    def start(self):
        with self._lock:
            cfg = self.ctx.config.section("api")
            if not cfg.get("enabled"):
                self.error = ""
                return False
            host = "0.0.0.0" if cfg.get("lan") else "127.0.0.1"
            try:
                self.server = make_server(host, int(cfg["port"]), self.app, threaded=True)
            except OSError as e:
                self.server = None
                self.error = T("端口 %s 被占用：%s") % (cfg["port"], e)
                self.ctx.log.error("api", self.error)
                return False
            self.error = ""
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="api-server")
            self.thread.start()
            self.ctx.log.ok("api", T("API 服务已启动 http://%s:%s/v1") % (host, cfg["port"]))
            return True

    def stop(self):
        with self._lock:
            if self.server:
                try:
                    self.server.shutdown()
                    self.server.server_close()
                except Exception:
                    pass
                self.server = None

    def restart(self):
        self.stop()
        time.sleep(0.2)
        self.start()

    def status(self):
        cfg = self.ctx.config.section("api")
        return {"enabled": cfg.get("enabled"), "running": self.server is not None, "url": self.url(), "error": self.error,
                "lan": cfg.get("lan"), "port": cfg.get("port")}

    # ---------------- 工具 ----------------
    def _listen(self):
        """订阅模型变更事件：新增/删除/改名/同步后让内存索引失效。"""
        try:
            self._q = self.ctx.bus.subscribe()
        except Exception:
            self._q = None
            return

        def run():
            while True:
                try:
                    etype, _ = self._q.get()
                except Exception:
                    return
                if etype == "models_changed":
                    self._ver += 1

        threading.Thread(target=run, daemon=True, name="api-index").start()

    def _index(self):
        """建立内存索引：分区名 -> 分区行、(分区 id, 模型名) -> 模型行、模型名 -> 首个模型行。"""
        ver = self._ver
        idx = self._idx
        if idx is not None and self._idx_ver == ver:
            return idx
        with self._idx_lock:
            if self._idx is not None and self._idx_ver == self._ver:
                return self._idx
            reg = self.ctx.registry
            parts = reg.db.query("SELECT id, name FROM partitions")
            from .registry import normalize_name
            keyed, by_name = {}, {}
            for m in reg.models():
                for k in (m["name"], normalize_name(m["name"])):
                    keyed.setdefault((m["partition_id"], k), m)
                    by_name.setdefault(k, m)
            self._idx = (parts, keyed, by_name)
            self._idx_ver = self._ver
            return self._idx

    def resolve(self, name):
        from .registry import normalize_name
        name = (name or "").strip()
        parts, keyed, by_name = self._index()
        if "/" in name:
            head, rest = name.split("/", 1)
            pid = next((p["id"] for p in parts if p["name"] == head), None)
            if pid is not None:
                return keyed.get((pid, rest)) or keyed.get((pid, normalize_name(rest)))
        return by_name.get(name) or by_name.get(normalize_name(name))

    def _engine(self, m):
        p = self.ctx.registry.partition(m["partition_id"])
        return self.ctx.engines.get(p)

    def _ensure(self, m):
        # 同一时刻只驻留一个模型：通过 loader 切换（若对话中则等待）
        ld = self.ctx.loader
        if ld.state.model_key != (m["partition_id"], m["name"]) or ld.state.status != "loaded":
            ld.ensure_loaded(m["partition_id"], m["name"])

    def _record(self, m, usage, t0, ttft, status="ok", timings=None):
        if not self.ctx.config.get("api.record_usage"):
            return
        timings = timings or {}
        inp = usage.get("prompt_tokens") or usage.get("prompt_eval_count") or 0
        out = usage.get("completion_tokens") or usage.get("eval_count") or 0
        total = (time.time() - t0) * 1000
        prompt_ms = float(timings.get("prompt_ms") or (usage.get("prompt_eval_duration") or 0) / 1e6 or 0)
        eval_ms = float(timings.get("eval_ms") or (usage.get("eval_duration") or 0) / 1e6 or 0)
        if not eval_ms:
            # 没有逐 token 计时（如非流式 OpenAI 接口）：用总耗时减去提示处理时间，作为整体速度
            eval_ms = max(50.0, total - prompt_ms) if prompt_ms else max(50.0, total)
        if not ttft:
            ttft = prompt_ms or total
        self.ctx.usage.record({"model": m["name"], "partition_id": m["partition_id"], "input_tokens": inp,
                               "output_tokens": out, "ttft_ms": ttft, "total_ms": total, "eval_ms": eval_ms,
                               "prompt_ms": prompt_ms, "tps": out / (eval_ms / 1000) if eval_ms else 0},
                              source="api", status=status)

    # ---------------- 应用 ----------------
    def _build(self):
        app = Flask("api")
        api = self

        @app.before_request
        def _auth():
            api.ctx.stats["api_requests"] += 1
            if request.method == "OPTIONS":
                return api._cors(Response(status=204))
            cfg = api.ctx.config.section("api")
            if cfg.get("require_key"):
                # 密钥为空时一律拒绝，避免"开启鉴权但未设置密钥"导致接口裸奔
                expected = cfg.get("api_key") or ""
                key = request.headers.get("Authorization", "").replace("Bearer ", "").strip() or request.headers.get("x-api-key", "")
                if not expected or key != expected:
                    return api._cors(jsonify({"error": {"message": "Invalid API key", "type": "invalid_request_error"}})), 401

        @app.after_request
        def _after(resp):
            return api._cors(resp)

        @app.get("/")
        def root():
            return jsonify({"name": T("Ollama 控制台") + " API", "openai_base": "/v1", "ollama_base": "/api"})

        @app.get("/v1/models")
        def v1_models():
            data = [{"id": m["name"], "object": "model", "created": int(m["added_at"]), "owned_by": m["partition_name"],
                     "context_length": m["context_length"]} for m in api.ctx.registry.models()]
            return jsonify({"object": "list", "data": data})

        @app.post("/v1/chat/completions")
        @app.post("/v1/completions")
        @app.post("/v1/embeddings")
        def v1_proxy():
            b = request.get_json(silent=True) or {}
            m = api.resolve(b.get("model"))
            if not m:
                return jsonify({"error": {"message": "model '%s' not found" % b.get("model"), "type": "not_found"}}), 404
            b["model"] = m["name"]
            if b.get("stream") and request.path.endswith("chat/completions"):
                b.setdefault("stream_options", {"include_usage": True})
            return api._proxy(m, request.path, b, sse=bool(b.get("stream")))

        @app.get("/api/tags")
        def api_tags():
            out = []
            for m in api.ctx.registry.models():
                out.append({"name": m["name"], "model": m["name"], "size": m["size"], "digest": m["digest"],
                            "details": {"family": m["family"], "parameter_size": m["params_label"], "quantization_level": m["quant"],
                                        "format": "gguf"}, "partition": m["partition_name"]})
            return jsonify({"models": out})

        @app.get("/api/version")
        def api_version():
            from .. import __version__
            return jsonify({"version": "0.40.4", "app": __version__})

        @app.post("/api/chat")
        @app.post("/api/generate")
        @app.post("/api/embed")
        @app.post("/api/embeddings")
        @app.post("/api/show")
        def api_proxy():
            b = request.get_json(silent=True) or {}
            m = api.resolve(b.get("model") or b.get("name"))
            if not m:
                return jsonify({"error": "model '%s' not found" % (b.get("model") or b.get("name"))}), 404
            b["model"] = m["name"]
            b.pop("name", None)
            stream = b.get("stream", True) if request.path in ("/api/chat", "/api/generate") else False
            return api._proxy(m, request.path, b, ndjson=stream)

        return app

    def _cors(self, resp):
        if self.ctx.config.get("api.cors"):
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, x-api-key"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp

    def _proxy(self, m, path, b, sse=False, ndjson=False):
        try:
            if not path.endswith("/show"):
                self._ensure(m)
            eng = self._engine(m)
        except Exception as e:
            return jsonify({"error": str(e)}), 503
        url = eng.base_url + path
        t0 = time.time()
        sess = requests.Session()
        sess.trust_env = False
        stream = sse or ndjson
        self.ctx.loader.chat_begin()
        try:
            r = sess.post(url, json=b, stream=stream, timeout=(10, 900))
        except Exception as e:
            self.ctx.loader.chat_end()
            return jsonify({"error": str(e)}), 502
        if not stream:
            try:
                data = r.content
                try:
                    j = json.loads(data)
                    if r.status_code < 400 and not path.endswith("/show") and "embed" not in path:
                        self._record(m, j.get("usage") or j, t0, 0, timings=j.get("timings"))
                except ValueError:
                    pass
                return Response(data, status=r.status_code, mimetype=r.headers.get("Content-Type", "application/json"))
            finally:
                r.close()
                self.ctx.loader.chat_end()

        api = self

        def gen():
            ttft = None
            usage = {}
            timings = {}
            try:
                for line in r.iter_lines(chunk_size=1):
                    if ttft is None:
                        ttft = (time.time() - t0) * 1000
                    if line:
                        try:
                            s = line.decode("utf-8", errors="ignore")
                            j = json.loads(s[5:].strip() if s.startswith("data:") else s)
                            if isinstance(j, dict):
                                if j.get("usage"):
                                    usage = j["usage"]
                                elif j.get("done"):
                                    usage = j
                                if j.get("timings"):
                                    timings = j["timings"]
                        except ValueError:
                            pass
                    yield line + (b"\n\n" if sse else b"\n") if line else b""
            finally:
                r.close()
                api.ctx.loader.chat_end()
                if usage:
                    api._record(m, usage, t0, ttft or 0, timings=timings)

        return Response(stream_with_context(gen()), status=r.status_code,
                        mimetype="text/event-stream" if sse else "application/x-ndjson",
                        headers={"Cache-Control": "no-cache"})
