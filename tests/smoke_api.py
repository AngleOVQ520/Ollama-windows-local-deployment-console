"""后端冒烟测试：需先运行 app-cn.py。用法：python tests/smoke_api.py [base_url]"""
import json
import sys
import time

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "..", "runtime", "pylib"))
import requests

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8848"
S = requests.Session()
S.trust_env = False


def j(method, path, **kw):
    r = S.request(method, B + path, timeout=kw.pop("timeout", 60), **kw)
    d = r.json()
    if not d.get("ok"):
        raise AssertionError("%s %s -> %s" % (method, path, d))
    return d.get("data")


def wait_ready():
    for _ in range(120):
        if j("GET", "/api/bootstrap")["app"]["ready"]:
            return
        time.sleep(0.5)
    raise AssertionError("not ready")


wait_ready()
parts = j("GET", "/api/partitions")
print("partitions:", [(p["id"], p["name"], p["model_count"], p["engine"]["status"]) for p in parts])
models = j("GET", "/api/models")
for m in models:
    print("model:", m["id"], m["name"], m["display_category"], m["params_label"], m["params"], m["quant"], m["size"], m["context_length"], m["capabilities"])
print("load:", j("GET", "/api/load"))
print("usage overview keys:", list(j("GET", "/api/usage/overview").keys()))
print("system:", {k: v for k, v in j("GET", "/api/system")["sample"].items() if k != "gpus"})
print("browse root drives:", len(j("GET", "/api/fs/browse")["drives"]))
print("api models:", S.get("http://127.0.0.1:8849/v1/models", timeout=10).json())
