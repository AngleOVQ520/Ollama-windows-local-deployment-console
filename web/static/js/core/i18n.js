// 运行时中英双语层。
//
// 页面源码始终写中文原文；英文模式下由本模块在 DOM 层把文本与提示属性换成英文。
// 这样做的好处：不需要改动任何页面模块（改动面为零、不会破坏既有交互），
// 中文模式完全不做任何替换，运行开销仅在英文模式下且只针对界面文案。
//
// 译文表分散在 ../i18n/en.*.js 中，各自导出 { dict, rules } 由本模块合并；
// 短句走 dict 精确匹配，带变量的句子走 rules 正则替换。

const ZH = "zh";
const EN = "en";

// 需要整棵子树跳过的标签 / 类名：代码、模型输出、图表与用户输入区
const PRUNE_TAGS = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CANVAS", "CODE", "PRE", "SVG"]);
const PRUNE_CLASSES = ["msg-md", "md", "katex", "mermaid", "hljs"];
// 参与翻译的属性（提示气泡、占位符、无障碍标签）
const ATTRS = ["placeholder", "data-tip", "title", "aria-label"];

const HAN = /[\u3400-\u4dbf\u4e00-\u9fff]/;
const HAN_ALL = /[\u3400-\u4dbf\u4e00-\u9fff]/g;

const dict = new Map();
const rules = [];
const textSrc = new WeakMap();     // 文本节点 → 中文原文
const textOut = new WeakMap();     // 文本节点 → 我们写入的译文（防止自我循环）
const attrSrc = new WeakMap();     // 元素 → { 属性名: 中文原文 }
const attrOut = new WeakMap();     // 元素 → { 属性名: 上次写入的译文 }

let lang = ZH;
let defaultLang = ZH;
let installed = false;
let observer = null;

export function normalize(l) {
  const s = String(l ?? "").trim().toLowerCase();
  return s.startsWith("en") ? EN : ZH;
}
export function setDefaultLang(l) {
  defaultLang = normalize(l);
}
export function resolveLang(pref) {
  const p = String(pref ?? "").trim().toLowerCase();
  return p === ZH || p === EN ? p : defaultLang;
}
export function getLang() {
  return lang;
}
export function isEn() {
  return lang === EN;
}

/** 合并一份词表：{ dict: {中文: English}, rules: [[/正则/, "替换"]] } */
export function register(fragment) {
  if (!fragment) return;
  const d = fragment.dict || fragment;
  if (d && typeof d === "object") for (const k in d) dict.set(k, d[k]);
  for (const r of fragment.rules || []) rules.push(r);
}

function interp(s, params) {
  if (!params) return s;
  return String(s).replace(/\{(\w+)\}/g, (m, k) => (k in params ? params[k] : m));
}

function applyRules(str) {
  // 词表分模块维护，难免出现「通用规则」与「具体规则」同时命中（如把任意冒号改成 ":" 的
  // 规则会抢在「当前访问地址：{x}」前面）。这里遍历全部命中项，取替换后残留中文最少的那条，
  // 让更具体的译文胜出。
  let best = null;
  let bestHan = Infinity;
  for (const [re, rep] of rules) {
    if (!re.test(str)) continue;
    const out = str.replace(re, rep);
    if (out === str) continue;
    const han = (out.match(HAN_ALL) || []).length;
    if (han < bestHan) {
      bestHan = han;
      best = out;
      if (han === 0) break;
    }
  }
  return best;
}

/** 单个字符串翻译（不查 DOM），供 JS 里手工拼接文案时使用 */
export function translate(s) {
  const str = String(s ?? "");
  if (lang === ZH || !str) return str;
  const hit = dict.get(str);
  if (hit !== undefined) return hit;
  const ruled = applyRules(str);
  if (ruled !== null) return ruled;
  // 文本节点常带着图标前后的空格，整体匹配不上时去掉首尾空白再试一次
  const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(str);
  if (m && m[2] && m[2] !== str) {
    const core = dict.get(m[2]);
    const out = core !== undefined ? core : applyRules(m[2]);
    if (out != null) return m[1] + out + m[3];
  }
  return str;
}

/** 界面文案；t("中文") 或 t("已删除 {n} 个对话", { n: 3 }) */
export function t(s, params) {
  return interp(translate(s), params);
}

// ---------------- DOM 翻译 ----------------

function pruneChildren(el) {
  // HTML 元素的 tagName 是大写，SVG/MathML 元素保持原样，统一大写后再比对
  const tag = String(el.tagName || "").toUpperCase();
  if (PRUNE_TAGS.has(tag)) return true;
  for (const c of PRUNE_CLASSES) if (el.classList && el.classList.contains(c)) return true;
  return false;
}

function trText(node) {
  const raw = node.nodeValue;
  if (!raw) return;
  // 记录「哪种语言下写入了什么」，换语言后旧记录自然失效，从而能按原文重新渲染
  const stamp = lang + "\u0000";
  if (textOut.get(node) === stamp + raw) return;
  const src = textSrc.get(node);
  if (HAN.test(raw)) {
    textSrc.set(node, raw);                         // 源码写的是中文 → 记为原文
  } else if (src === undefined) {
    return;                                         // 非中文且无原文：模型输出/数字，跳过
  }
  const out = translate(HAN.test(raw) ? raw : src);
  if (out !== raw) {
    node.nodeValue = out;
    textOut.set(node, stamp + out);
  }
}

function trAttrs(el) {
  let src = attrSrc.get(el);
  let out = attrOut.get(el);
  const stamp = lang + "\u0000";
  for (const name of ATTRS) {
    const cur = el.getAttribute(name);
    if (cur == null || !cur) continue;
    if (out && out[name] === stamp + cur) continue;  // 当前语言下正是我们写入的译文
    if (HAN.test(cur)) {
      if (!src) { src = {}; attrSrc.set(el, src); }
      src[name] = cur;
    } else if (!src || src[name] == null) {
      continue;
    }
    if (!out) { out = {}; attrOut.set(el, out); }
    const next = translate(src[name]);
    if (next !== cur) {
      el.setAttribute(name, next);
      out[name] = stamp + next;
    }
  }
}

function walk(node) {
  const type = node.nodeType;
  if (type === 3) { trText(node); return; }
  if (type !== 1) return;
  const tag = String(node.tagName || "").toUpperCase();
  if (tag === "SCRIPT" || tag === "STYLE") return;
  trAttrs(node);
  if (pruneChildren(node)) return;
  for (let c = node.firstChild; c; c = c.nextSibling) walk(c);
}

/** 首屏翻译 + 监听后续动态内容（页面是 innerHTML 重建的，必须持续观察） */
export function install() {
  if (installed || typeof document === "undefined") return;
  installed = true;
  walk(document.documentElement);
  observer = new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === "characterData") { trText(r.target); continue; }
      if (r.type === "attributes") { trAttrs(r.target); continue; }
      for (const n of r.addedNodes) walk(n);
    }
  });
  observer.observe(document.documentElement, {
    subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS,
  });
}

/** 切换语言（"auto" / "zh" / "en"）：按记录的原文重新渲染整个界面 */
export function applyLang(pref) {
  const next = resolveLang(pref);
  const d = document.documentElement;
  d.dataset.lang = next;
  d.lang = next === EN ? "en" : "zh-CN";
  if (next === lang && installed) return next;
  lang = next;
  if (installed) walk(d);
  return next;
}