"""Ollama 官方模型库搜索（ollama.com），用于"添加模型"页的联想与标签选择。失败时回退到内置推荐。"""
import re
import time

import requests

from ..i18n import T


def _featured():
    """内置推荐模型。每次调用重新取译文，保证运行期切换界面语言后描述也跟着变。"""
    return [
        {"name": "qwen3.5", "desc": T("通义千问 3.5，支持思考 / 视觉 / 工具"), "tags": ["0.8b", "2b", "4b", "9b", "27b", "35b"]},
        {"name": "qwen3", "desc": T("通义千问 3，混合思考模型"), "tags": ["0.6b", "1.7b", "4b", "8b", "14b", "30b", "32b"]},
        {"name": "deepseek-r1", "desc": T("DeepSeek 推理模型"), "tags": ["1.5b", "7b", "8b", "14b", "32b", "70b"]},
        {"name": "gemma3", "desc": T("Google Gemma 3，多模态"), "tags": ["270m", "1b", "4b", "12b", "27b"]},
        {"name": "llama3.2", "desc": T("Meta Llama 3.2 小模型"), "tags": ["1b", "3b"]},
        {"name": "gpt-oss", "desc": T("OpenAI 开放权重推理模型"), "tags": ["20b", "120b"]},
        {"name": "mistral", "desc": "Mistral 7B", "tags": ["7b"]},
        {"name": "phi4", "desc": T("微软 Phi-4"), "tags": ["14b"]},
        {"name": "qwen2.5-coder", "desc": T("千问代码模型"), "tags": ["0.5b", "1.5b", "3b", "7b", "14b", "32b"]},
        {"name": "nomic-embed-text", "desc": T("文本向量模型"), "tags": ["latest"]},
        {"name": "smollm2", "desc": T("超小模型，适合测试"), "tags": ["135m", "360m", "1.7b"]},
    ]


_cache = {}
_S = requests.Session()
_S.headers["User-Agent"] = "Mozilla/5.0 OllamaUltimate/1.0"


def _get(url, ttl=1800):
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    r = _S.get(url, timeout=8)
    r.raise_for_status()
    _cache[url] = (time.time(), r.text)
    return r.text


def search(q):
    if not q:
        return {"source": "featured", "items": _featured()}
    try:
        html = _get("https://ollama.com/search?q=" + requests.utils.quote(q))
        items = []
        for block in re.findall(r'<li x-test-model[^>]*>(.*?)</li>', html, re.S)[:30]:
            name = re.search(r'href="/library/([^"]+)"', block)
            if not name:
                name = re.search(r'href="/([^"]+)"', block)
            if not name:
                continue
            desc = re.search(r'<p[^>]*>([^<]{3,300})</p>', block)
            sizes = re.findall(r'x-test-size[^>]*>([^<]+)<', block)
            caps = re.findall(r'x-test-capability[^>]*>([^<]+)<', block)
            pulls = re.search(r'x-test-pull-count[^>]*>([^<]+)<', block)
            items.append({"name": name.group(1), "desc": (desc.group(1).strip() if desc else ""),
                          "tags": [s.strip() for s in sizes], "caps": [c.strip() for c in caps],
                          "pulls": pulls.group(1).strip() if pulls else ""})
        if items:
            return {"source": "ollama.com", "items": items}
    except Exception:
        pass
    ql = q.lower()
    return {"source": "featured", "items": [f for f in _featured() if ql in f["name"] or ql in f["desc"].lower()] or _featured()}


def tags(name):
    if not name:
        return []
    try:
        html = _get("https://ollama.com/library/%s/tags" % name)
        out = []
        seen = set()
        for m in re.finditer(r'href="/library/%s:([^"]+)"' % re.escape(name), html):
            t = m.group(1)
            if t in seen:
                continue
            seen.add(t)
            # 尝试读取紧随其后的大小信息
            seg = html[m.end(): m.end() + 1500]
            size = re.search(r'(\d+(?:\.\d+)?\s?[KMGT]B)', seg)
            out.append({"tag": t, "size": size.group(1) if size else ""})
        if out:
            return out[:120]
    except Exception:
        pass
    f = next((x for x in _featured() if x["name"] == name), None)
    return [{"tag": t, "size": ""} for t in (f["tags"] if f else ["latest"])]
