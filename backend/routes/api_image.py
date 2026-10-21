"""生图接口：引擎/资产状态、生成任务、参考图上传、产物与历史。"""
import os

from flask import Blueprint, current_app, request, send_file

from .. import paths
from . import body, fail, ok
from ..i18n import T

bp = Blueprint("image", __name__, url_prefix="/api/image")


def ctx():
    return current_app.extensions["ctx"]


def gen():
    return ctx().image


@bp.get("/status")
def status():
    return ok(gen().status())


@bp.get("/assets")
def assets():
    r, missing, all_assets = gen().resolve()
    return ok({"resolved": r, "missing": missing, "assets": all_assets})


@bp.post("/generate")
def generate():
    b = body()
    job = gen().submit(b)
    return ok({"id": job["id"], "status": job["status"], "params": job["params"]})


@bp.get("/jobs")
def jobs():
    return ok(gen().list_jobs(int(request.args.get("limit", 40))))


@bp.get("/jobs/<jid>")
def job(jid):
    j = gen().get_job(jid)
    if not j:
        return fail(T("任务不存在"), 404)
    return ok(j)


@bp.post("/jobs/<jid>/cancel")
def cancel(jid):
    return ok({"cancelled": gen().cancel(jid)})


@bp.delete("/jobs/<jid>")
def delete(jid):
    return ok({"deleted": gen().delete(jid)})


@bp.post("/upload")
def upload():
    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        return fail(T("没有收到图片"))
    out = []
    for f in files[:8]:
        out.append(gen().upload(f))
    return ok(out)


@bp.get("/file/<jid>/<path:name>")
def file_out(jid, name):
    """产出图片（仅允许访问本任务目录内的 png）。"""
    d = os.path.join(paths.IMAGE_OUT_DIR, os.path.basename(jid))
    p = os.path.join(d, os.path.basename(name))
    if not os.path.isfile(p) or not p.lower().endswith((".png", ".webp", ".jpg")):
        return fail(T("图片不存在"), 404)
    resp = send_file(p, mimetype="image/png", conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


@bp.get("/refs/<path:name>")
def file_ref(name):
    p = os.path.join(paths.IMAGE_UPLOAD_DIR, os.path.basename(name))
    if not os.path.isfile(p):
        return fail(T("图片不存在"), 404)
    resp = send_file(p, conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@bp.get("/preview/<jid>")
def preview(jid):
    """生成中的实时预览（开启 preview 后每步覆盖写入），必须禁用缓存。"""
    p = os.path.join(paths.IMAGE_OUT_DIR, os.path.basename(jid), "preview.png")
    if not os.path.isfile(p):
        return fail(T("暂无预览"), 404)
    resp = send_file(p, mimetype="image/png", conditional=False)
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


@bp.post("/open")
def open_dir():
    """在资源管理器中打开生图输出目录。"""
    os.makedirs(paths.IMAGE_OUT_DIR, exist_ok=True)
    if os.name == "nt":
        os.startfile(paths.IMAGE_OUT_DIR)
    return ok({"path": paths.IMAGE_OUT_DIR})
