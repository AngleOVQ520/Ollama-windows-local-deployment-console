// 用量统计：KPI、时段对比、趋势、模型排行、热力图、分布、散点、明细
import { del, get, on } from "../core/api.js";
import { icon } from "../core/icons.js";
import { $, $$, confirmBox, countUp, debounce, esc, fmtMs, fmtNum, fmtTime, h, seg, toast } from "../core/ui.js";

// charts：主图（按 data-c 注册）；sparks：KPI 迷你折线图，重绘前必须整体释放
const S = { days: 30, data: null, charts: {}, sparks: [], trendMetric: "tokens" };
const echarts = window.echarts;

function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
function palette() {
  const acc = css("--acc"), acc2 = css("--acc-2");
  return [acc, acc2, "#f4715e", "#84cc16", "#fb923c", "#22d3ee", "#f43f5e", "#a3a3a3", "#14b8a6", "#eab308"].map((c, i) => (i === 9 ? "#34d399" : c));
}
function baseOpt() {
  const t2 = css("--text-2"), t3 = css("--text-3"), line = css("--line");
  return {
    color: palette(), textStyle: { fontFamily: css("--font"), color: t2 }, animationDuration: 900, animationEasing: "cubicOut",
    grid: { left: 48, right: 18, top: 36, bottom: 30, containLabel: false },
    tooltip: { trigger: "axis", backgroundColor: css("--elev"), borderColor: css("--line-2"), textStyle: { color: css("--text"), fontSize: 12 }, extraCssText: "backdrop-filter:blur(12px);border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.35)" },
    legend: { top: 0, right: 0, textStyle: { color: t2, fontSize: 12 }, icon: "roundRect", itemWidth: 10, itemHeight: 10 },
    xAxis: { axisLine: { lineStyle: { color: line } }, axisLabel: { color: t3, fontSize: 11 }, axisTick: { show: false }, splitLine: { show: false } },
    yAxis: { axisLine: { show: false }, axisLabel: { color: t3, fontSize: 11, formatter: (v) => fmtNum(v) }, splitLine: { lineStyle: { color: line, type: "dashed" } } },
  };
}
function chart(id) {
  const el = $(`[data-c="${id}"]`, S.root);
  if (!el) return null;
  let c = S.charts[id];
  if (!c || c.isDisposed()) { c = echarts.init(el, null, { renderer: "canvas" }); S.charts[id] = c; }
  return c;
}
const grad = (c, a = 0.35) => new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: c + Math.round(a * 255).toString(16).padStart(2, "0") }, { offset: 1, color: c + "00" }]);

