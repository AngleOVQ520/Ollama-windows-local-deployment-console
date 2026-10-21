// 全局状态（设置、加载状态、模型分组）与设置的乐观更新
import { emit, get, on, patch } from "./api.js";
import { applyLang, install, setDefaultLang } from "./i18n.js";
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

export async function boot() {
  const b = await get("/api/bootstrap");
  store.settings = b.settings;
  store.defaults = b.defaults;
  store.thinkLevels = b.think_levels;
  store.app = b.app;
  store.load = b.load;
  store.engines = b.engines;
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
export function saveSettings(partial, { immediate = false } = {}) {
  deepAssign(store.settings, partial);
  deepAssign(pendingPatch, partial);
  applyUi();
  emit("settings", store.settings);
  clearTimeout(patchTimer);
  const flush = async () => {
    const p = pendingPatch;
    pendingPatch = {};
    const r = await patch("/api/settings", p);
    store.settings = r.settings;
    emit("settings_saved", r);
    return r;
  };
  if (immediate) return flush();
  return new Promise((res, rej) => { patchTimer = setTimeout(() => flush().then(res, rej), 350); });
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

export function findModel(pid, name) {
  for (const g of store.groups) if (g.id === pid) return g.models.find((m) => m.name === name);
  return null;
}
