"""回归测试：分区与引擎生命周期、设置联动、会话/预设/数据管理、API 鉴权、上下文裁剪、命令行仪表盘渲染。
需先运行 app-cn.py。用法：python tests/regression.py [base_url]
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
sys.path.insert(0, ROOT)
import requests  # noqa: E402

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8848"
S = requests.Session()
S.trust_env = False
PASS, FAIL = [], []


def j(method, path, **kw):
    r = S.request(method, B + path, timeout=kw.pop("timeout", 180), **kw)
    d = r.json()
    if not d.get("ok"):
        raise AssertionError("%s %s -> %s" % (method, path, str(d)[:300]))
    return d.get("data")


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def wait(pred, timeout=120, step=0.3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


print("== 1. 分区生命周期")
new_dir = os.path.join(ROOT, "models", "_test_partition")
p = j("POST", "/api/partitions", json={"name": "测试分区", "path": new_dir, "color": "#84cc16"})
check("创建分区", p["id"] and os.path.isdir(new_dir), p["path"])
pid = p["id"]
e = j("POST", "/api/partitions/%d/engine/start" % pid)
check("启动分区引擎", e["status"] == "running", (e["port"], e["version"]))
e2 = j("POST", "/api/partitions/%d/engine/restart" % pid)
check("重启分区引擎", e2["status"] == "running", e2["port"])
r = j("POST", "/api/partitions/%d/engine/stop" % pid)
check("停止分区引擎", (j("GET", "/api/partitions") and [x for x in j("GET", "/api/partitions") if x["id"] == pid][0]["engine"]["status"] == "stopped"))
j("PATCH", "/api/partitions/%d" % pid, json={"name": "测试分区（改名）"})
check("重命名分区", [x for x in j("GET", "/api/partitions") if x["id"] == pid][0]["name"] == "测试分区（改名）")
j("DELETE", "/api/partitions/%d" % pid)
check("删除分区", not any(x["id"] == pid for x in j("GET", "/api/partitions")))

print("== 2. 设置联动：引擎参数变更触发重启")
cur = j("GET", "/api/settings")
before = [x for x in j("GET", "/api/partitions") if x["is_default"]][0]["engine"]
j("PATCH", "/api/settings", json={"engine": {"keep_alive": "12m"}})
# 注意：重启窗口内 uptime 会短暂为 0（此时状态是 stopped），必须等到"运行中且刚启动"
after = wait(lambda: (lambda e: e if e["status"] == "running" and e["uptime"] < 6 else None)(
    [x for x in j("GET", "/api/partitions") if x["is_default"]][0]["engine"]), 90) or {}
check("修改 keep_alive 后引擎自动重启", after.get("status") == "running" and after.get("uptime", 99) < 60, after.get("uptime"))
check("设置已持久化", j("GET", "/api/settings")["engine"]["keep_alive"] == "12m")
j("PATCH", "/api/settings", json={"engine": {"keep_alive": cur["engine"]["keep_alive"]}})

print("== 3. 无效设置被拒绝")
r = S.patch(B + "/api/settings", json={"api": {"port": 70000}}, timeout=20).json()
check("端口越界被拒绝", not r["ok"], r.get("error"))
r = S.patch(B + "/api/settings", json={"api": {"port": 8848}}, timeout=20).json()
check("API 端口不能等于界面端口", not r["ok"], r.get("error"))

print("== 4. 模型编辑")
m = j("GET", "/api/models")[0]
j("PATCH", "/api/models/%d" % m["id"], json={"remark": "回归测试备注", "category": "测试类别", "favorite": True, "notes": "笔记内容"})
m2 = j("GET", "/api/models/%d" % m["id"])
check("备注/类别/收藏/笔记保存", (m2["remark"], m2["category"], m2["favorite"], m2["notes"]) == ("回归测试备注", "测试类别", 1, "笔记内容"))
lst = [x for x in j("GET", "/api/models") if x["id"] == m["id"]][0]
check("列表展示自定义类别", lst["display_category"] == "测试类别")
j("PATCH", "/api/models/%d" % m["id"], json={"remark": "", "category": "", "favorite": False, "notes": ""})
check("恢复备注", j("GET", "/api/models/%d" % m["id"])["display_category"] in ("千问 Qwen", "其他"))

print("== 5. 会话管理")
c = j("POST", "/api/conversations", json={"title": "回归会话"})
cid = c["id"]
j("PATCH", "/api/conversations/%s" % cid, json={"title": "改名后", "pinned": True, "system_prompt": "你是测试助手"})
c2 = j("GET", "/api/conversations/%s" % cid)
check("会话改名/置顶/系统提示词", (c2["title"], c2["pinned"], c2["system_prompt"])[0] == "改名后" and c2["pinned"] == 1 and c2["system_prompt"] == "你是测试助手")
dup = j("POST", "/api/conversations/%s/duplicate" % cid)
check("复制会话", dup["id"] != cid and dup["title"].endswith("（副本）"))
r = S.get(B + "/api/conversations/%s/export?format=md" % cid, timeout=30)
check("导出 Markdown", r.status_code == 200 and "回归会话" in r.text or "改名后" in r.text, r.headers.get("Content-Disposition", "")[:60])
check("导出 JSON", S.get(B + "/api/conversations/%s/export?format=json" % cid, timeout=30).json()["id"] == cid)
j("DELETE", "/api/conversations/%s" % dup["id"])
check("删除会话", not any(x["id"] == dup["id"] for x in j("GET", "/api/conversations")))
q = j("GET", "/api/conversations?q=改名")
check("搜索会话", any(x["id"] == cid for x in q))

print("== 6. 预设")
pr = j("POST", "/api/presets", json={"name": "回归预设", "content": "测试内容"})
j("PUT", "/api/presets/%d" % pr["id"], json={"name": "回归预设2", "content": "内容2"})
check("预设增改", any(x["id"] == pr["id"] and x["name"] == "回归预设2" for x in j("GET", "/api/presets")))
j("DELETE", "/api/presets/%d" % pr["id"])
check("预设删除", not any(x["id"] == pr["id"] for x in j("GET", "/api/presets")))

print("== 7. 上下文裁剪（max_input 生效）")
pid = [x for x in j("GET", "/api/partitions") if x["is_default"]][0]["id"]
model = j("GET", "/api/models")[0]["name"]
j("POST", "/api/load", json={"partition_id": pid, "model": model})
wait(lambda: j("GET", "/api/load")["status"] in ("loaded", "error"), 180)
cj = j("POST", "/api/conversations", json={})["id"]
for i in range(3):
    j("POST", "/api/conversations/%s/send" % cj, json={"content": "历史消息 %d：%s" % (i, "内容" * 200), "partition_id": pid, "model": model, "think": "off",
                                                      "context": {"max_input": 700, "max_output": 30}})
    wait(lambda: not j("GET", "/api/conversations/%s" % cj)["run_id"], 120, 0.5)
    time.sleep(0.5)
cres = j("GET", "/api/conversations/%s" % cj)
last_stats = cres["messages"][-1]["stats"]
check("超长历史被裁剪", last_stats.get("truncated", 0) >= 1, "truncated=%s input=%s" % (last_stats.get("truncated"), last_stats.get("input_tokens")))
j("DELETE", "/api/conversations/%s" % cj)

print("== 8. 数据管理")
bk = j("POST", "/api/data/backup")
check("创建备份", bk["name"] and os.path.isdir(os.path.join(ROOT, "data", "backups", bk["name"])))
check("备份列表", any(b["name"] == bk["name"] for b in j("GET", "/api/data/backups")))
v = j("POST", "/api/data/vacuum")
check("VACUUM", v["size"] > 0, "%.1f MB" % (v["size"] / 1e6))
j("DELETE", "/api/data/backups/%s" % bk["name"])
check("删除备份", not any(b["name"] == bk["name"] for b in j("GET", "/api/data/backups")))
check("日志读取", len(j("GET", "/api/logs?n=20")) > 0)
check("引擎日志读取", isinstance(j("GET", "/api/logs/engine/%d" % pid), str))

print("== 9. 文件浏览与扫描")
d = j("GET", "/api/fs/browse?path=" + requests.utils.quote(ROOT))
check("浏览项目目录（仅文件夹）", any(x["name"] == "models" and x["type"] == "dir" for x in d["entries"]), [x["name"] for x in d["entries"]][:6])
d2 = j("GET", "/api/fs/browse?mode=file&path=" + requests.utils.quote(ROOT))
check("文件模式列出 GGUF", any(x["name"].endswith(".gguf") for x in d2["entries"]))
check("盘符列表", len(d["drives"]) >= 1)
found = j("POST", "/api/fs/scan", json={"path": ROOT})
check("扫描 GGUF", any(x["name"].endswith(".gguf") for x in found), len(found))
r = S.post(B + "/api/fs/open", json={"path": "C:\\Windows"}, timeout=20).json()
check("拒绝打开项目外路径", not r["ok"])

def api_ready():
    try:
        requests.get(A + "/v1/models", timeout=3)
        return True
    except Exception:
        return False


print("== 10. API 密钥鉴权")
A = "http://127.0.0.1:8849"
S.patch(B + "/api/settings", json={"api": {"api_key": ""}}, timeout=20)
r = S.patch(B + "/api/settings", json={"api": {"require_key": True}}, timeout=20).json()
auto_key = r["data"]["settings"]["api"]["api_key"]
check("开启鉴权时自动生成密钥", auto_key.startswith("sk-oul-"), auto_key[:14] + "…")
wait(api_ready, 30)
r = requests.post(A + "/v1/chat/completions", json={"model": model, "messages": [{"role": "user", "content": "hi"}]}, timeout=30)
check("无密钥被拒绝 401", r.status_code == 401, r.status_code)
key = j("POST", "/api/api-server/genkey")["api_key"]
check("可手动轮换密钥", key != auto_key)
r = requests.post(A + "/v1/chat/completions", json={"model": model, "messages": [{"role": "user", "content": "只回复 OK"}], "max_tokens": 20},
                  headers={"Authorization": "Bearer " + key}, timeout=300).json()
check("带密钥可调用", "choices" in r and r["choices"][0]["message"]["content"] is not None, str(r)[:120])
rm = requests.get(A + "/v1/models", headers={"Authorization": "Bearer " + key}, timeout=20).json()
check("模型列表含分区模型", any(x["id"] == model for x in rm["data"]), len(rm["data"]))
r = requests.post(A + "/api/chat", json={"model": "不存在的分区/" + model, "messages": [{"role": "user", "content": "hi"}], "stream": False},
                  headers={"Authorization": "Bearer " + key}, timeout=60)
check("不存在的模型返回 404", r.status_code == 404, r.status_code)
j("PATCH", "/api/settings", json={"api": {"require_key": False, "api_key": ""}})
time.sleep(0.4)

print("== 11. 命令行仪表盘渲染")
os.environ["PYTHONIOENCODING"] = "utf-8"
from backend.console import Dashboard  # noqa: E402
from backend.context import AppContext   # noqa: E402
from rich.console import Console        # noqa: E402
ctx = AppContext()
ctx.loader.state.status = "loading"
ctx.loader.state.progress = 62.0
ctx.loader.state.stage = "读取权重 62%"
ctx.loader.state.model_key = (pid, model)
d = Dashboard(ctx, B + "/")
rec = Console(record=True, width=150, height=46)
rec.print(d.render())
text = rec.export_text()
check("仪表盘渲染成功", "OLLAMA" in text.upper() and "当前模型" in text and "实时日志" in text, text[:60].replace("\n", " "))
ctx.shutdown()

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