export function mount(root) {
  S.root = root;
  root.innerHTML = `<div class="page"><div class="page-inner">
    <div class="page-head"><div><h1>用量统计</h1><p>所有对话与 API 调用的 token 用量、速度与耗时分析。</p></div>
      <div class="actions"><span class="range-seg"></span><a class="btn" href="/api/usage/export">${icon("download")}导出 CSV</a><button class="btn ghost danger" data-clear>${icon("trash")}清空</button></div></div>
    <div class="kpi-grid stagger"></div>
    <div class="period-grid stagger"></div>
    <div class="chart-grid">
      <div class="chart-card w8"><h4>${icon("chart")}用量趋势<span class="trend-seg"></span></h4><div class="sub">每日输入 / 输出 / 思考 tokens</div><div class="chart" data-c="trend"></div></div>
      <div class="chart-card w4"><h4>${icon("box")}模型用量占比</h4><div class="sub">按输出 tokens</div><div class="chart" data-c="pie"></div></div>
      <div class="chart-card w8"><h4>${icon("zap")}速度与首 Token 趋势</h4><div class="sub">每日平均生成速度（tok/s）与首 token 延迟（ms）</div><div class="chart" data-c="speed"></div></div>
      <div class="chart-card w4"><h4>${icon("gauge")}今日平均速度</h4><div class="sub">与历史最高速度对比</div><div class="chart" data-c="gauge"></div></div>
      <div class="chart-card w12"><h4>${icon("clock")}活跃时段热力图</h4><div class="sub">星期 × 小时 调用次数</div><div class="chart h220" data-c="heat"></div></div>
      <div class="chart-card"><h4>${icon("timer")}今日 24 小时分布</h4><div class="sub">调用次数与 tokens</div><div class="chart" data-c="hourly"></div></div>
      <div class="chart-card"><h4>${icon("list")}模型排行</h4><div class="sub">输出 tokens / 调用次数</div><div class="chart" data-c="rank"></div></div>
      <div class="chart-card w4"><h4>${icon("zap")}速度分布</h4><div class="sub">tok/s 区间的调用次数</div><div class="chart h220" data-c="dtps"></div></div>
      <div class="chart-card w4"><h4>${icon("timer")}首 Token 延迟分布</h4><div class="sub">ms 区间的调用次数</div><div class="chart h220" data-c="dttft"></div></div>
      <div class="chart-card w4"><h4>${icon("arrowOut")}输出长度分布</h4><div class="sub">每次输出 tokens</div><div class="chart h220" data-c="dout"></div></div>
      <div class="chart-card w8"><h4>${icon("sparkle")}输入 × 输出 散点</h4><div class="sub">每个点是一次调用，大小表示速度</div><div class="chart" data-c="scatter"></div></div>
      <div class="chart-card w4"><h4>${icon("layers")}来源与状态</h4><div class="sub">界面对话 / API；成功 / 停止 / 失败</div><div class="chart" data-c="status"></div></div>
      <div class="chart-card w12"><h4>${icon("box")}模型明细</h4><div class="model-table"></div></div>
      <div class="chart-card w12"><h4>${icon("history")}最近调用</h4><div class="recent-table"></div></div>
    </div></div></div>`;
  $(".range-seg", root).appendChild(seg([["1", "今日"], ["7", "7 天"], ["30", "30 天"], ["90", "90 天"], ["365", "1 年"]], String(S.days), (v) => { S.days = +v; load(); }));
  $(".trend-seg", root).appendChild(seg([["tokens", "Tokens"], ["calls", "调用次数"]], S.trendMetric, (v) => { S.trendMetric = v; drawTrend(); }));
  $("[data-clear]", root).onclick = async () => {
    if (!(await confirmBox("清空所有用量统计记录？对话记录不受影响。", { danger: true, ok: "清空" }))) return;
    await del("/api/usage");
    toast("已清空", "ok");
    load();
  };
  addEventListener("resize", debounce(() => Object.values(S.charts).forEach((c) => c.resize()), 150));
  on("usage", debounce(() => { if (root.closest(".view.on")) load(); }, 1500));
  // 主题切换：主图与迷你折线一起释放重建，否则迷你图仍用旧主题配色
  on("settings", debounce(() => {
    if (!root.closest(".view.on")) return;
    Object.values(S.charts).forEach((c) => c.dispose());
    S.charts = {};
    disposeSparks();
    draw();
  }, 300));
  // 页面切走时暂停动画：外壳没有卸载钩子，这里监听视图的 on 类名变化；
  // 用 __statsViewObs 标记，避免页面 DOM 被外壳重建后重复挂监听
  const view = root.closest(".view");
  if (view && !view.__statsViewObs && window.MutationObserver) {
    view.__statsViewObs = new MutationObserver(() => {
      if (view.classList.contains("on")) resumeAnim();
      else pauseAnim();
    });
    view.__statsViewObs.observe(view, { attributes: true, attributeFilter: ["class"] });
  }
  load();
}
export function onShow() {
  if (!S.root) return;
  Object.values(S.charts).forEach((c) => c.resize({ animation: false }));
  S.sparks.forEach((c) => { if (!c.isDisposed()) c.resize({ animation: false }); });
  resumeAnim();
  requestAnimationFrame(() => {
    setTimeout(() => {
      if (!S.root?.closest(".view.on")) return;
      if (Date.now() - (S.loadedAt || 0) > 20000) load();
      else Object.values(S.charts).forEach((c) => c.resize());
    }, 40);
  });
}

