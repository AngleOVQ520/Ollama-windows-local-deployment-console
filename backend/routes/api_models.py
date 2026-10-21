"""分区 / 模型 / 加载 / 下载与导入任务 接口。"""
import os
import re
import time
import uuid

from flask import Blueprint, current_app, request

from .. import paths
from ..services.jobs import suggest_model_name
from ..services.registry import CATEGORIES
from . import body, fail, ok
from ..i18n import T

bp = Blueprint("models", __name__, url_prefix="/api")


def ctx():
    return current_app.extensions["ctx"]


# ---------- 分区 ----------
@bp.get("/partitions")
def partitions():
    return ok(ctx().registry.partitions())


@bp.post("/partitions")
def create_partition():
    b = body()
    return ok(ctx().registry.create_partition(b.get("name"), b.get("path"), b.get("color", "")))


@bp.patch("/partitions/<int:pid>")
def update_partition(pid):
    return ok(ctx().registry.update_partition(pid, body()))


@bp.delete("/partitions/<int:pid>")
def delete_partition(pid):
    ld = ctx().loader.state
    if ld.model_key and ld.model_key[0] == pid:
        ctx().loader.unload()
    ctx().registry.delete_partition(pid, delete_files=request.args.get("files") == "1")
    return ok()


@bp.post("/partitions/<int:pid>/engine/<action>")
def engine_action(pid, action):
    p = ctx().registry.partition(pid)
    if not p:
        return fail(T("分区不存在"), 404)
    if action == "start":
        e = ctx().engines.get(p)
        ctx().registry.sync(pid)
        return ok(e.info())
    if action == "stop":
        ld = ctx().loader.state
        if ld.model_key and ld.model_key[0] == pid:
            ctx().loader.unload()
        e = ctx().engines.peek(pid)
        if e:
            e.stop()
        return ok()
    if action == "restart":
        e = ctx().engines.get(p, start=False)
        e.stop()
        e.start()
        return ok(e.info())
    return fail(T("未知操作"))


@bp.post("/partitions/<int:pid>/sync")
def sync_partition(pid):
    p = ctx().registry.partition(pid)
    if not p:
        return fail(T("分区不存在"), 404)
    ctx().engines.get(p)
    n = ctx().registry.sync(pid, deep=request.args.get("deep") == "1")
    return ok({"updated": n})


# ---------- 模型 ----------
@bp.get("/models")
def models():
    pid = request.args.get("partition_id", type=int)
    return ok(ctx().registry.models(pid))


@bp.get("/models/grouped")
def grouped():
    return ok(ctx().registry.grouped())


@bp.get("/models/categories")
def categories():
    used = [r["c"] for r in ctx().db.query("SELECT DISTINCT COALESCE(NULLIF(category,''), category_auto) c FROM models WHERE present=1")]
    return ok(sorted(set(CATEGORIES) | {c for c in used if c}))


@bp.get("/models/<int:mid>")
def model(mid):
    m = ctx().registry.model(mid)
    if not m:
        return fail(T("模型不存在"), 404)
    return ok(m)


@bp.patch("/models/<int:mid>")
def update_model(mid):
    b = body()
    m = ctx().registry.update_model(mid, b)
    # 切换某个模型的 MTP 开关后，若它正是当前加载的模型，立即以相同上下文重新加载使其生效。
    # 正在生成时不做强制重载（避免打断输出），新设置会在下次加载时生效。
    if "mtp_enabled" in b and m:
        ld = ctx().loader.state
        if ld.model_key == (m["partition_id"], m["name"]) and not ctx().chat.active:
            try:
                ctx().loader.select(m["partition_id"], m["name"], force=True, num_ctx=ld.num_ctx or None)
            except Exception as e:
                ctx().log.warn("models", T("重新加载以应用 MTP 设置失败：%s") % e)
    return ok(m)


@bp.delete("/models/<int:mid>")
def delete_model(mid):
    m = ctx().registry.model(mid)
    if not m:
        return fail(T("模型不存在"), 404)
    ld = ctx().loader.state
    if ld.model_key == (m["partition_id"], m["name"]):
        ctx().loader.unload()
    ctx().registry.delete_model(mid)
    return ok()


@bp.post("/models/<int:mid>/copy")
def copy_model(mid):
    m = ctx().registry.model(mid)
    if not m:
        return fail(T("模型不存在"), 404)
    from ..services.registry import normalize_name
    dst = normalize_name((body().get("name") or "").strip())
    if not dst:
        return fail(T("请输入新名称"))
    p = ctx().registry.partition(m["partition_id"])
    ctx().engines.get(p).client.copy(m["name"], dst)
    new = ctx().registry.register(p["id"], dst, m["source"], m.get("source_path", ""), remark=(m["remark"] or "") + "（副本）")
    return ok(new)


