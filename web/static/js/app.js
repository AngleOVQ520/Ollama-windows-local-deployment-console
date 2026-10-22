// 应用外壳：导航、路由、全局状态指示
import { connectEvents, on } from "./core/api.js";
import { t } from "./core/i18n.js";
import { icon } from "./core/icons.js";
import { boot, store } from "./core/store.js";
import { $, $$, fmtBytes, toast } from "./core/ui.js";
import * as add from "./pages/add.js";
import * as chat from "./pages/chat.js";
import * as image from "./pages/image.js";
import * as models from "./pages/models.js";
import * as settings from "./pages/settings.js";
import * as stats from "./pages/stats.js";

const ROUTES = [
  ["chat", "首页", "chat", chat],
  ["add", "添加模型", "plus", add],
  ["models", "模型列表", "list", models],
  ["image", "生图", "palette", image],
  ["stats", "用量统计", "chart", stats],
  ["settings", "设置", "gear", settings],
];
const mounted = new Set();
let currentRoute = null;

function shell() {
  document.getElementById("app").innerHTML = `
    <header class="topnav">
      <div class="brand"><span class="brand-logo">${icon("logo")}</span><div>Ollama 控制台<br><small>Local LLM Command Center</small></div></div>
      <nav class="nav-tabs"><span class="nav-ink"></span>${ROUTES.map(([id, name, ic]) => `<a href="#/${id}" data-r="${id}">${icon(ic)}<span>${name}</span></a>`).join("")}</nav>
      <div class="nav-right">
        <div class="nav-chip sys-mini" data-tip="CPU / 内存 / GPU / 显存"><span class="meter">CPU<i><b data-m="cpu"></b></i></span><span class="meter">内存<i><b data-m="mem"></b></i></span><span class="meter">GPU<i><b data-m="gpu"></b></i></span><span class="meter">显存<i><b data-m="vram"></b></i></span></div>
        <div class="nav-chip" data-load-chip><i class="dot"></i><b>未加载模型</b></div>
        <button class="btn ghost icon sm" data-theme-t data-tip="切换深色/浅色">${icon("moon")}</button>
      </div>
    </header>
    <main class="view-host">${ROUTES.map(([id]) => `<div class="view" data-view="${id}"></div>`).join("")}</main>`;
  $("[data-theme-t]").onclick = async () => {
    const { saveSettings } = await import("./core/store.js");
    const cur = document.documentElement.dataset.theme;
    saveSettings({ ui: { theme: cur === "dark" ? "light" : "dark" } });
    themeIcon();
  };
  $("[data-load-chip]").onclick = () => { location.hash = "#/chat"; };
  themeIcon();
  // shell 重建了 DOM，滑块状态随之重置（下一帧 route() 会重新定位）
  ink.el = $(".nav-ink");
  ink.ready = false;
  ink.x = ink.w = ink.press = 0;
  ink.sx = ink.sy = 1;
  bindInkGestures();
}
function themeIcon() {
  $("[data-theme-t]").innerHTML = icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon");
}

/* ===== 液态玻璃滑块 =====
   对应 GKD 的 DampedDragAnimation：三组独立弹簧（位移 / 宽度 / 按压）
   并行收敛，再用滑块速度做 X 拉伸 + Y 压缩，得到液压果冻的手感。 */
const INK_K = { x: 300, w: 360, p: 520 };  // 刚度
const INK_C = { x: 26, w: 28, p: 34 };     // 阻尼（略欠阻尼，落点有极轻回弹）
const ink = { el: null, x: 0, vx: 0, w: 0, vw: 0, press: 0, vp: 0, tx: 0, tw: 0, tp: 0, sx: 1, sy: 1, ready: false, raf: 0, last: 0 };

const animOff = () =>
  document.documentElement.dataset.anim === "off" ||
  matchMedia("(prefers-reduced-motion: reduce)").matches;

function inkApply() {
  if (!ink.el) return;
  ink.el.style.width = ink.w.toFixed(2) + "px";
  ink.el.style.transform = `translate3d(${ink.x.toFixed(2)}px,0,0) scale(${ink.sx.toFixed(4)},${ink.sy.toFixed(4)})`;
  ink.el.style.setProperty("--press", ink.press.toFixed(3));
}

