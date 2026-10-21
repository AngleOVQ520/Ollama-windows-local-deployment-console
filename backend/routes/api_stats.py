"""用量统计接口。"""
from flask import Blueprint, Response, current_app, request

from . import ok

bp = Blueprint("stats", __name__, url_prefix="/api/usage")


def ctx():
    return current_app.extensions["ctx"]


@bp.get("/report")
def report():
    days = max(1, min(365, request.args.get("days", 30, type=int)))
    return ok(ctx().usage.report(days))


@bp.get("/overview")
def overview():
    return ok(ctx().usage.overview())


@bp.get("/export")
def export():
    return Response(ctx().usage.export_csv(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=usage.csv"})


@bp.delete("")
def clear():
    ctx().usage.clear()
    return ok()