async function load() {
  S.data = await get(`/api/usage/report?days=${S.days}`);
  S.loadedAt = Date.now();
  draw();
}

function delta(cur, prev) {
  if (!prev) return cur ? `<span class="up">新增</span>` : `<span>—</span>`;
  const p = ((cur - prev) / prev) * 100;
  return `<span class="${p >= 0 ? "up" : "down"}">${p >= 0 ? "▲" : "▼"} ${Math.abs(p).toFixed(0)}%</span>`;
}

function draw() {
  const d = S.data;
  if (!d) return;
  disposeSparks();  // 下面会重建 KPI 卡片，旧的迷你折线实例随之释放
  const o = d.overview;
  const range = { 1: o.today, 7: o.d7, 30: o.d30 }[S.days] || summarize(d.daily);
  const kpis = [
    ["hash", "调用次数", range.calls, "", delta(o.today.calls, o.yesterday.calls) + " 今日 vs 昨日", "calls"],
    ["arrowIn", "总输入 tokens", range.input, "", `累计 ${fmtNum(o.all.input)}`, "input"],
    ["arrowOut", "总输出 tokens", range.output, "", `累计 ${fmtNum(o.all.output)}`, "output"],
    ["brain", "思考 tokens", range.thinking, "", `占输出 ${range.output ? ((range.thinking / range.output) * 100).toFixed(0) : 0}%`, "thinking"],
    ["zap", "平均速度", range.avg_tps, "tok/s", `峰值 ${(range.max_tps || 0).toFixed(1)} tok/s`, "tps"],
    ["timer", "平均首 Token", range.avg_ttft, "ms", `平均总耗时 ${fmtMs(range.avg_total)}`, "ttft"],
    ["message", "对话 / 消息", o.conversations, "", `${fmtNum(o.messages)} 条消息 · 活跃 ${o.active_days} 天`],
    ["alert", "失败 / 停止", range.errors || 0, "", `停止 ${range.stopped || 0} 次 · 成功率 ${range.calls ? (((range.calls - (range.errors || 0)) / range.calls) * 100).toFixed(1) : 100}%`],
  ];
  const kg = $(".kpi-grid", S.root);
  kg.innerHTML = "";
  for (const [ic, k, v, unit, sub, spark] of kpis) {
    const el = h(`<div class="kpi"><div class="k">${icon(ic)}${k}</div><div class="v"><span data-n>0</span>${unit ? `<small>${unit}</small>` : ""}</div><div class="d">${sub}</div>${spark ? `<div class="spark"></div>` : ""}</div>`);
    kg.appendChild(el);
    countUp($("[data-n]", el), v || 0, { fmt: unit === "tok/s" ? (x) => x.toFixed(1) : unit === "ms" ? (x) => Math.round(x).toLocaleString() : fmtNum });
    if (spark) setTimeout(() => sparkline($(".spark", el), d.daily.slice(-14).map((r) => ({ calls: r.calls, input: r.input, output: r.output, thinking: r.thinking, tps: r.tps, ttft: r.ttft }[spark]))), 30);
  }
  const pg = $(".period-grid", S.root);
  pg.innerHTML = "";
  for (const [name, s, tag] of [["今日", o.today, "1 天"], ["近 7 天", o.d7, "7 天"], ["近 30 天", o.d30, "30 天"], ["全部", o.all, o.first_ts ? "自 " + fmtTime(o.first_ts).slice(0, 10) : "—"]]) {
    pg.appendChild(h(`<div class="period"><h4>${icon("chart", "sm")}${name}<span class="tag">${tag}</span></h4>
      <div class="pr"><span>调用次数</span><b>${fmtNum(s.calls)}</b></div><div class="pr"><span>输入 tokens</span><b>${fmtNum(s.input)}</b></div>
      <div class="pr"><span>输出 tokens</span><b>${fmtNum(s.output)}</b></div><div class="pr"><span>合计 tokens</span><b>${fmtNum(s.total)}</b></div>
      <div class="pr"><span>平均速度</span><b>${(s.avg_tps || 0).toFixed(1)} tok/s</b></div><div class="pr"><span>平均首 Token</span><b>${fmtMs(s.avg_ttft)}</b></div>
      <div class="pr"><span>使用模型数</span><b>${s.models || 0}</b></div></div>`));
  }
  drawTrend();
  drawPie();
  drawSpeed();
  drawGauge(o);
  drawHeat();
  drawHourly();
  drawRank();
  drawDist("dtps", d.dist_tps, "tok/s");
  drawDist("dttft", d.dist_ttft, "ms");
  drawDist("dout", d.dist_output, "tokens");
  drawScatter();
  drawStatus();
  drawModelTable();
  drawRecent();
}

