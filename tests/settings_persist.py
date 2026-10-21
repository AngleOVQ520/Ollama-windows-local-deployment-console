"""设置持久化验证：SQLite 为真源 + 重启后自动恢复（含亮/暗主题）。
自行启动与重启后端进程。用法：python tests/settings_persist.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runtime", "pylib"))
import requests  # noqa: E402

B = "http://127.0.0.1:8848"
GLYPH = os.path.join(ROOT, "data", "settings.json")
DB = os.path.join(ROOT, "data", "app.db")
PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + str(info) if info else ""))


def start_app(extra=()):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "app-cn.py"), "--no-browser", "--plain", *extra],
                         cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    for _ in range(120):
        try:
            d = requests.get(B + "/api/bootstrap", timeout=2).json()
            if d["ok"] and d["data"]["app"]["ready"]:
                return p
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit("后端启动失败")


def stop_app(p):
    try:
        requests.post(B + "/api/app/shutdown", timeout=5)
    except Exception:
        pass
    try:
        p.wait(timeout=15)
    except Exception:
        p.terminate()
    time.sleep(1.5)


def theme():
    return requests.get(B + "/api/settings", timeout=10).json()["data"]["ui"]["theme"]


def meta():
    return requests.get(B + "/api/settings/meta", timeout=10).json()["data"]


def db_ui_theme():
    c = sqlite3.connect(DB)
    try:
        row = c.execute("SELECT value, updated_at FROM settings WHERE key='ui'").fetchone()
        return json.loads(row[0])["theme"] if row else None
    except sqlite3.OperationalError:  # 表还没建（旧版本数据库）
        return None
    finally:
        c.close()


def set_theme(v):
    return requests.patch(B + "/api/settings", json={"ui": {"theme": v}}, timeout=10).json()["data"]


orig = json.load(open(GLYPH, encoding="utf-8"))["ui"]["theme"] if os.path.exists(GLYPH) else "light"
print("重启前 settings.json 里的主题:", orig, "| 文件名存在:", os.path.exists(GLYPH), "| 数据库里已有设置:", db_ui_theme() is not None)

app = start_app()
try:
    print("== 1. 首次启动：从 settings.json 迁移到数据库")
    m = meta()
    check("载入来源为迁移", m["source"] in ("json", "db"), m["source"])
    check("主题与原设置一致", theme() == orig, theme())
    check("数据库已写入设置行", m["rows"] >= 10, "%d 行" % m["rows"])
    check("数据库里的主题正确", db_ui_theme() == orig, db_ui_theme())

    print("== 2. 修改主题 → 数据库 + 镜像同步落盘")
    other = "dark" if orig == "light" else "light"
    set_theme(other)
    time.sleep(0.4)
    check("接口返回新值", theme() == other)
    check("数据库已更新", db_ui_theme() == other)
    check("settings.json 镜像同步", json.load(open(GLYPH, encoding="utf-8"))["ui"]["theme"] == other)

    print("== 3. 重启后端：设置必须原样恢复")
    stop_app(app)
    app = start_app()
    check("重启后主题保持", theme() == other, theme())
    check("重启后来源为数据库", meta()["source"] == "db", meta()["source"])

    print("== 4. 覆盖写入其他参数也持久化（思考档位 / 上下文 / 温度）")
    requests.patch(B + "/api/settings", json={"chat": {"default_think": "max"}, "context": {"num_ctx": 12345},
                                              "params": {"temperature": 0.42}}, timeout=10)
    stop_app(app)
    app = start_app()
    s = requests.get(B + "/api/settings", timeout=10).json()["data"]
    check("思考档位持久化", s["chat"]["default_think"] == "max", s["chat"]["default_think"])
    check("上下文持久化", s["context"]["num_ctx"] == 12345, s["context"]["num_ctx"])
    check("模型参数持久化", s["params"]["temperature"] == 0.42, s["params"]["temperature"])

    print("== 5. 恢复用户原有设置")
    requests.patch(B + "/api/settings", json={"ui": {"theme": orig}, "chat": {"default_think": "ultra"},
                                              "context": {"num_ctx": 8192}, "params": {"temperature": 0.7}}, timeout=10)
    stop_app(app)
    app = start_app()
    s = requests.get(B + "/api/settings", timeout=10).json()["data"]
    check("已恢复主题", s["ui"]["theme"] == orig, s["ui"]["theme"])
    check("已恢复思考档位", s["chat"]["default_think"] == "ultra", s["chat"]["default_think"])
    check("已恢复上下文", s["context"]["num_ctx"] == 8192, s["context"]["num_ctx"])
    check("已恢复温度", s["params"]["temperature"] == 0.7, s["params"]["temperature"])
finally:
    stop_app(app)

print("\n结果：%d 通过，%d 失败" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("  失败：", f)
sys.exit(1 if FAIL else 0)