function inkSnap() {
  ink.x = ink.tx; ink.w = ink.tw; ink.press = ink.tp;
  ink.vx = ink.vw = ink.vp = 0;
  ink.sx = ink.sy = 1 + 0.10 * ink.press;
  inkApply();
}

function inkStep(dt) {
  const run = (v, vv, target, k, c) => {
    vv += (-k * (v - target) - c * vv) * dt;
    return [v + vv * dt, vv];
  };
  [ink.x, ink.vx] = run(ink.x, ink.vx, ink.tx, INK_K.x, INK_C.x);
  [ink.w, ink.vw] = run(ink.w, ink.vw, ink.tw, INK_K.w, INK_C.w);
  [ink.press, ink.vp] = run(ink.press, ink.vp, ink.tp, INK_K.p, INK_C.p);

  // 速度 → 非等比形变：沿运动方向拉长、垂直方向压扁（近似保体积）
  const speed = Math.max(-1, Math.min(1, (ink.vx / 900 + ink.vw / 1200) * 0.9));
  const jelly = speed * 0.11;
  const bulge = 1 + 0.10 * ink.press;   // 按住时整体鼓起，对应 pressedScale
  ink.sx = bulge * (1 + jelly);
  ink.sy = bulge * (1 - jelly * 0.45);
  inkApply();
}

function inkSettled() {
  return Math.abs(ink.vx) < 0.4 && Math.abs(ink.x - ink.tx) < 0.15 &&
    Math.abs(ink.vw) < 0.4 && Math.abs(ink.w - ink.tw) < 0.15 &&
    Math.abs(ink.vp) < 0.4 && Math.abs(ink.press - ink.tp) < 0.002;
}

function inkStart() {
  if (!ink.el) return;
  if (animOff()) { inkSnap(); return; }
  if (ink.raf) return;
  ink.last = 0;
  const frame = (now) => {
    const dt = ink.last ? Math.min(0.034, (now - ink.last) / 1000) : 0.016;
    ink.last = now;
    inkStep(dt);
    if (inkSettled()) { inkSnap(); ink.raf = 0; ink.last = 0; return; }
    ink.raf = requestAnimationFrame(frame);
  };
  ink.raf = requestAnimationFrame(frame);
}

function moveInk() {
  const on = $(".nav-tabs a.on");
  const el = $(".nav-ink");
  if (!on || !el) return;
  ink.el = el;
  ink.tx = on.offsetLeft;
  ink.tw = on.offsetWidth;
  if (!ink.ready) {
    // 首次只定位不位移，避免启动时滑块从左上角飞入
    ink.ready = true;
    inkSnap();
    return;
  }
  inkStart();
}

/** 按住 / 拖动滑块：按下鼓起，横向拖到目标 tab 松手即切换 */
function bindInkGestures() {
  const tabs = $(".nav-tabs");
  if (!tabs) return;
  const links = $$(".nav-tabs a");
  let pid = null, moved = false, downX = 0;

  const localX = (e) => e.clientX - tabs.getBoundingClientRect().left;
  const indexAt = (x) => {
    let best = 0, dist = Infinity;
    links.forEach((a, i) => {
      const d = Math.abs(x - (a.offsetLeft + a.offsetWidth / 2));
      if (d < dist) { dist = d; best = i; }
    });
    return best;
  };
  const aim = (a) => {
    if (!a) return;
    ink.el = $(".nav-ink");
    ink.tx = a.offsetLeft;
    ink.tw = a.offsetWidth;
    inkStart();
  };

  tabs.addEventListener("pointerdown", (e) => {
    const a = e.target.closest("a");
    if (!a || e.button !== 0) return;
    pid = e.pointerId; moved = false; downX = e.clientX;
    ink.tp = 1;
    aim(a);
  });
  // 挂在 window 上：拖出导航栏范围也能继续跟手，且不影响 click 的命中目标
  window.addEventListener("pointermove", (e) => {
    if (pid !== e.pointerId) return;
    if (!moved && Math.abs(e.clientX - downX) < 4) return;
    moved = true;
    aim(links[indexAt(localX(e))]);
  });
  window.addEventListener("pointerup", (e) => {
    if (pid !== e.pointerId) return;
    pid = null;
    ink.tp = 0;
    if (moved) {
      const a = links[indexAt(localX(e))];
      if (a && a.dataset.r !== currentRoute) location.hash = "#/" + a.dataset.r;
    }
    inkStart();
  });
  window.addEventListener("pointercancel", () => {
    if (pid === null) return;
    pid = null;
    ink.tp = 0;
    inkStart();
  });
  // 拖动松手后浏览器仍会补发 click，这里拦掉避免覆盖拖拽结果
  tabs.addEventListener("click", (e) => {
    if (!moved) return;
    e.preventDefault();
    moved = false;
  }, true);
}