function summarize(daily) {
  const s = daily.reduce((a, r) => { a.calls += r.calls; a.input += r.input; a.output += r.output; a.thinking += r.thinking; a.errors += r.errors; return a; }, { calls: 0, input: 0, output: 0, thinking: 0, errors: 0 });
  const act = daily.filter((r) => r.tps);
  s.avg_tps = act.length ? act.reduce((a, r) => a + r.tps, 0) / act.length : 0;
  s.max_tps = Math.max(0, ...daily.map((r) => r.tps));
  const t = daily.filter((r) => r.ttft);
  s.avg_ttft = t.length ? t.reduce((a, r) => a + r.ttft, 0) / t.length : 0;
  return s;
}

/** 本页当前是否可见（主题切换等异步回调里也要判断，避免不可见时初始化图表） */
function visible() { return !!S.root?.closest(".view.on"); }

function sparkline(el, vals) {
  if (!el || !visible()) return;
  // 容器是每次重绘新建的 DOM，旧实例不会随 DOM 释放，必须显式登记后统一 dispose
  const c = echarts.init(el);
  S.sparks.push(c);
  c.setOption({ grid: { left: 0, right: 0, top: 2, bottom: 2 }, xAxis: { type: "category", show: false, data: vals.map((_, i) => i) }, yAxis: { show: false, min: 0 },
    series: [{ type: "line", data: vals, smooth: true, symbol: "none", lineStyle: { width: 1.6, color: css("--acc") }, areaStyle: { color: grad(css("--acc"), 0.3) } }], animationDuration: 1200 });
}

function disposeSparks() {
  S.sparks.forEach((c) => { if (c && !c.isDisposed()) c.dispose(); });
  S.sparks = [];
}

/** 暂停全部动画（echarts 暂停渲染循环，重新可见后 resume 继续） */
function pauseAnim() {
  Object.values(S.charts).forEach((c) => { if (!c.isDisposed()) c.getZr().animation?.pause(); });
  S.sparks.forEach((c) => { if (!c.isDisposed()) c.getZr().animation?.pause(); });
}
function resumeAnim() {
  Object.values(S.charts).forEach((c) => { if (!c.isDisposed()) c.getZr().animation?.resume(); });
  S.sparks.forEach((c) => { if (!c.isDisposed()) c.getZr().animation?.resume(); });
}

function days() { return S.data.daily.map((r) => r.day.slice(5)); }

