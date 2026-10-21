"""清理本次验证产生的测试数据，并把界面状态恢复为用户原先的选择。
只删除标题能明确匹配到测试提示词的对话，绝不动用户自己的对话。
"""
import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
import requests  # noqa: E402

B = "http://127.0.0.1:8848"
S = requests.Session()
S.trust_env = False

MY_TESTS = re.compile(
    r"(17\*23|17 × 23|欧拉公式|单文件 HTML|绿色渐变按钮|介绍长城|宇宙的起源|斐波那契|下一个数|快速排序|黄山|"
    r"3000 字|2000 字|秋天的傍晚|用一句话介绍你自己|勾股定理|Say hello|hello in one word|回归|测试)")

rows = S.get(B + "/api/conversations", timeout=20).json()["data"]
victims = [c for c in rows if MY_TESTS.search(c["title"] or "")]
keep = [c for c in rows if c not in victims]
print("保留的对话（你自己的）:")
for c in keep:
    print("   -", c["title"], "|", c["msg_count"], "条 |", c["model"])
print("将删除的测试对话:", len(victims))
for c in victims:
    S.delete(B + "/api/conversations/" + c["id"], timeout=20)
    print("   已删:", c["title"])

# 顺带清掉这些测试对话产生的用量记录
db = sqlite3.connect(os.path.join(ROOT, "data", "app.db"))
ids = [c["id"] for c in victims]
if ids:
    q = "DELETE FROM usage WHERE conv_id IN (%s)" % ",".join("?" * len(ids))
    db.execute(q, ids)
    db.commit()
db.close()
print("已清理对应用量记录")

# 恢复用户原先的选择：qwen3.5:2b + Ultra 思考档
models = S.get(B + "/api/models", timeout=20).json()["data"]
target = next((m for m in models if m["name"] == "qwen3.5:2b"), None)
S.patch(B + "/api/settings", json={"chat": {"default_think": "ultra"}}, timeout=20)
if target:
    S.post(B + "/api/load", json={"partition_id": target["partition_id"], "model": target["name"]}, timeout=30)
    print("已恢复加载:", target["name"])
print("当前设置:", json.dumps(S.get(B + "/api/settings", timeout=20).json()["data"]["chat"], ensure_ascii=False))
