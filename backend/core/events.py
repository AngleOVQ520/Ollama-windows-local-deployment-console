"""进程内事件总线（供 SSE 推送）与日志环形缓冲（供命令行仪表盘与设置页查看）。"""
import collections
import json
import os
import queue
import threading
import time

from .. import paths


class EventBus:
    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()
        self._state = {}  # 最近一次的状态型事件，新订阅者立刻收到

    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self._lock:
            self._subs.add(q)
            for etype, data in self._state.items():
                q.put_nowait((etype, data))
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def publish(self, etype, data, sticky=False):
        with self._lock:
            if sticky:
                self._state[etype] = data
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((etype, data))
            except queue.Full:
                pass  # 慢消费者丢弃事件，避免阻塞

    def sse(self, q, heartbeat=15):
        """生成 SSE 文本流。"""
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    etype, data = q.get(timeout=heartbeat)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                yield "event: %s\ndata: %s\n\n" % (etype, json.dumps(data, ensure_ascii=False))
        finally:
            self.unsubscribe(q)


class LogBuffer:
    LEVELS = ("debug", "info", "ok", "warn", "error")

    def __init__(self, size=400, file_name="app.log"):
        self.lines = collections.deque(maxlen=size)
        self._lock = threading.Lock()
        self.bus = None
        os.makedirs(paths.LOG_DIR, exist_ok=True)
        self._fp = open(os.path.join(paths.LOG_DIR, file_name), "a", encoding="utf-8", buffering=1)

    def log(self, level, source, msg):
        rec = {"ts": time.time(), "level": level, "source": source, "msg": str(msg)}
        with self._lock:
            self.lines.append(rec)
            try:
                self._fp.write("%s [%s] %s: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), level.upper(), source, msg))
            except (OSError, ValueError):
                pass
        if self.bus is not None:
            self.bus.publish("log", rec)

    def info(self, source, msg):
        self.log("info", source, msg)

    def ok(self, source, msg):
        self.log("ok", source, msg)

    def warn(self, source, msg):
        self.log("warn", source, msg)

    def error(self, source, msg):
        self.log("error", source, msg)

    def recent(self, n=200):
        with self._lock:
            return list(self.lines)[-n:]