@bp.post("/models/refresh")
def refresh():
    n = ctx().registry.sync(deep=request.args.get("deep") == "1")
    return ok({"updated": n})


# ---------- 加载 ----------
@bp.get("/load")
def load_state():
    return ok(ctx().loader.current())


@bp.post("/load")
def load():
    b = body()
    return ok(ctx().loader.select(int(b.get("partition_id") or 0), b.get("model") or "", num_ctx=b.get("num_ctx")))


@bp.post("/unload")
def unload():
    ctx().loader.unload()
    return ok()


@bp.get("/running")
def running():
    out = []
    for e in list(ctx().engines.engines.values()):
        if not e.alive() or e.status != "running":
            continue
        try:
            for r in e.client.ps():
                r["partition_id"] = e.pid_
                r["partition_name"] = e.name
                out.append(r)
        except Exception:
            pass
    return ok(out)


# ---------- 任务 ----------
@bp.get("/jobs")
def jobs():
    return ok(ctx().jobs.list())


@bp.post("/jobs/pull")
def pull():
    b = body()
    return ok(ctx().jobs.start_pull(int(b.get("partition_id") or 0), b.get("model"), b.get("remark", "")))


@bp.post("/jobs/import")
def import_gguf():
    b = body()
    return ok(ctx().jobs.start_import(int(b.get("partition_id") or 0), b.get("path"), b.get("name"), b.get("remark", ""),
                                      b.get("category", ""), b.get("mode", "auto"), b.get("options")))


def _upload_dir():
    d = os.path.join(paths.TMP_DIR, "uploads")
    os.makedirs(d, exist_ok=True)
    return d


@bp.post("/gguf/upload")
def upload_gguf():
    """接收浏览器拖入的 GGUF（先落到项目临时目录，再解析元数据）。

    浏览器出于安全不暴露本地文件绝对路径，因此拖拽只能走"上传到项目内临时目录"；
    临时文件与 models 在同一磁盘，导入时会用硬链接，不产生额外拷贝。
    """
    f = request.files.get("file")
    if f is None or not f.filename:
        return fail(T("没有收到文件"))
    name = os.path.basename(f.filename)
    if not name.lower().endswith(".gguf"):
        return fail(T("只支持 .gguf 文件"))
    updir = _upload_dir()
    # 清理 24 小时前的残留上传
    now = time.time()
    for old in os.listdir(updir):
        p = os.path.join(updir, old)
        try:
            if os.path.isfile(p) and now - os.path.getmtime(p) > 86400:
                os.remove(p)
        except OSError:
            pass
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:80] or "model.gguf"
    dest = os.path.join(updir, "%s-%s" % (uuid.uuid4().hex[:10], safe))
    f.save(dest)
    info = ctx().jobs.inspect_gguf(dest)
    info["upload_path"] = dest
    info["original_name"] = name
    # 临时文件名带随机前缀，建议模型名应基于用户的原始文件名生成
    info["suggest_name"] = suggest_model_name(name, info)
    return ok(info)


@bp.get("/gguf/uploads")
def list_uploads():
    """列出临时上传（供前端清理提示）。"""
    updir = _upload_dir()
    out = []
    for f in os.listdir(updir):
        p = os.path.join(updir, f)
        if os.path.isfile(p):
            out.append({"path": p, "name": f, "size": os.path.getsize(p), "mtime": os.path.getmtime(p)})
    return ok(out)


@bp.delete("/gguf/uploads")
def clear_uploads():
    updir = _upload_dir()
    n = 0
    for f in os.listdir(updir):
        p = os.path.join(updir, f)
        try:
            if os.path.isfile(p):
                os.remove(p)
                n += 1
        except OSError:
            pass
    return ok({"removed": n})


@bp.post("/jobs/<jid>/cancel")
def cancel(jid):
    return ok(ctx().jobs.cancel(jid))


@bp.delete("/jobs")
def clear_jobs():
    ctx().jobs.clear()
    return ok()


@bp.post("/gguf/inspect")
def inspect():
    return ok(ctx().jobs.inspect_gguf(body().get("path")))


@bp.get("/library/search")
def library_search():
    """从 ollama.com 搜索模型（失败时返回内置推荐列表）。"""
    q = request.args.get("q", "").strip()
    from ..services.library import search
    return ok(search(q))


@bp.get("/library/tags")
def library_tags():
    from ..services.library import tags
    return ok(tags(request.args.get("name", "").strip()))
