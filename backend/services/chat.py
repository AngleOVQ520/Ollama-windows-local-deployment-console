"""对话服务：会话/消息存储、流式生成、停止、思考强度预算、上下文裁剪、统计。

思考强度实现：
- off：think=false；
- mini~max：think=true，并按预算限制思考 token 数。超出预算时中断思考，
  把已有思考内容作为 assistant 前缀（<think>…</think>）续写，让模型直接给出答案；
- ultra：think=true，不设上限。
"""
import json
import queue
import re
import threading
import time
import uuid

from ..core.db import jdumps, jloads
from ..core.ollama_client import OllamaError
from ..i18n import T

BUDGET_NOTE = "\n\n（思考预算已用尽，现在根据以上思考直接给出最终答案。）\n"

# 只把最近 N 轮用户消息里的图片带进上下文，避免历史图片随轮数线性推高 prompt tokens 与显存
HISTORY_IMAGE_TURNS = 2

# 采样参数合法范围（与前端参数浮窗一致）：保存/下发前兜底钳制，非法值不会进入引擎
PARAM_RANGES = {
    "temperature": (0.0, 2.0), "top_p": (0.0, 1.0), "top_k": (0, 200), "min_p": (0.0, 1.0),
    "typical_p": (0.0, 1.0), "repeat_penalty": (0.5, 2.0), "repeat_last_n": (-1, 512),
    "presence_penalty": (-2.0, 2.0), "frequency_penalty": (-2.0, 2.0), "mirostat": (0, 2),
    "mirostat_tau": (0.0, 10.0), "mirostat_eta": (0.0, 1.0),
    "num_thread": (0, 64), "num_batch": (32, 4096), "num_gpu": (-1, 200),
}


def clamp_param(key, value):
    """按 PARAM_RANGES 钳制参数；无法解析时返回 None（交给调用方回退默认）。"""
    rng = PARAM_RANGES.get(key)
    if rng is None:
        return value
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    lo, hi = rng
    if isinstance(lo, int) and isinstance(hi, int):
        return int(min(hi, max(lo, int(v))))
    return min(hi, max(lo, v))


def est_tokens(text):
    """粗略估算 token：CJK 每字约 1 token，其余约 4 字符 1 token。"""
    if not text:
        return 0
    cjk = len(re.findall(r"[\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]", text))
    return cjk + max(0, len(text) - cjk) // 4 + 1


_CJK_RE = re.compile(r"[\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]")