let lastRouteAt = 0;

function route() {
  const id = (location.hash.match(/^#\/(\w+)/) || [])[1] || "chat";
  const r = ROUTES.find((x) => x[0] === id) || ROUTES[0];
  if (r[0] === currentRoute) return; // 同一页面重复点击不重排
  const now = performance.now();
  // 快速连点时不再叠加进场动画，避免连续重排造成卡顿
  const animate = now - lastRouteAt > 260;
  lastRouteAt = now;
  currentRoute = r[0];
  $$(".nav-tabs a").forEach((a) => a.classList.toggle("on", a.dataset.r === r[0]));
  moveInk();
  $$(".view").forEach((v) => {
    const on = v.dataset.view === r[0];
    const wasOn = v.classList.contains("on");
    v.classList.remove("enter");
    v.classList.toggle("on", on);
    if (on && !wasOn && animate) {
      void v.offsetWidth;
      v.classList.add("enter");
      setTimeout(() => v.classList.remove("enter"), 420);
    }
  });
  const view = $(`[data-view="${r[0]}"]`);
  if (!mounted.has(r[0])) { mounted.add(r[0]); r[3].mount(view); }
  else r[3].onShow?.();
  document.title = `${t(r[1])} · ${t("Ollama 控制台")}`;
}

function loadChip(st) {
  const chip = $("[data-load-chip]");
  if (!chip) return;
  const dot = $(".dot", chip);
  dot.className = "dot " + ({ loaded: "ok", loading: "warn", error: "err" }[st.status] || "");
  $("b", chip).textContent = st.model ? (st.status === "loading" ? `${st.model} · ${Math.round(st.progress)}%` : st.model) : "未加载模型";
  chip.dataset.tip = st.status === "loaded" ? `已加载 · 显存 ${fmtBytes(st.size_vram)} · ctx ${st.num_ctx}` : st.status === "error" ? st.error : st.stage || "";
}

function sysMini(s) {
  const set = (k, v) => { const el = $(`[data-m="${k}"]`); if (el) el.style.width = Math.max(2, Math.min(100, v || 0)) + "%"; };
  set("cpu", s.cpu);
  set("mem", s.mem_percent);
  const g = s.gpus?.[0];
  set("gpu", g?.util || 0);
  set("vram", g ? (g.mem_used / g.mem_total) * 100 : 0);
}

async function main() {
  let b;
  try {
    b = await boot();
  } catch (e) {
    $(".boot-text").textContent = "无法连接后端：" + e.message;
    return;
  }
  shell();
  if (b.app.boot_error) toast("后台初始化未完成：" + b.app.boot_error, "err", 8000);
  connectEvents();
  on("load", loadChip);
  on("system", sysMini);
  let wasDown = false;
  on("_conn", (ok) => {
    if (!ok) { wasDown = true; toast("与后端的连接中断，正在重连…", "warn"); }
    else if (wasDown) { wasDown = false; toast("已重新连接后端", "ok"); }
  });
  on("load", (st) => {
    if (st.status === "error" && st.error) toast("模型加载失败：" + st.error, "err", 6000);
  });
  loadChip(store.load);
  addEventListener("hashchange", route);
  addEventListener("resize", moveInk);
  document.addEventListener("keydown", (e) => {
    if (e.altKey && /^[1-6]$/.test(e.key)) { e.preventDefault(); location.hash = "#/" + ROUTES[+e.key - 1][0]; }
  });
  route();
  requestAnimationFrame(moveInk);
  setTimeout(moveInk, 300);
  document.fonts?.ready.then(moveInk);
  $(".boot").classList.add("done");
  setTimeout(() => $(".boot")?.remove(), 700);
}
main();
