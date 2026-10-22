"""设置 / 系统 / 事件流 / 文件浏览 / 数据管理 接口。"""
import json
import os
import shutil
import time

from flask import Blueprint, Response, current_app, request, send_file, stream_with_context

from .. import APP_NAME, __version__, i18n, paths
from ..i18n import T
from ..core.config import DEFAULTS, THINK_LEVELS
from ..services import system as sysmod
from . import body, fail, ok

bp = Blueprint("misc", __name__, url_prefix="/api")


def ctx():
    return current_app.extensions["ctx"]


@bp.get("/events")
def events():
    q = ctx().bus.subscribe()
    return Response(stream_with_context(ctx().bus.sse(q)), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.get("/bootstrap")
def bootstrap():
    c = ctx()
    return ok({
        "app": {"name": APP_NAME, "version": __version__, "root": paths.ROOT, "ready": c.ready.is_set(),
                "boot_error": c.boot_error,
                "started_at": c.started_at, "ollama": c.ollama_exe()},
        # lang：启动入口的默认语言，「跟随启动器」的前端据此决定用中文还是英文
        "lang": i18n.get_launcher_lang(),
        "settings": c.config.snapshot(), "defaults": DEFAULTS, "think_levels": THINK_LEVELS,
        "load": c.loader.current(), "engines": c.engines.list(),
    })


@bp.get("/settings")
def get_settings():
    return ok(ctx().config.snapshot())


@bp.get("/settings/meta")
def settings_meta():
    """设置存储信息（真源为 SQLite，settings.json 为镜像）。"""
    import time as _t
    db = ctx().db
    rows = db.query("SELECT key, updated_at FROM settings ORDER BY key")
    return ok({"source": ctx().config.source, "db_path": paths.DB_PATH, "mirror_path": paths.SETTINGS_PATH,
               "sections": [{"key": r["key"], "updated_at": r["updated_at"], "time": _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(r["updated_at"]))}
                            for r in rows if r["key"] != "__meta__"],
               "rows": len(rows)})


@bp.patch("/settings")
def patch_settings():
    b = body()
    if "server" in b and "port" in b["server"]:
        port = int(b["server"]["port"])
        if not 1024 <= port <= 65535:
            return fail(T("端口范围 1024-65535"))
    if "api" in b and "port" in b["api"]:
        port = int(b["api"]["port"])
        if not 1024 <= port <= 65535:
            return fail(T("端口范围 1024-65535"))
        if port == ctx().config.get("server.port"):
            return fail(T("API 端口不能与界面端口相同"))
    changed = ctx().config.update(b)
    cfg = ctx().config.section("api")
    # 开启密钥校验但还没设置密钥时，自动生成一个，避免出现"以为开了鉴权其实没有"的情况
    if cfg.get("require_key") and not cfg.get("api_key"):
        import secrets
        key = "sk-oul-" + secrets.token_urlsafe(24)
        ctx().config.update({"api": {"api_key": key}})
        changed.setdefault("api", []).append("api_key")
        ctx().log.warn("api", T("已开启 API 密钥校验并自动生成密钥"))
    return ok({"settings": ctx().config.snapshot(), "changed": changed,
               "restart_required": bool(set(changed.get("server", [])) & {"port", "host"})})


@bp.post("/settings/reset")
def reset_settings():
    ctx().config.reset(body().get("section"))
    return ok(ctx().config.snapshot())