def est_tokens_delta(text):
    """逐块累加用的估算：与 est_tokens 同口径，但不加 +1 常数。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    return cjk + max(0, len(text) - cjk) // 4


class Run:
    """一次生成任务。事件写入缓冲，前端可断线重连回放。"""

    def __init__(self, conv_id, user_msg_id):
        self.id = uuid.uuid4().hex[:12]
        self.conv_id = conv_id
        self.user_msg_id = user_msg_id
        self.events = []
        self.cv = threading.Condition()
        self.done = False
        self.stop_evt = threading.Event()
        self.resp = None
        self.started = time.time()

    def emit(self, etype, data):
        with self.cv:
            self.events.append((etype, data))
            self.cv.notify_all()

    def finish(self):
        with self.cv:
            self.done = True
            self.cv.notify_all()

    def stop(self):
        self.stop_evt.set()
        r = self.resp
        if r is not None:
            try:
                r.close()
            except Exception:
                pass

    def iter(self, start=0):
        i = start
        while True:
            with self.cv:
                while i >= len(self.events) and not self.done:
                    self.cv.wait(timeout=15)
                    if i >= len(self.events) and not self.done:
                        break
                batch = self.events[i:]
                done = self.done
            if not batch and not done:
                yield ("ping", {})
                continue
            for ev in batch:
                yield ev
            i += len(batch)
            if done and i >= len(self.events):
                return


def _safe_iter(it, run):
    """停止时关闭连接会让底层迭代器抛异常，这里吞掉以便正常结算统计。"""
    try:
        for d in it:
            yield d
    except Exception:
        if not run.stop_evt.is_set():
            raise


class ChatService:
    def __init__(self, db, registry, engines, loader, config, usage, log, bus):
        self.db = db
        self.registry = registry
        self.engines = engines
        self.loader = loader
        self.config = config
        self.usage = usage
        self.log = log
        self.bus = bus
        self.runs = {}
        self.active = {}  # conv_id -> run

    # ---------------- 会话 ----------------
    def conversations(self, q=""):
        sql = ("SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conv_id=c.id) msg_count, "
               "(SELECT substr(content,1,80) FROM messages m WHERE m.conv_id=c.id ORDER BY id DESC LIMIT 1) preview "
               "FROM conversations c")
        args = []
        if q:
            sql += " WHERE c.title LIKE ? OR c.id IN (SELECT conv_id FROM messages WHERE content LIKE ?)"
            args = ["%" + q + "%", "%" + q + "%"]
        sql += " ORDER BY c.pinned DESC, c.updated_at DESC"
        rows = self.db.query(sql, args)
        for r in rows:
            r["running"] = r["id"] in self.active
        return rows

    def create(self, title="新对话", model="", partition_id=None, system_prompt=""):
        cid = uuid.uuid4().hex[:16]
        now = time.time()
        self.db.insert("conversations", {"id": cid, "title": title or "新对话", "model": model, "partition_id": partition_id,
                                         "pinned": 0, "system_prompt": system_prompt or "", "created_at": now, "updated_at": now})
        self.bus.publish("convs_changed", {"id": cid})
        return self.get(cid)

    def get(self, cid):
        c = self.db.one("SELECT * FROM conversations WHERE id=?", (cid,))
        if not c:
            return None
        c["messages"] = [self._msg(m) for m in self.db.query("SELECT * FROM messages WHERE conv_id=? ORDER BY id", (cid,))]
        run = self.active.get(cid)
        c["run_id"] = run.id if run else None
        return c

    @staticmethod
    def _msg(m):
        m["images"] = jloads(m.pop("images_json"), [])
        m["files"] = jloads(m.pop("files_json"), [])
        m["stats"] = jloads(m.pop("stats_json"), {})
        return m

    def update(self, cid, data):
        upd = {}
        if "title" in data:
            upd["title"] = (str(data["title"]).strip() or "新对话")[:120]
        if "pinned" in data:
            upd["pinned"] = 1 if data["pinned"] else 0
        if "system_prompt" in data:
            upd["system_prompt"] = str(data["system_prompt"] or "")
        if upd:
            self.db.update("conversations", cid, upd)
            self.bus.publish("convs_changed", {"id": cid})
        return self.get(cid)

    def delete(self, cid):
        run = self.active.get(cid)
        if run:
            run.stop()
        self.db.execute("DELETE FROM messages WHERE conv_id=?", (cid,))
        self.db.execute("DELETE FROM conversations WHERE id=?", (cid,))
        self.bus.publish("convs_changed", {"id": cid})

    def delete_all(self, keep_pinned=True):
        # 快照遍历：_generate 的 finally 会并发 pop self.active，直接迭代会抛 size changed
        for r in list(self.active.values()):
            r.stop()
        where = " WHERE pinned=0" if keep_pinned else ""
        ids = [r["id"] for r in self.db.query("SELECT id FROM conversations" + where)]
        for cid in ids:
            self.db.execute("DELETE FROM messages WHERE conv_id=?", (cid,))
            self.db.execute("DELETE FROM conversations WHERE id=?", (cid,))
        self.bus.publish("convs_changed", {})
        return len(ids)

    def delete_message(self, cid, mid, after=False):
        if after:
            self.db.execute("DELETE FROM messages WHERE conv_id=? AND id>=?", (cid, mid))
        else:
            self.db.execute("DELETE FROM messages WHERE conv_id=? AND id=?", (cid, mid))

    def edit_message(self, cid, mid, content):
        self.db.execute("UPDATE messages SET content=? WHERE conv_id=? AND id=?", (content, cid, mid))

    def export(self, cid, fmt="md"):
        c = self.get(cid)
        if not c:
            raise KeyError(T("对话不存在"))
        if fmt == "json":
            return json.dumps(c, ensure_ascii=False, indent=2)
        out = ["# %s" % c["title"], "", T("> 导出时间：%s") % time.strftime("%Y-%m-%d %H:%M:%S"), ""]
        for m in c["messages"]:
            who = {"user": T("🧑 用户"), "assistant": T("🤖 助手 · %s") % (m.get("model") or ""),
                   "system": T("⚙ 系统")}.get(m["role"], m["role"])
            out.append("## %s" % who)
            if m.get("thinking"):
                out.append("<details><summary>%s</summary>\n\n%s\n\n</details>\n" % (T("思考过程"), m["thinking"]))
            out.append(m["content"] or "")
            s = m.get("stats") or {}
            if s.get("output_tokens"):
                out.append(T("\n`输入 %s · 输出 %s · %.1f tok/s · 首 token %.0f ms`") % (
                    s.get("input_tokens"), s.get("output_tokens"), s.get("tps") or 0, s.get("ttft_ms") or 0))
            out.append("")
        return "\n".join(out)

    # ---------------- 生成 ----------------
    def send(self, cid, payload):
        """payload: {content, images, files, partition_id, model, think, params, context, regenerate, continue}"""
        conv = self.db.one("SELECT * FROM conversations WHERE id=?", (cid,))
        if not conv:
            raise KeyError(T("对话不存在"))
        if cid in self.active:
            raise ValueError(T("该对话正在生成中"))
        pid = int(payload.get("partition_id") or 0)
        model = payload.get("model") or ""
        if not pid or not model:
            raise ValueError(T("请先在左下角选择模型"))
        m = self.registry.find(pid, model)
        if not m:
            raise ValueError(T("模型不存在或已被删除"))
        # 并发保护：loader 全局只驻留一个模型，第二个会话若用不同模型生成会卸载第一个会话正在用的模型
        key = (pid, m["name"])
        for ocid, orun in list(self.active.items()):
            if ocid != cid and getattr(orun, "model_key", None) != key:
                raise ValueError(T("另一个对话正在使用其他模型生成，请等待其结束或先停止它"))
        now = time.time()
        user_mid = None
        if payload.get("regenerate"):
            # 删除最后一条助手消息，用已有的用户消息重新生成
            last = self.db.one("SELECT * FROM messages WHERE conv_id=? ORDER BY id DESC LIMIT 1", (cid,))
            if last and last["role"] == "assistant":
                self.db.execute("DELETE FROM messages WHERE id=?", (last["id"],))
            lu = self.db.one("SELECT id FROM messages WHERE conv_id=? AND role='user' ORDER BY id DESC LIMIT 1", (cid,))
            if not lu:
                raise ValueError(T("没有可重新生成的消息"))
            user_mid = lu["id"]
        else:
            content = (payload.get("content") or "").strip()
            images = payload.get("images") or []
            files = payload.get("files") or []
            if not content and not images and not files:
                raise ValueError(T("消息不能为空"))
            user_mid = self.db.insert("messages", {"conv_id": cid, "role": "user", "content": content,
                                                   "images_json": jdumps(images), "files_json": jdumps(files),
                                                   "model": "", "stats_json": "{}", "status": "ok", "created_at": now})
            first = self.db.scalar("SELECT COUNT(*) FROM messages WHERE conv_id=? AND role='user'", (cid,)) == 1
            if first and conv["title"] in ("新对话", ""):
                title = re.sub(r"\s+", " ", content or (files[0]["name"] if files else "图片对话"))[:28] or "新对话"
                self.db.update("conversations", cid, {"title": title})
        self.db.update("conversations", cid, {"model": m["name"], "partition_id": pid, "updated_at": now})
        run = Run(cid, user_mid)
        run.model_key = (pid, m["name"])
        self.runs[run.id] = run
        self.active[cid] = run
        self.bus.publish("convs_changed", {"id": cid})
        threading.Thread(target=self._generate, args=(run, conv, m, payload), daemon=True).start()
        return run

    def stop(self, cid=None, run_id=None):
        run = self.runs.get(run_id) if run_id else self.active.get(cid)
        if run:
            run.stop()
            return True
        return False

    def _build_messages(self, conv, run, m, payload):
        cfg_ctx = self.config.section("context")
        ctx = dict(cfg_ctx, **(payload.get("context") or {}))
        sys_prompt = (conv.get("system_prompt") or "").strip() or (self.config.get("chat.system_prompt") or "").strip()
        rows = self.db.query("SELECT * FROM messages WHERE conv_id=? AND id<=? ORDER BY id", (conv["id"], run.user_msg_id))
        has_vision = "vision" in (m.get("capabilities") or [])
        user_idx = [i for i, r in enumerate(rows) if r["role"] == "user"]
        recent_img_rows = set(user_idx[-HISTORY_IMAGE_TURNS:])
        msgs = []
        for i, r in enumerate(rows):
            if r["role"] not in ("user", "assistant") or r["status"] == "error":
                continue
            content = r["content"] or ""
            if r["role"] == "user":
                for f in jloads(r["files_json"], []):
                    content += "\n\n<file name=\"%s\">\n%s\n</file>" % (f.get("name", "file"), f.get("text", ""))
            item = {"role": r["role"], "content": content}
            imgs = jloads(r["images_json"], [])
            if imgs and has_vision and i in recent_img_rows:
                item["images"] = [i2.split(",", 1)[-1] for i2 in imgs]
            msgs.append(item)
        # 历史轮数限制
        turns = int(ctx.get("history_turns") or 0)
        if turns > 0:
            idx = [i for i, x in enumerate(msgs) if x["role"] == "user"]
            if len(idx) > turns:
                msgs = msgs[idx[-turns]:]
        # 最大输入 token 裁剪（保留最新消息）
        max_in = int(ctx.get("max_input") or 0)
        truncated = 0
        if max_in > 0:
            budget = max_in - est_tokens(sys_prompt)
            kept = []
            for x in reversed(msgs):
                t = est_tokens(x["content"]) + (768 * len(x.get("images", [])))
                if kept and budget - t < 0:
                    truncated += 1
                    continue
                budget -= t
                kept.append(x)
            msgs = list(reversed(kept))
            truncated = len(rows) - len(msgs) if truncated else 0
            # 单条超长：截断用户最后一条的头部
            if msgs and budget < 0:
                last = msgs[-1]
                keep_chars = max(200, len(last["content"]) + budget * 2)
                last["content"] = "…（已截断）" + last["content"][-int(keep_chars):]
        while msgs and msgs[0]["role"] == "assistant":
            msgs.pop(0)
        if sys_prompt:
            msgs.insert(0, {"role": "system", "content": sys_prompt})
        return msgs, ctx, truncated

    def _options(self, m, payload, ctx):
        p = dict(self.config.section("params"), **(payload.get("params") or {}))
        # 兜底：无论来自设置还是请求，参数都先钳制到合法范围，非法值回退默认
        defaults = self.config.section("params")
        for k in PARAM_RANGES:
            if p.get(k) is not None:
                cv = clamp_param(k, p[k])
                p[k] = cv if cv is not None else defaults.get(k, p[k])
        opts = {}
        if not p.get("use_model_defaults"):
            for k in ("temperature", "top_p", "top_k", "min_p", "typical_p", "repeat_penalty", "repeat_last_n",
                      "presence_penalty", "frequency_penalty", "mirostat", "mirostat_tau", "mirostat_eta"):
                if p.get(k) is not None:
                    opts[k] = p[k]
        seed = int(p.get("seed") if p.get("seed") is not None else -1)
        if seed >= 0:
            opts["seed"] = seed
        stop = p.get("stop") or []
        if isinstance(stop, str):
            stop = [s for s in stop.split(",") if s.strip()]
        if stop:
            opts["stop"] = stop
        if int(p.get("num_thread") or 0) > 0:
            opts["num_thread"] = int(p["num_thread"])
        if int(p.get("num_batch") or 0) > 0:
            opts["num_batch"] = int(p["num_batch"])
        if int(p.get("num_gpu") if p.get("num_gpu") is not None else -1) >= 0:
            opts["num_gpu"] = int(p["num_gpu"])
        opts["num_ctx"] = int(ctx.get("num_ctx") or 8192)
        mo = int(ctx.get("max_output") or 0)
        opts["num_predict"] = mo if mo > 0 else -1
        return opts

    def _think_arg(self, m, level):
        caps = m.get("capabilities") or []
        if "thinking" not in caps:
            return None, 0
        if level == "off":
            return False, 0
        tv = m.get("thinking_values") or {}
        values = tv.get("values") if isinstance(tv, dict) else None
        budgets = self.config.get("thinking.budgets") or {}
        budget = int(budgets.get(level, 0) or 0)
        if values and any(isinstance(v, str) for v in values):
            # gpt-oss 等支持 low/medium/high 的模型
            mapping = {"mini": "low", "low": "low", "medium": "medium", "high": "high",
                       "x-high": "high", "max": "high", "ultra": "high"}
            return mapping.get(level, "medium"), budget
        return True, budget

    def _generate(self, run, conv, m, payload):
        self.loader.chat_begin()
        t_req = time.time()
        stats = {"model": m["name"], "partition_id": m["partition_id"], "input_tokens": 0, "output_tokens": 0,
                 "thinking_tokens": 0, "ttft_ms": 0, "think_ms": 0, "eval_ms": 0, "prompt_ms": 0, "load_ms": 0,
                 "total_ms": 0, "tps": 0, "think_level": payload.get("think") or "off", "budget_hit": False}
        content_parts, thinking_parts = [], []
        status = "ok"
        err = ""
        aid = None
        try:
            run.emit("status", {"stage": "loading", "text": T("正在准备模型…")})
            self.loader.ensure_loaded(m["partition_id"], m["name"])
            # 记录生成开始时的 MTP 探测结果，随本条回复持久化（之后切换模型不影响历史消息）
            mtp_state = (self.loader.state.mtp if getattr(self.loader, "state", None) else None) or {}
            stats["mtp_detected"] = bool(mtp_state.get("detected"))
            stats["mtp_evidence"] = mtp_state.get("evidence") or ""
            msgs, ctx, truncated = self._build_messages(conv, run, m, payload)
            if truncated:
                run.emit("notice", {"text": T("已按最大输入限制省略 %d 条较早的消息") % truncated})
            opts = self._options(m, payload, ctx)
            think, budget = self._think_arg(m, payload.get("think") or "off")
            stats["num_ctx"] = opts["num_ctx"]
            p = self.registry.partition(m["partition_id"])
            eng = self.engines.get(p)
            body = {"model": m["name"], "messages": msgs, "stream": True, "options": opts,
                    "keep_alive": self.config.get("engine.keep_alive") or "30m"}
            if think is not None:
                body["think"] = think
            run.emit("status", {"stage": "prompt", "text": T("处理提示词…")})
            t_req = time.time()
            first_tok = None
            first_content = None
            think_tokens = 0
            content_tokens = 0
            final = None
            budget_hit = False
            resp, it = eng.client.stream("/api/chat", body, timeout=(10, 900))
            run.resp = resp
            if run.stop_evt.is_set():
                resp.close()
            try:
                for d in _safe_iter(it, run):
                    if run.stop_evt.is_set():
                        break
                    msg = d.get("message") or {}
                    th = msg.get("thinking") or ""
                    ct = msg.get("content") or ""
                    now = time.time()
                    if (th or ct) and first_tok is None:
                        first_tok = now
                        stats["ttft_ms"] = (now - t_req) * 1000
                    if th:
                        thinking_parts.append(th)
                        think_tokens += est_tokens_delta(th)
                        run.emit("thinking", {"t": th})
                        if budget and think_tokens >= budget and not first_content:
                            budget_hit = True
                            break
                    if ct:
                        if first_content is None:
                            first_content = now
                        content_parts.append(ct)
                        content_tokens += est_tokens_delta(ct)
                        run.emit("content", {"t": ct})
                    if d.get("done"):
                        final = d
                        break
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
            if run.stop_evt.is_set():
                status = "stopped"
            # 思考预算用尽：带着已有思考续写答案
            if budget_hit and not run.stop_evt.is_set():
                stats["budget_hit"] = True
                t_think_end = time.time()
                stats["think_ms"] = (t_think_end - (first_tok or t_req)) * 1000
                run.emit("notice", {"text": T("思考达到预算上限（%d tokens），开始输出答案") % budget})
                prefill = "<think>\n" + "".join(thinking_parts).strip() + BUDGET_NOTE + "</think>\n\n"
                body2 = dict(body)
                body2["messages"] = msgs + [{"role": "assistant", "content": prefill}]
                body2["think"] = True
                resp, it = eng.client.stream("/api/chat", body2, timeout=(10, 900))
                run.resp = resp
                buf = ""
                passthrough = False
                try:
                    for d in _safe_iter(it, run):
                        if run.stop_evt.is_set():
                            break
                        msg = d.get("message") or {}
                        ct = (msg.get("content") or "") + (msg.get("thinking") or "")
                        if ct:
                            if not passthrough:
                                buf += ct
                                # 部分模板会把前缀原样回显，需要剥离
                                if prefill.startswith(buf):
                                    continue
                                if buf.startswith(prefill):
                                    ct = buf[len(prefill):]
                                else:
                                    ct = buf
                                passthrough = True
                                ct = re.sub(r"^\s*<think>\s*</think>\s*", "", ct)
                                if not ct:
                                    continue
                            if first_content is None:
                                first_content = time.time()
                            content_parts.append(ct)
                            content_tokens += est_tokens_delta(ct)
                            run.emit("content", {"t": ct})
                        if d.get("done"):
                            d["_phase2"] = True
                            final = d
                            break
                finally:
                    try:
                        resp.close()
                    except Exception:
                        pass
                if run.stop_evt.is_set():
                    status = "stopped"
            t_end = time.time()
            stats["thinking_tokens"] = think_tokens
            if thinking_parts and not stats["think_ms"]:
                end = first_content or t_end
                stats["think_ms"] = (end - (first_tok or t_req)) * 1000
            if final and not final.get("_phase2"):
                stats["input_tokens"] = final.get("prompt_eval_count") or 0
                stats["output_tokens"] = final.get("eval_count") or 0
                stats["eval_ms"] = (final.get("eval_duration") or 0) / 1e6
                stats["prompt_ms"] = (final.get("prompt_eval_duration") or 0) / 1e6
                stats["load_ms"] = (final.get("load_duration") or 0) / 1e6
                stats["done_reason"] = final.get("done_reason")
            else:
                # 被停止或分两段生成：根据流式块估算
                stats["input_tokens"] = sum(est_tokens(x.get("content", "")) for x in msgs) + 4 * len(msgs)
                out_n = think_tokens + content_tokens
                if final and final.get("_phase2"):
                    out_n = think_tokens + (final.get("eval_count") or content_tokens)
                    stats["done_reason"] = final.get("done_reason")
                else:
                    stats["done_reason"] = "stop_by_user" if status == "stopped" else "aborted"
                stats["output_tokens"] = out_n
                window = (t_end - (first_tok or t_req)) * 1000
                # 停止过早时窗口过小，会算出天文数字的速度，退化用整个请求耗时估算
                stats["eval_ms"] = window if window > 30 else max(1.0, (t_end - t_req) * 1000)
                stats["prompt_ms"] = stats["ttft_ms"]
            stats["total_ms"] = (t_end - t_req) * 1000
            stats["tps"] = stats["output_tokens"] / (stats["eval_ms"] / 1000) if stats["eval_ms"] > 0 else 0
            stats["truncated"] = truncated
        except Exception as e:
            if run.stop_evt.is_set():
                status = "stopped"
            else:
                status = "error"
                err = str(e)
                if isinstance(e, OllamaError) and "memory" in err.lower():
                    err = T("显存/内存不足：%s（可尝试减小上下文长度）") % err
                self.log.error("chat", T("生成失败：%s") % err)
            stats["total_ms"] = (time.time() - t_req) * 1000
        finally:
            content = "".join(content_parts)
            thinking = "".join(thinking_parts)
            if status == "error" and not content:
                content = ""
            stats["error"] = err
            # 会话可能在生成过程中被删除：此时不再写回孤儿 assistant 消息
            conv_exists = self.db.scalar("SELECT 1 FROM conversations WHERE id=?", (run.conv_id,))
            if conv_exists:
                aid = self.db.insert("messages", {"conv_id": run.conv_id, "role": "assistant", "content": content,
                                                  "thinking": thinking, "images_json": "[]", "files_json": "[]",
                                                  "model": m["name"], "stats_json": jdumps(stats), "status": status,
                                                  "created_at": time.time()})
                self.db.update("conversations", run.conv_id, {"updated_at": time.time()})
            else:
                aid = None
            if status != "error" and stats["output_tokens"]:
                self.usage.record(stats, conv_id=run.conv_id, source="chat", status=status)
            elif status == "error":
                self.usage.record(stats, conv_id=run.conv_id, source="chat", status="error")
            run.emit("done", {"message_id": aid, "status": status, "error": err, "stats": stats})
            self.active.pop(run.conv_id, None)
            run.finish()
            self.loader.chat_end()
            self.bus.publish("convs_changed", {"id": run.conv_id})
            # 清理旧 run
            for k in [k for k, r in self.runs.items() if r.done and time.time() - r.started > 600]:
                self.runs.pop(k, None)
            if status == "ok" and self.config.get("chat.auto_title") == "ai":
                threading.Thread(target=self._ai_title, args=(run.conv_id, m), daemon=True).start()

    def _ai_title(self, cid, m):
        try:
            if self.db.scalar("SELECT COUNT(*) FROM messages WHERE conv_id=? AND role='assistant'", (cid,)) != 1:
                return
            rows = self.db.query("SELECT role, content FROM messages WHERE conv_id=? ORDER BY id LIMIT 2", (cid,))
            text = "\n".join("%s: %s" % (r["role"], (r["content"] or "")[:600]) for r in rows)
            p = self.registry.partition(m["partition_id"])
            eng = self.engines.get(p)
            body = {"model": m["name"], "stream": False, "messages": [
                {"role": "user", "content": "为下面的对话起一个不超过 12 个字的简短标题，只输出标题本身：\n\n" + text}],
                "options": {"num_predict": 32, "temperature": 0.3}}
            if "thinking" in (m.get("capabilities") or []):
                body["think"] = False
            r = eng.client.post_json("/api/chat", body, timeout=60)
            title = re.sub(r"[\"'“”《》#*\n]", "", (r.get("message") or {}).get("content", "")).strip()[:30]
            if title:
                self.db.update("conversations", cid, {"title": title})
                self.bus.publish("convs_changed", {"id": cid})
        except Exception as e:
            self.log.warn("chat", T("自动标题失败：%s") % e)