function drawTrend() {
  const c = chart("trend");
  if (!c) return;
  const d = S.data.daily, o = baseOpt(), [a, b] = palette();
  const series = S.trendMetric === "tokens"
    ? [
      { name: "输入", type: "bar", stack: "t", data: d.map((r) => r.input), barMaxWidth: 22, itemStyle: { color: a, borderRadius: [0, 0, 0, 0] } },
      { name: "输出", type: "bar", stack: "t", data: d.map((r) => r.output - r.thinking), barMaxWidth: 22, itemStyle: { color: b } },
      { name: "思考", type: "bar", stack: "t", data: d.map((r) => r.thinking), barMaxWidth: 22, itemStyle: { color: "#f4715e", borderRadius: [5, 5, 0, 0] } },
      { name: "合计", type: "line", data: d.map((r) => r.input + r.output), smooth: true, symbol: "circle", symbolSize: 5, lineStyle: { width: 2, color: css("--text-2") }, itemStyle: { color: css("--text-2") } },
    ]
    : [{ name: "调用次数", type: "line", data: d.map((r) => r.calls), smooth: true, symbol: "circle", symbolSize: 6, lineStyle: { width: 2.5 }, areaStyle: { color: grad(a, 0.4) } },
      { name: "失败", type: "bar", data: d.map((r) => r.errors), barMaxWidth: 14, itemStyle: { color: "#f87171", borderRadius: [4, 4, 0, 0] } }];
  c.setOption({ ...o, xAxis: { ...o.xAxis, type: "category", data: days() }, yAxis: { ...o.yAxis, type: "value" }, series,
    dataZoom: d.length > 31 ? [{ type: "inside" }, { type: "slider", height: 14, bottom: 4, borderColor: "transparent" }] : [] }, true);
}

function drawPie() {
  const c = chart("pie");
  if (!c) return;
  const rows = S.data.by_model.filter((r) => r.output > 0);
  c.setOption({ color: palette(), tooltip: { ...baseOpt().tooltip, trigger: "item", formatter: (p) => `${esc(p.name)}<br>输出 <b>${fmtNum(p.value)}</b> tokens（${p.percent}%）` },
    legend: { bottom: 0, type: "scroll", textStyle: { color: css("--text-2"), fontSize: 11 }, icon: "circle", itemWidth: 8 },
    series: [{ type: "pie", radius: ["48%", "74%"], center: ["50%", "44%"], itemStyle: { borderRadius: 8, borderColor: css("--surface"), borderWidth: 3 },
      label: { show: false }, emphasis: { scale: true, scaleSize: 6, label: { show: true, formatter: "{d}%", fontSize: 16, fontWeight: 700, color: css("--text") } },
      data: rows.length ? rows.map((r) => ({ name: r.model, value: r.output })) : [{ name: "暂无数据", value: 1, itemStyle: { color: css("--surface-3") } }] }],
    graphic: rows.length ? [{ type: "text", left: "center", top: "40%", style: { text: fmtNum(rows.reduce((a, r) => a + r.output, 0)), fill: css("--text"), fontSize: 18, fontWeight: 700, textAlign: "center" } },
      { type: "text", left: "center", top: "49%", style: { text: "输出 tokens", fill: css("--text-3"), fontSize: 11, textAlign: "center" } }] : [] }, true);
}

function drawSpeed() {
  const c = chart("speed");
  if (!c) return;
  const d = S.data.daily, o = baseOpt(), [a] = palette();
  c.setOption({ ...o, xAxis: { ...o.xAxis, type: "category", data: days() },
    yAxis: [{ ...o.yAxis, type: "value", name: "tok/s", nameTextStyle: { color: css("--text-3") } }, { ...o.yAxis, type: "value", name: "ms", nameTextStyle: { color: css("--text-3") }, splitLine: { show: false } }],
    series: [{ name: "平均速度", type: "line", data: d.map((r) => r.tps || null), smooth: true, connectNulls: true, symbolSize: 6, lineStyle: { width: 2.5 }, areaStyle: { color: grad(a, 0.3) } },
      { name: "首 Token", type: "bar", yAxisIndex: 1, data: d.map((r) => r.ttft || null), barMaxWidth: 12, itemStyle: { color: "#fb923c99", borderRadius: [4, 4, 0, 0] } }] }, true);
}

