"""对话相关接口。"""
import json

from flask import Blueprint, Response, current_app, request, stream_with_context

from . import body, fail, ok
from ..i18n import T

bp = Blueprint("chat", __name__, url_prefix="/api")


def ctx():
    return current_app.extensions["ctx"]


@bp.get("/conversations")
def list_convs():
    return ok(ctx().chat.conversations(request.args.get("q", "").strip()))


@bp.post("/conversations")
def create_conv():
    b = body()
    return ok(ctx().chat.create(b.get("title") or "新对话", b.get("model", ""), b.get("partition_id"), b.get("system_prompt", "")))


@bp.delete("/conversations")
def delete_all():
    keep = request.args.get("keep_pinned", "1") != "0"
    return ok({"deleted": ctx().chat.delete_all(keep_pinned=keep)})


@bp.get("/conversations/<cid>")
def get_conv(cid):
    c = ctx().chat.get(cid)
    if not c:
        return fail(T("对话不存在"), 404)
    return ok(c)


@bp.patch("/conversations/<cid>")
def patch_conv(cid):
    c = ctx().chat.update(cid, body())
    if not c:
        return fail(T("对话不存在"), 404)
    return ok(c)


@bp.delete("/conversations/<cid>")
def del_conv(cid):
    ctx().chat.delete(cid)
    return ok()


@bp.post("/conversations/<cid>/duplicate")
def dup_conv(cid):
    c = ctx().chat
    src = c.get(cid)
    if not src:
        return fail(T("对话不存在"), 404)
    new = c.create(src["title"] + "（副本）", src["model"], src["partition_id"], src["system_prompt"])
    db = ctx().db
    for m in db.query("SELECT * FROM messages WHERE conv_id=? ORDER BY id", (cid,)):
        m.pop("id")
        m["conv_id"] = new["id"]
        db.insert("messages", m)
    return ok(c.get(new["id"]))


@bp.get("/conversations/<cid>/export")
def export_conv(cid):
    fmt = request.args.get("format", "md")
    text = ctx().chat.export(cid, fmt)
    c = ctx().chat.get(cid)
    from urllib.parse import quote
    name = quote((c["title"] if c else "conversation") + (".json" if fmt == "json" else ".md"))
    return Response(text, mimetype="application/json" if fmt == "json" else "text/markdown",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''%s" % name})


@bp.delete("/conversations/<cid>/messages/<int:mid>")
def del_msg(cid, mid):
    ctx().chat.delete_message(cid, mid, after=request.args.get("after") == "1")
    return ok()


@bp.patch("/conversations/<cid>/messages/<int:mid>")
def edit_msg(cid, mid):
    ctx().chat.edit_message(cid, mid, body().get("content", ""))
    return ok()


def _sse(run, start=0):
    def gen():
        yield "retry: 1500\n\n"
        for etype, data in run.iter(start):
            if etype == "ping":
                yield ": ping\n\n"
                continue
            yield "event: %s\ndata: %s\n\n" % (etype, json.dumps(data, ensure_ascii=False))
    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.post("/conversations/<cid>/send")
def send(cid):
    run = ctx().chat.send(cid, body())
    return ok({"run_id": run.id, "user_message_id": run.user_msg_id})


@bp.get("/runs/<rid>/stream")
def run_stream(rid):
    run = ctx().chat.runs.get(rid)
    if not run:
        return fail(T("任务不存在或已过期"), 404)
    return _sse(run, int(request.args.get("from", 0)))


@bp.post("/conversations/<cid>/stop")
def stop(cid):
    return ok({"stopped": ctx().chat.stop(cid=cid)})


@bp.get("/presets")
def presets():
    return ok(ctx().db.query("SELECT * FROM presets ORDER BY sort, id"))


@bp.post("/presets")
def add_preset():
    b = body()
    if not (b.get("name") or "").strip() or not (b.get("content") or "").strip():
        return fail(T("名称和内容不能为空"))
    import time
    pid = ctx().db.insert("presets", {"name": b["name"].strip()[:40], "content": b["content"], "sort": 99, "created_at": time.time()})
    return ok({"id": pid})


@bp.put("/presets/<int:pid>")
def put_preset(pid):
    b = body()
    ctx().db.update("presets", pid, {k: b[k] for k in ("name", "content") if k in b})
    return ok()


@bp.delete("/presets/<int:pid>")
def del_preset(pid):
    ctx().db.execute("DELETE FROM presets WHERE id=?", (pid,))
    return ok()
