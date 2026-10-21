"""Flask 应用工厂与蓝图注册。"""
import os
import traceback

from flask import Flask, current_app, jsonify, request, send_from_directory

from .. import paths
from ..i18n import T


def ok(data=None, **kw):
    out = {"ok": True}
    if data is not None:
        out["data"] = data
    out.update(kw)
    return jsonify(out)


def fail(msg, status=400):
    return jsonify({"ok": False, "error": str(msg)}), status


def body():
    return request.get_json(silent=True) or {}


def create_app(ctx):
    app = Flask(__name__, static_folder=None)
    app.config["JSON_AS_ASCII"] = False
    # 拖拽上传 GGUF 需要较大的请求上限（模型文件可达数十 GB）
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024 * 1024
    app.json.ensure_ascii = False
    app.extensions["ctx"] = ctx

    from . import api_chat, api_image, api_misc, api_models, api_stats
    for bp in (api_chat.bp, api_models.bp, api_stats.bp, api_misc.bp, api_image.bp):
        app.register_blueprint(bp)

    @app.before_request
    def _count():
        ctx.stats["requests"] += 1

    @app.before_request
    def _lang():
        # 浏览器界面把当前语言放在 X-Lang 头（EventSource 走 ?lang=），
        # 让接口错误 / 日志 / 阶段名跟随界面语言，而不是启动入口语言
        from ..i18n import set_request_lang
        set_request_lang(request.headers.get("X-Lang") or request.args.get("lang"))

    @app.teardown_request
    def _lang_reset(exc=None):
        from ..i18n import reset_request_lang
        reset_request_lang()

    @app.errorhandler(KeyError)
    def _key(e):
        return fail(e.args[0] if e.args else T("不存在"), 404)

    @app.errorhandler(ValueError)
    def _val(e):
        return fail(e, 400)

    from ..core.gguf import GGUFError

    @app.errorhandler(GGUFError)
    def _gguf(e):
        return fail(e, 400)

    @app.errorhandler(Exception)
    def _err(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            if request.path.startswith("/api/"):
                return fail(e.description, e.code)
            return e
        ctx.log.error("http", "%s %s: %s" % (request.method, request.path, e))
        traceback.print_exc(file=open(os.path.join(paths.LOG_DIR, "errors.log"), "a", encoding="utf-8"))
        return fail(e, 500)

    @app.route("/")
    def index():
        # 把启动入口的语言注入页面：首帧就能用正确语言渲染，避免闪一下中文
        from ..i18n import get_launcher_lang
        with open(os.path.join(paths.WEB_DIR, "index.html"), "r", encoding="utf-8") as f:
            html = f.read().replace("__LANG__", get_launcher_lang())
        resp = current_app.response_class(html, mimetype="text/html")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/static/<path:p>")
    def static_files(p):
        resp = send_from_directory(paths.STATIC_DIR, p)
        if "/vendor/" in "/" + p:
            resp.headers["Cache-Control"] = "public, max-age=604800"
            # 沙箱 iframe（origin=null）中的 HTML 预览需要加载 KaTeX 字体
            resp.headers["Access-Control-Allow-Origin"] = "*"
        else:
            # 本项目自带的前端代码：强制不缓存，
            # 避免升级后浏览器仍用旧 JS（曾出现图标/交互修复不生效的情况）
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
        return resp

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(paths.STATIC_DIR, "favicon.svg", mimetype="image/svg+xml")

    return app