function drawGauge(o) {
  const c = chart("gauge");
  if (!c) return;
  const max = Math.max(50, Math.ceil(((o.all.max_tps || 0) * 1.1) / 10) * 10);
  c.setOption({ series: [{ type: "gauge", min: 0, max, startAngle: 210, endAngle: -30, radius: "92%", center: ["50%", "58%"],
    progress: { show: true, width: 14, roundCap: true, itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: palette()[0] }, { offset: 1, color: palette()[1] }]) } },
    axisLine: { roundCap: true, lineStyle: { width: 14, color: [[1, css("--surface-3")]] } }, axisTick: { show: false }, splitLine: { show: false },
    axisLabel: { distance: -8, color: css("--text-3"), fontSize: 10 }, pointer: { show: false }, anchor: { show: false },
    title: { offsetCenter: [0, "32%"], color: css("--text-3"), fontSize: 12 },
    detail: { valueAnimation: true, offsetCenter: [0, "-4%"], fontSize: 30, fontWeight: 750, color: css("--text"), formatter: (v) => v.toFixed(1) },
    data: [{ value: o.today.avg_tps || 0, name: `tok/s · 峰值 ${(o.all.max_tps || 0).toFixed(1)}` }] }] }, true);
}

function drawHeat() {
  const c = chart("heat");
  if (!c) return;
  const data = S.data.heatmap;
  const max = Math.max(1, ...data.map((r) => r[2]));
  const o = baseOpt();
  c.setOption({ tooltip: { ...o.tooltip, trigger: "item", formatter: (p) => `周${"一二三四五六日"[p.value[1]]} ${p.value[0]}:00<br>调用 <b>${p.value[2]}</b> 次` },
    grid: { left: 40, right: 20, top: 8, bottom: 40 },
    xAxis: { type: "category", data: Array.from({ length: 24 }, (_, i) => i + "时"), axisLabel: { color: css("--text-3"), fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false }, splitArea: { show: false } },
    yAxis: { type: "category", data: ["周一", "周二", "周三", "周四", "周五", "周六", "周日"], axisLabel: { color: css("--text-3"), fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false } },
    visualMap: { min: 0, max, orient: "horizontal", left: "center", bottom: 0, itemHeight: 120, itemWidth: 10, textStyle: { color: css("--text-3"), fontSize: 10 }, inRange: { color: [css("--surface-3"), palette()[0], palette()[1]] } },
    series: [{ type: "heatmap", data, itemStyle: { borderRadius: 4, borderColor: css("--surface"), borderWidth: 2 }, emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,.4)" } } }] }, true);
}

function drawHourly() {
  const c = chart("hourly");
  if (!c) return;
  const d = S.data.hourly_today, o = baseOpt(), [a, b] = palette();
  c.setOption({ ...o, xAxis: { ...o.xAxis, type: "category", data: d.map((r) => r.hour + "时") },
    yAxis: [{ ...o.yAxis, type: "value" }, { ...o.yAxis, type: "value", splitLine: { show: false } }],
    series: [{ name: "tokens", type: "bar", data: d.map((r) => r.input + r.output), barMaxWidth: 14, itemStyle: { color: grad(a, 0.9), borderRadius: [5, 5, 0, 0] } },
      { name: "调用次数", type: "line", yAxisIndex: 1, data: d.map((r) => r.calls), smooth: true, symbolSize: 5, itemStyle: { color: b } }] }, true);
}

function drawRank() {
  const c = chart("rank");
  if (!c) return;
  const rows = [...S.data.by_model].slice(0, 10).reverse(), o = baseOpt(), [a, b] = palette();
  c.setOption({ ...o, grid: { left: 10, right: 40, top: 30, bottom: 20, containLabel: true },
    xAxis: { ...o.xAxis, type: "value", axisLabel: { ...o.xAxis.axisLabel, formatter: (v) => fmtNum(v) }, splitLine: { lineStyle: { color: css("--line"), type: "dashed" } } },
    yAxis: { type: "category", data: rows.map((r) => r.model), axisLabel: { color: css("--text-2"), fontSize: 11, width: 130, overflow: "truncate" }, axisLine: { show: false }, axisTick: { show: false } },
    series: [{ name: "输出 tokens", type: "bar", data: rows.map((r) => r.output), barMaxWidth: 16, itemStyle: { borderRadius: [0, 6, 6, 0], color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: a }, { offset: 1, color: b }]) },
      label: { show: true, position: "right", color: css("--text-3"), fontSize: 11, formatter: (p) => fmtNum(p.value) } },
      { name: "调用次数", type: "bar", data: rows.map((r) => r.calls), barMaxWidth: 6, itemStyle: { color: "#fb923c", borderRadius: [0, 4, 4, 0] } }] }, true);
}

