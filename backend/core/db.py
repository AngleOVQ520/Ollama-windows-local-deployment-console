"""SQLite 数据层：线程本地连接 + WAL + 简单迁移。"""
import json
import os
import sqlite3
import threading
import time

from .. import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS partitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    color TEXT DEFAULT '',
    sort INTEGER DEFAULT 0,
    is_default INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    partition_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    remark TEXT DEFAULT '',
    category TEXT DEFAULT '',
    category_auto TEXT DEFAULT '',
    family TEXT DEFAULT '',
    arch TEXT DEFAULT '',
    params INTEGER,
    params_label TEXT DEFAULT '',
    quant TEXT DEFAULT '',
    size INTEGER DEFAULT 0,
    context_length INTEGER,
    capabilities TEXT DEFAULT '[]',
    thinking_values TEXT DEFAULT '',
    source TEXT DEFAULT 'existing',
    source_path TEXT DEFAULT '',
    digest TEXT DEFAULT '',
    blob_path TEXT DEFAULT '',
    added_at REAL NOT NULL,
    modified_at REAL,
    meta_json TEXT DEFAULT '{}',
    favorite INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    present INTEGER DEFAULT 1,
    has_mtp INTEGER DEFAULT 0,
    mtp_enabled INTEGER DEFAULT 1,
    UNIQUE(partition_id, name)
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '新对话',
    model TEXT DEFAULT '',
    partition_id INTEGER,
    pinned INTEGER DEFAULT 0,
    system_prompt TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT DEFAULT '',
    thinking TEXT DEFAULT '',
    images_json TEXT DEFAULT '[]',
    files_json TEXT DEFAULT '[]',
    model TEXT DEFAULT '',
    stats_json TEXT DEFAULT '{}',
    status TEXT DEFAULT 'ok',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id, id);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    day TEXT NOT NULL,
    hour INTEGER NOT NULL,
    model TEXT DEFAULT '',
    partition_id INTEGER,
    conv_id TEXT DEFAULT '',
    source TEXT DEFAULT 'chat',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    thinking_tokens INTEGER DEFAULT 0,
    ttft_ms REAL DEFAULT 0,
    total_ms REAL DEFAULT 0,
    eval_ms REAL DEFAULT 0,
    prompt_ms REAL DEFAULT 0,
    load_ms REAL DEFAULT 0,
    think_ms REAL DEFAULT 0,
    tps REAL DEFAULT 0,
    status TEXT DEFAULT 'ok'
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);
CREATE INDEX IF NOT EXISTS idx_usage_day ON usage(day);
CREATE TABLE IF NOT EXISTS presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    sort INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    partition_id INTEGER,
    target TEXT DEFAULT '',
    status TEXT DEFAULT '',
    message TEXT DEFAULT '',
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS image_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 't2i',
    prompt TEXT DEFAULT '',
    negative TEXT DEFAULT '',
    params_json TEXT DEFAULT '{}',
    refs_json TEXT DEFAULT '[]',
    outputs_json TEXT DEFAULT '[]',
    status TEXT DEFAULT 'queued',
    stage TEXT DEFAULT '',
    error TEXT DEFAULT '',
    elapsed_ms REAL DEFAULT 0,
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_image_jobs_created ON image_jobs(created_at);
"""

DEFAULT_PRESETS = [
    ("通用助手", "你是一个乐于助人、严谨准确的 AI 助手。回答使用简体中文，结构清晰。"),
    ("代码专家", "你是资深软件工程师。给出可直接运行的完整代码，附简要说明，指出潜在风险与边界情况。"),
    ("翻译官", "你是专业翻译。把用户输入在中文与英文之间互译，保留格式，不要添加解释。"),
    ("前端设计师", "你是前端开发专家。输出单文件 HTML（内联 CSS/JS），设计现代美观、响应式，可直接预览。"),
    ("数学老师", "你是数学老师。用 LaTeX（$...$ 与 $$...$$）书写公式，逐步推导并给出最终答案。"),
]


class Database:
    def __init__(self, path=paths.DB_PATH):
        self.path = path
        self._local = threading.local()
        self._write_lock = threading.RLock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._write_lock:
            c = self.conn()
            c.executescript(SCHEMA)
            # 轻量迁移：为旧库补齐新增列
            cols = {r[1] for r in c.execute("PRAGMA table_info(models)")}
            if "has_mtp" not in cols:
                c.execute("ALTER TABLE models ADD COLUMN has_mtp INTEGER DEFAULT 0")
            if "mtp_enabled" not in cols:
                c.execute("ALTER TABLE models ADD COLUMN mtp_enabled INTEGER DEFAULT 1")
            if not c.execute("SELECT 1 FROM presets LIMIT 1").fetchone():
                now = time.time()
                c.executemany("INSERT INTO presets(name, content, sort, created_at) VALUES (?,?,?,?)",
                              [(n, t, i, now) for i, (n, t) in enumerate(DEFAULT_PRESETS)])
            c.commit()

    def conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return c

    def query(self, sql, args=()):
        return [dict(r) for r in self.conn().execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        r = self.conn().execute(sql, args).fetchone()
        return dict(r) if r else None

    def scalar(self, sql, args=()):
        r = self.conn().execute(sql, args).fetchone()
        return r[0] if r else None

    def execute(self, sql, args=()):
        with self._write_lock:
            c = self.conn()
            cur = c.execute(sql, args)
            c.commit()
            return cur.lastrowid if cur.lastrowid else cur.rowcount

    def executemany(self, sql, rows):
        with self._write_lock:
            c = self.conn()
            c.executemany(sql, rows)
            c.commit()

    def insert(self, table, data):
        keys = list(data.keys())
        sql = "INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(keys), ",".join("?" * len(keys)))
        with self._write_lock:
            c = self.conn()
            cur = c.execute(sql, [data[k] for k in keys])
            c.commit()
            return cur.lastrowid

    def update(self, table, row_id, data, key="id"):
        if not data:
            return 0
        sets = ",".join("%s=?" % k for k in data)
        return self.execute("UPDATE %s SET %s WHERE %s=?" % (table, sets, key), list(data.values()) + [row_id])

    def backup(self, dest):
        with self._write_lock:
            target = sqlite3.connect(dest)
            try:
                self.conn().backup(target)
            finally:
                target.close()


def jloads(s, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def jdumps(o):
    return json.dumps(o, ensure_ascii=False)
