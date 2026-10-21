"""交付前清理：重置测试数据、清理中间产物，让项目回到干净的初始状态。"""
import json
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))

# 1) 数据库：清空对话与统计（保留分区 / 模型 / 预设）
db = os.path.join(ROOT, "data", "app.db")
c = sqlite3.connect(db)
for t in ("messages", "conversations", "usage", "jobs"):
    c.execute("DELETE FROM %s" % t)
c.commit()
c.execute("VACUUM")
c.commit()
c.close()
print("数据库已重置：对话 / 消息 / 用量 / 任务记录已清空")

# 2) 设置：恢复与测试相关的项
sp = os.path.join(ROOT, "data", "settings.json")
cfg = json.load(open(sp, encoding="utf-8"))
cfg["chat"]["last_model"] = ""
cfg["chat"]["default_think"] = "off"
cfg["api"]["require_key"] = False
cfg["api"]["api_key"] = ""
cfg["ui"]["theme"] = "dark"
cfg["ui"]["sidebar_open"] = True
json.dump(cfg, open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("设置已恢复默认")

# 3) 清理中间产物
targets = ["runtime/scratch", "runtime/shots", "runtime/chrome-profile", "runtime/browsers",
           "runtime/logs", "runtime/tmp", "data/backups", "models/_test_partition", "models/test-second", "models/_probe"]
for rel in targets:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)
        print("已删除目录", rel)
    elif os.path.isfile(p):
        os.remove(p)
        print("已删除文件", rel)
for d in ("runtime/logs", "runtime/tmp"):
    os.makedirs(os.path.join(ROOT, d.replace("/", os.sep)), exist_ok=True)

# 4) 目录体积统计
def size_of(p):
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


print("\n目录体积：")
for d in ("backend", "web", "tests", "data", "models", "runtime"):
    p = os.path.join(ROOT, d)
    if os.path.isdir(p):
        print("  %-8s %8.1f MB" % (d, size_of(p) / 1e6))
print("  %-8s %8.1f MB" % ("app-cn.py", os.path.getsize(os.path.join(ROOT, "app-cn.py")) / 1e6))
