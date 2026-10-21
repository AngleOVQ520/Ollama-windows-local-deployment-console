// UI 工具：DOM 帮助、Popover（从按钮滑出）、Modal、Toast、Tooltip、确认框、分段控件、格式化
import { icon } from "./icons.js";
import { isEn } from "./i18n.js";

export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];
export function h(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- 格式化 ----------
export function fmtBytes(n, d = 1) {
  if (!n && n !== 0) return "—";
  if (n < 1024) return n + " B";
  const u = ["KB", "MB", "GB", "TB"];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
  return n.toFixed(n >= 100 ? 0 : d) + " " + u[i];
}
export function fmtNum(n) {
  if (n === null || n === undefined || isNaN(n)) return "—";
  n = Number(n);
  const abs = Math.abs(n);
  // 中文用「万/亿」，英文换成 K/M/B（由 i18n 决定），避免英文界面里冒出「4.48 万」
  if (isEn()) {
    if (abs >= 1e9) return (n / 1e9).toFixed(2).replace(/\.?0+$/, "") + "B";
    if (abs >= 1e6) return (n / 1e6).toFixed(2).replace(/\.?0+$/, "") + "M";
    if (abs >= 1e4) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
  } else {
    if (abs >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
    if (abs >= 1e4) return (n / 1e4).toFixed(n >= 1e6 ? 1 : 2) + " 万";
  }
  return n.toLocaleString(isEn() ? "en-US" : "zh-CN", { maximumFractionDigits: 1 });
}
export function fmtCtx(n) {
  if (!n) return "";
  if (n >= 1048576 && n % 1048576 === 0) return n / 1048576 + "M";
  if (n >= 1024 && n % 1024 === 0) return n / 1024 + "K";
  return n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "K" : String(n);
}
export function fmtMs(ms) {
  if (!ms && ms !== 0) return "—";
  if (ms < 1000) return Math.round(ms) + " ms";
  if (ms < 60000) return (ms / 1000).toFixed(ms < 10000 ? 2 : 1) + " s";
  return Math.floor(ms / 60000) + "m " + Math.round((ms % 60000) / 1000) + "s";
}
export function fmtTime(ts, withDate = true) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const p = (x) => String(x).padStart(2, "0");
  const t = `${p(d.getHours())}:${p(d.getMinutes())}`;
  if (!withDate) return t;
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${t}`;
}
export function fmtRel(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "刚刚";
  if (s < 3600) return Math.floor(s / 60) + " 分钟前";
  if (s < 86400) return Math.floor(s / 3600) + " 小时前";
  if (s < 86400 * 7) return Math.floor(s / 86400) + " 天前";
  return fmtTime(ts).slice(0, 10);
}
export function fmtParams(n, label) {
  if (label) return label;
  if (!n) return "—";
  if (n >= 1e9) return (n / 1e9).toFixed(2).replace(/\.?0+$/, "") + "B";
  if (n >= 1e6) return Math.round(n / 1e6) + "M";
  return String(n);
}
export function debounce(fn, ms = 250) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ---------- 按钮水波纹 ----------
// 只对 .btn 生效：.tool-btn / .send-btn 是 flex 容器且没有 ripple 定位规则，
// 追加的波纹 span 会作为 flex 子项撑宽按钮（连点越点越长），故不再注入。
document.addEventListener("pointerdown", (e) => {
  const b = e.target.closest(".btn");
  if (!b || b.disabled) return;
  const r = b.getBoundingClientRect();
  const s = Math.max(r.width, r.height);
  const rp = document.createElement("span");
  rp.className = "ripple";
  rp.style.cssText = `width:${s}px;height:${s}px;left:${e.clientX - r.left - s / 2}px;top:${e.clientY - r.top - s / 2}px`;
  if (getComputedStyle(b).position === "static") b.style.position = "relative";
  b.style.overflow = "hidden";
  b.appendChild(rp);
  setTimeout(() => rp.remove(), 650);
});

// ---------- Tooltip ----------
const tip = h('<div class="tip"></div>');
document.body.appendChild(tip);
let tipTimer;
document.addEventListener("mouseover", (e) => {
  const el = e.target.closest("[data-tip]");
  clearTimeout(tipTimer);
  if (!el) { tip.classList.remove("show"); return; }
  tipTimer = setTimeout(() => {
    tip.textContent = el.dataset.tip;
    const r = el.getBoundingClientRect();
    const tw = tip.offsetWidth;
    let x = r.left + r.width / 2 - tw / 2;
    x = Math.max(8, Math.min(x, innerWidth - tw - 8));
    let y = r.top - tip.offsetHeight - 8;
    if (y < 6) y = r.bottom + 8;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
    tip.classList.add("show");
  }, 380);
});
document.addEventListener("pointerdown", () => tip.classList.remove("show"));

// ---------- Popover ----------
const layer = h('<div class="pop-layer"></div>');
document.body.appendChild(layer);
let current = null;
// 记录每个锚点"刚刚关闭"的时间：快速连点时忽略重复打开，
// 避免出现"展开动画没播完又被重新触发"的持续拉伸感。
const recentClose = new WeakMap();
const REOPEN_GUARD = 260;

/**
 * 在锚点附近打开悬浮窗，动画以锚点为原点"滑出"。
 * opts: { place: 'top'|'bottom'|'auto', align: 'start'|'center'|'end', className, onClose }
 */
export function popover(anchor, content, opts = {}) {
  if (Date.now() - (recentClose.get(anchor) || 0) < REOPEN_GUARD) return null;
  if (current && current.anchor === anchor) { current.close(); return null; }
  current?.close(true);
  const el = h(`<div class="popover ${opts.className || ""}" role="dialog"></div>`);
  if (typeof content === "string") el.innerHTML = content;
  else el.appendChild(content);
  layer.appendChild(el);
  anchor.classList.add("active-pop");
  const place = () => {
    const r = anchor.getBoundingClientRect();
    const pw = el.offsetWidth, ph = el.offsetHeight;
    let side = opts.place || "auto";
    if (side === "auto") side = r.top > ph + 20 || r.top > innerHeight / 2 ? "top" : "bottom";
    let x;
    const align = opts.align || "start";
    if (align === "center") x = r.left + r.width / 2 - pw / 2;
    else if (align === "end") x = r.right - pw;
    else x = r.left;
    x = Math.max(10, Math.min(x, innerWidth - pw - 10));
    let y = side === "top" ? r.top - ph - 10 : r.bottom + 10;
    y = Math.max(10, Math.min(y, innerHeight - ph - 10));
    el.style.left = x + "px";
    el.style.top = y + "px";
    // 变换原点 = 锚点中心相对浮层的位置 → 视觉上从按钮"长出来"
    const ox = Math.max(0, Math.min(pw, r.left + r.width / 2 - x));
    el.style.setProperty("--ox", ox + "px");
    el.style.setProperty("--oy", side === "top" ? "100%" : "0%");
    el.style.setProperty("--dy", side === "top" ? "14px" : "-14px");
  };
  place();
  requestAnimationFrame(() => el.classList.add("show"));
  const onDoc = (e) => {
    if (el.contains(e.target) || anchor.contains(e.target)) return;
    if (e.target.closest(".modal-mask, .popover")) return;
    api.close();
  };
  const onKey = (e) => { if (e.key === "Escape") api.close(); };
  const onResize = () => place();
  setTimeout(() => document.addEventListener("pointerdown", onDoc), 0);
  document.addEventListener("keydown", onKey);
  addEventListener("resize", onResize);
  const api = {
    el, anchor, reposition: place,
    close(instant) {
      if (api.closed) return;
      api.closed = true;
      document.removeEventListener("pointerdown", onDoc);
      document.removeEventListener("keydown", onKey);
      removeEventListener("resize", onResize);
      anchor.classList.remove("active-pop");
      if (current === api) current = null;
      opts.onClose?.();
      recentClose.set(anchor, Date.now());  // 记录关闭时刻，挡住快速连点
      if (instant) { el.remove(); return; }
      el.classList.add("leaving");
      el.classList.remove("show");
      el.style.pointerEvents = "none";      // 退场中的浮层不再接收点击
      setTimeout(() => el.remove(), 220);
    },
  };
  current = api;
  return api;
}
export function closePopover() { current?.close(); }

// 菜单
export function menu(anchor, items, opts = {}) {
  const box = h('<div class="menu"></div>');
  for (const it of items) {
    if (!it) continue;
    if (it === "-") { box.appendChild(h("<hr>")); continue; }
    if (it.hidden) continue;
    const b = h(`<button class="${it.danger ? "danger" : ""}">${icon(it.icon || "chevR", "sm")}<span>${esc(it.label)}</span></button>`);
    b.onclick = () => { p.close(); it.action(); };
    box.appendChild(b);
  }
  const p = popover(anchor, box, { className: "menu-pop", place: opts.place || "bottom", align: opts.align || "end", onClose: opts.onClose });
  return p;
}

// ---------- Modal ----------
export function modal({ title, body, foot, wide, xl, onClose, icon: ic } = {}) {
  const mask = h(`<div class="modal-mask"><div class="modal ${wide ? "wide" : ""} ${xl ? "xl" : ""}">
    <div class="modal-head">${ic ? icon(ic) : ""}<h3>${esc(title || "")}</h3><button class="btn ghost icon sm" data-x>${icon("x")}</button></div>
    <div class="modal-body"></div>${foot !== false ? '<div class="modal-foot"></div>' : ""}</div></div>`);
  const b = $(".modal-body", mask);
  if (typeof body === "string") b.innerHTML = body; else if (body) b.appendChild(body);
  const f = $(".modal-foot", mask);
  if (f && foot) { if (typeof foot === "string") f.innerHTML = foot; else f.appendChild(foot); }
  else if (f && !foot) f.remove();
  document.body.appendChild(mask);
  requestAnimationFrame(() => mask.classList.add("show"));
  const close = () => {
    if (m.closed) return;
    m.closed = true;
    mask.classList.remove("show");
    document.removeEventListener("keydown", onKey);
    setTimeout(() => mask.remove(), 300);
    onClose?.();
  };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  mask.addEventListener("pointerdown", (e) => { if (e.target === mask) close(); });
  $("[data-x]", mask).onclick = close;
  const m = { el: mask, body: b, foot: f, close };
  return m;
}

export function confirmBox(text, { title = "确认操作", ok = "确定", danger = false, extra = "" } = {}) {
  return new Promise((resolve) => {
    const foot = h(`<div style="display:contents"><button class="btn ghost" data-c>取消</button><button class="btn ${danger ? "danger solid" : "primary"}" data-o>${esc(ok)}</button></div>`);
    let val = false;
    const m = modal({ title, body: `<p style="margin:0;line-height:1.7">${text}</p>${extra}`, foot, icon: danger ? "alert" : "info", onClose: () => resolve(val) });
    $("[data-c]", foot).onclick = () => m.close();
    $("[data-o]", foot).onclick = () => { val = m.body.querySelector("[data-extra]") ? { checked: m.body.querySelector("[data-extra]").checked } : true; m.close(); };
    setTimeout(() => $("[data-o]", foot).focus(), 50);
  });
}

export function promptBox(title, { value = "", placeholder = "", ok = "确定", hint = "" } = {}) {
  return new Promise((resolve) => {
    const body = h(`<div class="field"><input class="input" value="${esc(value)}" placeholder="${esc(placeholder)}">${hint ? `<div class="hint">${esc(hint)}</div>` : ""}</div>`);
    const foot = h(`<div style="display:contents"><button class="btn ghost" data-c>取消</button><button class="btn primary" data-o>${esc(ok)}</button></div>`);
    let val = null;
    const m = modal({ title, body, foot, onClose: () => resolve(val) });
    const inp = $("input", body);
    const submit = () => { val = inp.value; m.close(); };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
    $("[data-c]", foot).onclick = () => m.close();
    $("[data-o]", foot).onclick = submit;
    setTimeout(() => { inp.focus(); inp.select(); }, 60);
  });
}

// ---------- Toast ----------
const toasts = h('<div class="toasts"></div>');
document.body.appendChild(toasts);
export function toast(msg, type = "info", life = 3200) {
  const ic = { ok: "ok", err: "err", warn: "alert", info: "info" }[type] || "info";
  const t = h(`<div class="toast ${type}" style="--life:${life}ms">${icon(ic)}<div class="grow">${esc(msg)}</div></div>`);
  toasts.appendChild(t);
  const rm = () => { t.classList.add("out"); setTimeout(() => t.remove(), 260); };
  const timer = setTimeout(rm, life);
  t.onclick = () => { clearTimeout(timer); rm(); };
  while (toasts.children.length > 5) toasts.firstElementChild.remove();
}
export const toastErr = (e) => toast(e?.message || String(e), "err", 5000);

// ---------- 分段控件 ----------
export function seg(options, value, onChange) {
  const el = h('<div class="seg"><div class="seg-thumb"></div></div>');
  const thumb = el.firstElementChild;
  const btns = options.map(([v, label]) => {
    const b = h(`<button type="button" data-v="${esc(v)}">${label}</button>`);
    b.onclick = () => { set(v); onChange?.(v); };
    el.appendChild(b);
    return b;
  });
  const move = () => {
    const on = btns.find((b) => b.classList.contains("on"));
    if (!on || !on.offsetWidth) return;
    thumb.style.left = on.offsetLeft + "px";
    thumb.style.width = on.offsetWidth + "px";
  };
  const set = (v) => {
    btns.forEach((b) => b.classList.toggle("on", b.dataset.v === String(v)));
    requestAnimationFrame(move);
  };
  set(value);
  new ResizeObserver(move).observe(el);
  el.setValue = set;
  return el;
}

export function rangeFill(input) {
  const upd = () => {
    const min = +input.min || 0, max = +input.max || 100;
    input.style.setProperty("--p", ((input.value - min) / (max - min)) * 100 + "%");
  };
  input.addEventListener("input", upd);
  upd();
  return upd;
}

// 数字滚动动画
export function countUp(el, to, { dur = 700, fmt = fmtNum } = {}) {
  const from = +el.dataset.v || 0;
  el.dataset.v = to;
  if (document.documentElement.dataset.anim === "off" || from === to) { el.textContent = fmt(to); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur);
    const e = 1 - Math.pow(1 - k, 3);
    el.textContent = fmt(from + (to - from) * e);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

export function copyText(text) {
  const done = () => toast("已复制到剪贴板", "ok", 1600);
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(done);
  const ta = h("<textarea style='position:fixed;opacity:0'></textarea>");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  ta.remove();
  done();
}

export function download(name, text, type = "text/plain") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
