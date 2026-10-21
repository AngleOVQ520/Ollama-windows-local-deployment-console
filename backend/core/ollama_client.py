"""Ollama HTTP 客户端（基于 requests，支持流式与可中断）。"""
import json

import requests


class OllamaError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


class OllamaClient:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        self.s.trust_env = False  # 本地引擎不走系统代理

    def _url(self, path):
        return self.base + path

    def _check(self, r):
        if r.status_code >= 400:
            try:
                msg = r.json().get("error") or r.text
            except ValueError:
                msg = r.text
            raise OllamaError(msg or ("HTTP %d" % r.status_code), r.status_code)
        return r

    def version(self, timeout=2):
        return self._check(self.s.get(self._url("/api/version"), timeout=timeout)).json().get("version")

    def tags(self, timeout=10):
        return self._check(self.s.get(self._url("/api/tags"), timeout=timeout)).json().get("models", [])

    def ps(self, timeout=5):
        return self._check(self.s.get(self._url("/api/ps"), timeout=timeout)).json().get("models", [])

    def show(self, model, timeout=30):
        return self._check(self.s.post(self._url("/api/show"), json={"model": model}, timeout=timeout)).json()

    def delete(self, model, timeout=30):
        self._check(self.s.delete(self._url("/api/delete"), json={"model": model}, timeout=timeout))

    def copy(self, src, dst, timeout=30):
        self._check(self.s.post(self._url("/api/copy"), json={"source": src, "destination": dst}, timeout=timeout))

    def unload(self, model, timeout=30):
        self._check(self.s.post(self._url("/api/generate"), json={"model": model, "keep_alive": 0}, timeout=timeout))

    def has_blob(self, digest, timeout=10):
        r = self.s.head(self._url("/api/blobs/" + digest), timeout=timeout)
        return r.status_code == 200

    def stream(self, path, body, timeout=(5, None)):
        """返回 (response, 迭代器)。调用方可关闭 response 以中断。"""
        r = self.s.post(self._url(path), json=body, stream=True, timeout=timeout)
        self._check(r)

        def it():
            for line in r.iter_lines(chunk_size=1):
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("error"):
                    raise OllamaError(d["error"])
                yield d

        return r, it()

    def post_json(self, path, body, timeout=600):
        return self._check(self.s.post(self._url(path), json=body, timeout=timeout)).json()
