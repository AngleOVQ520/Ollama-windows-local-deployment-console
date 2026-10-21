"""用量统计：记录每次调用，并提供多维聚合（日/7 天/30 天/全部、按模型、按小时、分布等）。"""
import datetime
import time


class UsageService:
    def __init__(self, db, bus):
        self.db = db
        self.bus = bus

    def record(self, stats, conv_id="", source="chat", status="ok"):
        now = time.time()
        lt = time.localtime(now)
        self.db.insert("usage", {
            "ts": now, "day": time.strftime("%Y-%m-%d", lt), "hour": lt.tm_hour,
            "model": stats.get("model") or "", "partition_id": stats.get("partition_id"), "conv_id": conv_id or "",
            "source": source, "input_tokens": int(stats.get("input_tokens") or 0),
            "output_tokens": int(stats.get("output_tokens") or 0), "thinking_tokens": int(stats.get("thinking_tokens") or 0),
            "ttft_ms": float(stats.get("ttft_ms") or 0), "total_ms": float(stats.get("total_ms") or 0),
            "eval_ms": float(stats.get("eval_ms") or 0), "prompt_ms": float(stats.get("prompt_ms") or 0),
            "load_ms": float(stats.get("load_ms") or 0), "think_ms": float(stats.get("think_ms") or 0),
            "tps": float(stats.get("tps") or 0), "status": status,
        })
        self.bus.publish("usage", {"ts": now})

    @staticmethod
    def _since(days):
        if not days:
            return 0
        start = datetime.datetime.combine(datetime.date.today() - datetime.timedelta(days=days - 1), datetime.time())
        return start.timestamp()

    def _summary(self, since, until=None):
        sql = ("SELECT COUNT(*) calls, COALESCE(SUM(input_tokens),0) input, COALESCE(SUM(output_tokens),0) output, "
               "COALESCE(SUM(thinking_tokens),0) thinking, AVG(NULLIF(tps,0)) avg_tps, MAX(tps) max_tps, "
               "AVG(NULLIF(ttft_ms,0)) avg_ttft, AVG(NULLIF(total_ms,0)) avg_total, "
               "SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) errors, "
               "SUM(CASE WHEN status='stopped' THEN 1 ELSE 0 END) stopped, "
               "COUNT(DISTINCT model) models, COUNT(DISTINCT conv_id) convs, COALESCE(SUM(total_ms),0) busy_ms "
               "FROM usage WHERE ts>=?")
        args = [since]
        if until:
            sql += " AND ts<?"
            args.append(until)
        r = self.db.one(sql, args) or {}
        for k in ("avg_tps", "max_tps", "avg_ttft", "avg_total"):
            r[k] = round(r.get(k) or 0, 2)
        r["total"] = (r.get("input") or 0) + (r.get("output") or 0)
        return r

    def overview(self):
        today = self._since(1)
        yday = today - 86400
        out = {
            "today": self._summary(today),
            "yesterday": self._summary(yday, today),
            "d7": self._summary(self._since(7)),
            "prev7": self._summary(self._since(14), self._since(7)),
            "d30": self._summary(self._since(30)),
            "all": self._summary(0),
        }
        first = self.db.scalar("SELECT MIN(ts) FROM usage")
        out["first_ts"] = first
        out["active_days"] = self.db.scalar("SELECT COUNT(DISTINCT day) FROM usage") or 0
        out["conversations"] = self.db.scalar("SELECT COUNT(*) FROM conversations") or 0
        out["messages"] = self.db.scalar("SELECT COUNT(*) FROM messages") or 0
        return out

    def daily(self, days=30):
        since = self._since(days)
        rows = {r["day"]: r for r in self.db.query(
            "SELECT day, COUNT(*) calls, SUM(input_tokens) input, SUM(output_tokens) output, SUM(thinking_tokens) thinking, "
            "AVG(NULLIF(tps,0)) tps, AVG(NULLIF(ttft_ms,0)) ttft, SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) errors "
            "FROM usage WHERE ts>=? GROUP BY day", (since,))}
        out = []
        d0 = datetime.date.today() - datetime.timedelta(days=days - 1)
        for i in range(days):
            d = (d0 + datetime.timedelta(days=i)).isoformat()
            r = rows.get(d, {})
            out.append({"day": d, "calls": r.get("calls") or 0, "input": r.get("input") or 0, "output": r.get("output") or 0,
                        "thinking": r.get("thinking") or 0, "tps": round(r.get("tps") or 0, 2),
                        "ttft": round(r.get("ttft") or 0, 1), "errors": r.get("errors") or 0})
        return out

    def hourly(self, days=1):
        """今天（或近 N 天）每小时分布。"""
        since = self._since(days)
        rows = {r["hour"]: r for r in self.db.query(
            "SELECT hour, COUNT(*) calls, SUM(input_tokens) input, SUM(output_tokens) output FROM usage WHERE ts>=? GROUP BY hour", (since,))}
        return [{"hour": h, "calls": rows.get(h, {}).get("calls") or 0, "input": rows.get(h, {}).get("input") or 0,
                 "output": rows.get(h, {}).get("output") or 0} for h in range(24)]

    def heatmap(self, days=30):
        since = self._since(days)
        rows = self.db.query("SELECT CAST(strftime('%w', ts, 'unixepoch', 'localtime') AS INTEGER) wd, hour, COUNT(*) calls "
                             "FROM usage WHERE ts>=? GROUP BY wd, hour", (since,))
        return [[r["hour"], (r["wd"] + 6) % 7, r["calls"]] for r in rows]

    def by_model(self, days=0):
        since = self._since(days)
        return self.db.query(
            "SELECT model, COUNT(*) calls, SUM(input_tokens) input, SUM(output_tokens) output, SUM(thinking_tokens) thinking, "
            "AVG(NULLIF(tps,0)) tps, MAX(tps) max_tps, AVG(NULLIF(ttft_ms,0)) ttft, AVG(NULLIF(total_ms,0)) total_ms, "
            "SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) errors, MAX(ts) last_ts "
            "FROM usage WHERE ts>=? GROUP BY model ORDER BY output DESC", (since,))

    def by_source(self, days=0):
        since = self._since(days)
        return self.db.query("SELECT source, COUNT(*) calls, SUM(input_tokens+output_tokens) tokens FROM usage WHERE ts>=? GROUP BY source", (since,))

    def by_status(self, days=0):
        since = self._since(days)
        return self.db.query("SELECT status, COUNT(*) calls FROM usage WHERE ts>=? GROUP BY status", (since,))

    def distribution(self, field, days=30):
        since = self._since(days)
        bins = {"tps": [0, 5, 10, 20, 40, 60, 80, 120, 200, 1e9], "ttft_ms": [0, 100, 250, 500, 1000, 2000, 5000, 10000, 1e12],
                "output_tokens": [0, 50, 100, 250, 500, 1000, 2000, 4000, 1e12]}[field]
        vals = [r["v"] for r in self.db.query("SELECT %s v FROM usage WHERE ts>=? AND status<>'error' AND %s>0" % (field, field), (since,))]
        out = []
        for i in range(len(bins) - 1):
            lo, hi = bins[i], bins[i + 1]
            label = ("≥%g" % lo) if hi >= 1e9 else ("%g-%g" % (lo, hi))
            out.append({"label": label, "count": sum(1 for v in vals if lo <= v < hi)})
        return out

    def recent(self, limit=50):
        rows = self.db.query("SELECT u.*, c.title FROM usage u LEFT JOIN conversations c ON c.id=u.conv_id ORDER BY u.ts DESC LIMIT ?", (limit,))
        return rows

    def scatter(self, days=30, limit=600):
        since = self._since(days)
        return self.db.query("SELECT ts, model, input_tokens, output_tokens, tps, ttft_ms FROM usage WHERE ts>=? AND status<>'error' ORDER BY ts DESC LIMIT ?", (since, limit))

    def report(self, days=30):
        return {"overview": self.overview(), "daily": self.daily(days), "hourly_today": self.hourly(1), "hourly_range": self.hourly(days),
                "heatmap": self.heatmap(days), "by_model": self.by_model(days), "by_model_all": self.by_model(0),
                "by_source": self.by_source(days), "by_status": self.by_status(days),
                "dist_tps": self.distribution("tps", days), "dist_ttft": self.distribution("ttft_ms", days),
                "dist_output": self.distribution("output_tokens", days), "scatter": self.scatter(days),
                "recent": self.recent(60), "days": days}

    def export_csv(self):
        import csv
        import io
        buf = io.StringIO()
        cols = ["ts", "day", "hour", "model", "source", "input_tokens", "output_tokens", "thinking_tokens", "ttft_ms",
                "think_ms", "eval_ms", "total_ms", "tps", "status", "conv_id"]
        w = csv.writer(buf)
        w.writerow(cols)
        for r in self.db.query("SELECT * FROM usage ORDER BY ts"):
            r["ts"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"]))
            w.writerow([r.get(c) for c in cols])
        return "\ufeff" + buf.getvalue()

    def clear(self):
        self.db.execute("DELETE FROM usage")
        self.bus.publish("usage", {"cleared": True})

    def prune(self, days):
        if days and days > 0:
            self.db.execute("DELETE FROM usage WHERE ts<?", (time.time() - days * 86400,))
