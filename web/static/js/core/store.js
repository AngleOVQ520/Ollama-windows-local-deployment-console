// 全局状态（设置、加载状态、模型分组）与设置的乐观更新
import { emit, get, on, patch } from "./api.js";
import { applyLang, install, setDefaultLang } from "./i18n.js";
import { toast } from "./ui.js";
import "../i18n/index.js"; // 注册英文词表（模块副作用）

// 启动入口（app-cn.py / app-en.py）决定「跟随启动器」时用哪种语言
setDefaultLang(typeof window !== "undefined" && window.__LANG ? window.__LANG : "zh");

export const store = {
  settings: null,
  defaults: null,
  thinkLevels: [],
  app: {},
  load: { status: "idle", progress: 0 },
  groups: [],
  engines: [],
  system: null,
};

let pendingPatch = {};
let patchTimer = null;
// 已乐观写入本地、尚未被服务端确认的调用（按调用顺序排队，统一结算）
let optimistic = [];
// 串行提交链：保证补丁按调用顺序合并发送，且每次调用都能结算
let chain = Promise.resolve();
// 最近一次被服务端确认的完整设置快照（失败回滚的基准）
let lastConfirmed = null;
let lastFailToast = 0;

export async function boot() {
  const b = await get("/api/bootstrap");
  store.settings = b.settings;
  store.defaults = b.defaults;
  store.thinkLevels = b.think_levels;
  store.app = b.app;
  store.load = b.load;
  store.engines = b.engines;
  lastConfirmed = clone(b.settings);
  applyUi();
  await refreshGroups();
  return b;
}

export async function refreshGroups() {
  store.groups = await get("/api/models/grouped");
  emit("groups", store.groups);
  return store.groups;
}

export function setting(path) {
  return path.split(".").reduce((o, k) => (o ? o[k] : undefined), store.settings);
}

// 合并写入设置（防抖批量提交）
// 防抖只负责合并补丁：每个调用都拿到自己的结算，失败时按顺序回滚并提示。
export function saveSettings(partial, { immediate = false } = {}) {
  deepAssign(store.settings, partial);
  deepAssign(pendingPatch, partial);
  applyUi();
  emit("settings", store.settings);
  const job = { resolve: null, reject: null };
  job.promise = new Promise((res, rej) => { job.resolve = res; job.reject = rej; });
  // 不阻塞调用方链式写法；失败通过返回值（调用方自行 catch）与全局事件传递
  job.promise.catch(() => {});
  optimistic.push(job);
  if (immediate) flush();
  else {
    clearTimeout(patchTimer);
    patchTimer = setTimeout(flush, 350);
  }
  return job.promise;
}

// 重置 / 导入等直接替换整份设置后，同步回滚基准，避免之后保存失败回滚到过期快照
export function markSettingsConfirmed() {
  lastConfirmed = clone(store.settings);
}

function clone(o) {
  if (o === null || typeof o !== "object") return o;
  try { return JSON.parse(JSON.stringify(o)); } catch { return typeof structuredClone === "function" ? structuredClone(o) : { ...o }; }
}

// 依次发送待提交的补丁；排队期间新来的补丁会被并进下一次发送
function flush() {
  clearTimeout(patchTimer);
  patchTimer = null;
  chain = chain.then(drain).catch(() => {});
  return chain;
}

async function drain() {
  while (Object.keys(pendingPatch).length) {
    const p = pendingPatch;
    const items = optimistic;
    pendingPatch = {};
    optimistic = [];
    try {
      const r = await patch("/api/settings", p);
      lastConfirmed = clone(r.settings);
      store.settings = r.settings;
      emit("settings_saved", r);
      items.forEach((it) => it.resolve(r));
    } catch (e) {
      items.forEach((it) => it.reject(e));
      rollback();
      emit("settings_failed", e);
      // 向用户明确提示：保存失败，界面值已回滚（连续失败只提示一次）
      if (Date.now() - lastFailToast > 3000) {
        lastFailToast = Date.now();
        toast("设置保存失败，已恢复为上次保存的值：" + (e?.message || e), "err", 5000);
      }
      throw e;
    }
  }
}

// 失败回滚：以最近确认的服务端快照为基准，再叠加仍在排队、尚未确认的乐观修改
function rollback() {
  const base = clone(lastConfirmed || {});
  deepAssign(base, pendingPatch);
  store.settings = base;
  applyUi();
  emit("settings", store.settings);
}

function deepAssign(t, s) {
  for (const [k, v] of Object.entries(s)) {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      if (!t[k] || typeof t[k] !== "object") t[k] = {};
      deepAssign(t[k], v);
    } else t[k] = v;
  }
}

export function applyUi() {
  const ui = store.settings?.ui || {};
  const d = document.documentElement;
  let theme = ui.theme || "dark";
  if (theme === "auto") theme = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  d.dataset.theme = theme;
  d.dataset.accent = ui.accent || "emerald";
  d.dataset.anim = ui.animations === false ? "off" : "on";
  d.style.setProperty("--fs", (ui.font_size || 14) + "px");
  d.style.setProperty("--speed", String(1 / Math.max(0.3, ui.anim_speed || 1)));
  d.style.setProperty("--msg-w", (ui.msg_width || 860) + "px");
  // 语言：优先取设置里的选择，「跟随启动器」时由启动入口决定
  applyLang(ui.language || "auto");
  install();
  const hl = document.getElementById("hljs-theme");
  if (hl) hl.href = theme === "light" ? "/static/vendor/hljs/styles/github.min.css" : "/static/vendor/hljs/styles/github-dark.min.css";
  // 缓存一份到本地，下次打开页面首帧即可套用（真源仍是数据库）
  try {
    localStorage.setItem("ui-cache", JSON.stringify({
      theme: ui.theme || "dark", accent: ui.accent || "emerald", animations: ui.animations !== false,
      font_size: ui.font_size || 14, anim_speed: ui.anim_speed || 1, msg_width: ui.msg_width || 860,
    }));
  } catch { /* 隐私模式下可能不可用，忽略 */ }
}

on("load", (s) => { store.load = s; });
on("engines", (e) => { store.engines = e; });
on("system", (s) => { store.system = s; });
on("models_changed", () => refreshGroups().catch(() => {}));

// ---------------- 上下文上限（浮窗与设置页共用同一口径） ----------------
// 有模型声明时取声明值（不超过 1M）；模型未知时才回退到 128K
export const CTX_LIMIT_UNKNOWN = 131072;

export function ctxLimit(pid = store.load.partition_id, name = store.load.model) {
  const m = pid && name ? findModel(pid, name) : null;
  const declared = Number(m?.context_length) || 0;
  return declared ? Math.min(declared, 1048576) : CTX_LIMIT_UNKNOWN;
}

// 把数值钳制到 [min, max]；非法值取 min
export function clampNum(v, min, max) {
  let n = Number(v);
  if (!Number.isFinite(n)) n = min;
  return Math.min(max, Math.max(min, n));
}

export function findModel(pid, name) {
  for (const g of store.groups) if (g.id === pid) return g.models.find((m) => m.name === name);
  return null;
}