@bp.get("/settings/export")
def export_settings():
    return Response(json.dumps(ctx().config.snapshot(), ensure_ascii=False, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=settings.json"})


@bp.post("/settings/import")
def import_settings():
    b = body()
    if not isinstance(b, dict) or not b:
        return fail(T("无效的配置文件"))
    ctx().config.update(b)
    return ok(ctx().config.snapshot())


@bp.get("/system")
def system_info():
    c = ctx()
    s = c.system.latest or c.system.sample()
    return ok({"sample": s, "history": c.system.history, "engines": c.engines.list(), "jobs": len(c.jobs.jobs),
               "uptime": time.time() - c.started_at, "requests": c.stats})


@bp.get("/system/about")
def about():
    import platform
    import sys
    c = ctx()
    size = 0
    for d in (paths.DATA_DIR,):
        for root, _, files in os.walk(d):
            for f in files:
                try:
                    size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    ver = ""
    exe = c.ollama_exe()
    for e in c.engines.engines.values():
        if e.version:
            ver = e.version
    return ok({"app": APP_NAME, "version": __version__, "python": sys.version.split()[0], "platform": platform.platform(),
               "ollama_exe": exe, "ollama_version": ver, "root": paths.ROOT, "data_size": size,
               "db_path": paths.DB_PATH, "settings_path": paths.SETTINGS_PATH, "log_dir": paths.LOG_DIR,
               "cpu": platform.processor(), "conversations": c.db.scalar("SELECT COUNT(*) FROM conversations"),
               "messages": c.db.scalar("SELECT COUNT(*) FROM messages"), "models": c.db.scalar("SELECT COUNT(*) FROM models WHERE present=1"),
               "api_url": c.api_server.url() if c.api_server else ""})


@bp.get("/api-server")
def api_server_status():
    s = ctx().api_server
    return ok(s.status() if s else {"enabled": False, "running": False})


@bp.post("/api-server/restart")
def api_server_restart():
    s = ctx().api_server
    if s:
        s.restart()
        return ok(s.status())
    return fail(T("API 服务不可用"))


@bp.post("/api-server/genkey")
def api_genkey():
    import secrets
    key = "sk-oul-" + secrets.token_urlsafe(24)
    ctx().config.update({"api": {"api_key": key}})
    return ok({"api_key": key})


@bp.get("/logs")
def logs():
    return ok(ctx().log.recent(int(request.args.get("n", 300))))


@bp.get("/logs/engine/<int:pid>")
def engine_log(pid):
    p = os.path.join(paths.LOG_DIR, "engine-p%d.log" % pid)
    if not os.path.isfile(p):
        return ok("")
    with open(p, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 60000))
        return ok(f.read().decode("utf-8", errors="replace"))


@bp.get("/fs/browse")
def fs_browse():
    return ok(sysmod.browse(request.args.get("path", ""), request.args.get("mode", "dir")))


@bp.post("/fs/mkdir")
def fs_mkdir():
    b = body()
    parent = os.path.abspath(b.get("path") or "")
    name = (b.get("name") or "").strip()
    if not os.path.isdir(parent) or not name or any(ch in name for ch in '\\/:*?"<>|'):
        return fail(T("无效的文件夹名称"))
    p = os.path.join(parent, name)
    os.makedirs(p, exist_ok=True)
    return ok({"path": p})


@bp.post("/fs/scan")
def fs_scan():
    p = body().get("path") or ""
    if not os.path.isdir(p):
        return fail(T("文件夹不存在"))
    return ok(sysmod.scan_gguf(p))


@bp.post("/fs/open")
def fs_open():
    """在资源管理器中打开文件夹（仅限分区目录与项目目录）。"""
    p = os.path.abspath(body().get("path") or "")
    allowed = [paths.ROOT] + [x["path"] for x in ctx().db.query("SELECT path FROM partitions")]
    if not any(os.path.normcase(p).startswith(os.path.normcase(a)) for a in allowed) or not os.path.exists(p):
        return fail(T("不允许打开该路径"))
    if os.name == "nt":
        os.startfile(p)
    return ok()


# ---------- 数据管理 ----------
@bp.post("/data/backup")
def data_backup():
    return ok({"name": ctx().backup()})


@bp.get("/data/backups")
def data_backups():
    return ok(ctx().backups())


@bp.get("/data/backups/<name>")
def download_backup(name):
    p = os.path.join(paths.BACKUP_DIR, os.path.basename(name), "app.db")
    if not os.path.isfile(p):
        return fail(T("备份不存在"), 404)
    return send_file(p, as_attachment=True, download_name="%s.db" % os.path.basename(name))


@bp.delete("/data/backups/<name>")
def delete_backup(name):
    shutil.rmtree(os.path.join(paths.BACKUP_DIR, os.path.basename(name)), ignore_errors=True)
    return ok()


@bp.post("/data/vacuum")
def vacuum():
    c = ctx()
    with c.db._write_lock:
        c.db.conn().execute("VACUUM")
    return ok({"size": os.path.getsize(paths.DB_PATH)})


@bp.post("/data/clear-logs")
def clear_logs():
    n = 0
    for f in os.listdir(paths.LOG_DIR):
        p = os.path.join(paths.LOG_DIR, f)
        try:
            with open(p, "w", encoding="utf-8"):
                pass
            n += 1
        except OSError:
            pass
    return ok({"cleared": n})


@bp.post("/data/clear-tmp")
def clear_tmp():
    n = 0
    for f in os.listdir(paths.TMP_DIR):
        p = os.path.join(paths.TMP_DIR, f)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            n += 1
        except OSError:
            pass
    return ok({"cleared": n})


@bp.post("/app/shutdown")
def shutdown():
    import threading

    def later():
        time.sleep(0.6)
        ctx().shutdown()
        os._exit(0)

    threading.Thread(target=later, daemon=True).start()
    return ok()