function drawDist(id, rows, unit) {
  const c = chart(id);
  if (!c) return;
  const o = baseOpt();
  c.setOption({ ...o, grid: { left: 36, right: 10, top: 14, bottom: 40 }, legend: { show: false },
    xAxis: { ...o.xAxis, type: "category", data: rows.map((r) => r.label), axisLabel: { ...o.xAxis.axisLabel, rotate: 30, fontSize: 10 } },
    yAxis: { ...o.yAxis, type: "value", minInterval: 1 }, tooltip: { ...o.tooltip, formatter: (p) => `${p[0].name} ${unit}<br>次数 <b>${p[0].value}</b>` },
    series: [{ type: "bar", data: rows.map((r) => r.count), barMaxWidth: 26, itemStyle: { borderRadius: [6, 6, 0, 0], color: grad(palette()[id === "dttft" ? 4 : id === "dout" ? 1 : 0], 1) } }] }, true);
}

function drawScatter() {
  const c = chart("scatter");
  if (!c) return;
  const rows = S.data.scatter, o = baseOpt();
  const models = [...new Set(rows.map((r) => r.model))];
  c.setOption({ ...o, grid: { left: 54, right: 20, top: 36, bottom: 36 },
    tooltip: { ...o.tooltip, trigger: "item", formatter: (p) => `${esc(p.seriesName)}<br>输入 ${fmtNum(p.value[0])} · 输出 ${fmtNum(p.value[1])}<br>速度 ${p.value[2].toFixed(1)} tok/s · 首 token ${fmtMs(p.value[3])}<br>${fmtTime(p.value[4])}` },
    xAxis: { ...o.xAxis, type: "value", name: "输入", nameTextStyle: { color: css("--text-3") }, splitLine: { lineStyle: { color: css("--line"), type: "dashed" } }, axisLabel: { ...o.xAxis.axisLabel, formatter: (v) => fmtNum(v) } },
    yAxis: { ...o.yAxis, type: "value", name: "输出", nameTextStyle: { color: css("--text-3") } },
    series: models.map((m) => ({ name: m, type: "scatter", data: rows.filter((r) => r.model === m).map((r) => [r.input_tokens, r.output_tokens, r.tps, r.ttft_ms, r.ts]),
      symbolSize: (v) => Math.max(6, Math.min(26, Math.sqrt(v[2] || 1) * 2.2)), itemStyle: { opacity: 0.75 } })) }, true);
}

function drawStatus() {
  const c = chart("status");
  if (!c) return;
  const src = S.data.by_source, st = S.data.by_status;
  const sName = { chat: "界面对话", api: "API 调用" }, tName = { ok: "成功", stopped: "手动停止", error: "失败" }, tColor = { ok: css("--ok"), stopped: "#fb923c", error: "#f87171" };
  c.setOption({ tooltip: { ...baseOpt().tooltip, trigger: "item" }, legend: { bottom: 0, textStyle: { color: css("--text-2"), fontSize: 11 }, icon: "circle", itemWidth: 8 },
    series: [{ name: "来源", type: "pie", radius: ["0%", "38%"], center: ["50%", "45%"], label: { show: false }, itemStyle: { borderColor: css("--surface"), borderWidth: 2 },
      data: src.length ? src.map((r, i) => ({ name: sName[r.source] || r.source, value: r.calls, itemStyle: { color: palette()[i] } })) : [{ name: "无", value: 1, itemStyle: { color: css("--surface-3") } }] },
    { name: "状态", type: "pie", radius: ["52%", "70%"], center: ["50%", "45%"], label: { show: false }, itemStyle: { borderRadius: 6, borderColor: css("--surface"), borderWidth: 3 },
      data: st.length ? st.map((r) => ({ name: tName[r.status] || r.status, value: r.calls, itemStyle: { color: tColor[r.status] } })) : [{ name: "无", value: 1, itemStyle: { color: css("--surface-3") } }] }] }, true);
}

function drawModelTable() {
  const rows = S.data.by_model;
  $(".model-table", S.root).innerHTML = rows.length ? `<div class="table-wrap" style="border-radius:12px"><table class="dt"><thead><tr><th>模型</th><th class="num">调用</th><th class="num">输入</th><th class="num">输出</th><th class="num">思考</th><th class="num">平均速度</th><th class="num">峰值速度</th><th class="num">平均首 Token</th><th class="num">平均耗时</th><th class="num">失败</th><th>最近使用</th></tr></thead><tbody>
    ${rows.map((r) => `<tr><td class="mid">${esc(r.model)}</td><td class="num">${fmtNum(r.calls)}</td><td class="num">${fmtNum(r.input)}</td><td class="num">${fmtNum(r.output)}</td><td class="num">${fmtNum(r.thinking)}</td>
      <td class="num">${(r.tps || 0).toFixed(1)}</td><td class="num">${(r.max_tps || 0).toFixed(1)}</td><td class="num">${fmtMs(r.ttft)}</td><td class="num">${fmtMs(r.total_ms)}</td><td class="num">${r.errors || 0}</td><td class="dim">${fmtTime(r.last_ts)}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="empty">${icon("chart")}<div>该时间段暂无数据，去首页聊几句吧</div></div>`;
}

function drawRecent() {
  const rows = S.data.recent;
  const stTag = { ok: '<span class="tag ok">成功</span>', stopped: '<span class="tag warn">停止</span>', error: '<span class="tag err">失败</span>' };
  $(".recent-table", S.root).innerHTML = rows.length ? `<div class="table-wrap" style="border-radius:12px;max-height:420px"><table class="dt"><thead><tr><th>时间</th><th>模型</th><th>来源</th><th>对话</th><th class="num">输入</th><th class="num">输出</th><th class="num">思考</th><th class="num">速度</th><th class="num">首 Token</th><th class="num">推理</th><th class="num">总耗时</th><th>状态</th></tr></thead><tbody>
    ${rows.map((r) => `<tr><td class="dim tnum">${fmtTime(r.ts)}</td><td class="mid">${esc(r.model)}</td><td>${r.source === "api" ? '<span class="tag">API</span>' : '<span class="tag acc">对话</span>'}</td><td class="ellipsis" style="max-width:200px">${esc(r.title || "—")}</td>
      <td class="num">${fmtNum(r.input_tokens)}</td><td class="num">${fmtNum(r.output_tokens)}</td><td class="num">${fmtNum(r.thinking_tokens)}</td><td class="num">${(r.tps || 0).toFixed(1)}</td>
      <td class="num">${fmtMs(r.ttft_ms)}</td><td class="num">${r.think_ms ? fmtMs(r.think_ms) : "—"}</td><td class="num">${fmtMs(r.total_ms)}</td><td>${stTag[r.status] || esc(r.status)}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="empty">${icon("history")}<div>暂无调用记录</div></div>`;
}
