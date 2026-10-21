// Markdown 渲染：marked + DOMPurify + KaTeX（含 mhchem）+ highlight.js + Mermaid
// 代码块支持「代码 / 预览」切换：html / svg / mermaid / markdown，预览在沙箱 iframe 中运行
import { icon } from "./icons.js";
import { copyText, download, esc, h, seg, toast } from "./ui.js";
import { setting } from "./store.js";

const { marked, DOMPurify, katex, hljs } = window;
const PREVIEWABLE = { html: "html", htm: "html", xhtml: "html", svg: "svg", mermaid: "mermaid", markdown: "md", md: "md" };
const EXT = { python: "py", javascript: "js", typescript: "ts", html: "html", css: "css", json: "json", bash: "sh", shell: "sh", powershell: "ps1",
  java: "java", cpp: "cpp", c: "c", csharp: "cs", go: "go", rust: "rs", sql: "sql", yaml: "yml", xml: "xml", markdown: "md", svg: "svg", vue: "vue",
  php: "php", ruby: "rb", kotlin: "kt", swift: "swift", lua: "lua", r: "r", dart: "dart", mermaid: "mmd", latex: "tex", tex: "tex" };

// ---- 数学公式保护：先提取，渲染 Markdown 后再替换，避免 marked 破坏 \\ _ * 等 ----
function protectMath(src) {
  const store = [];
  const put = (tex, display) => { store.push({ tex, display }); return `\u0000M${store.length - 1}\u0000`; };
  // 跳过代码块与行内代码
  const parts = src.split(/(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]+`)/g);
  for (let i = 0; i < parts.length; i += 2) {
    let s = parts[i];
    s = s.replace(/\$\$([\s\S]+?)\$\$/g, (_, t) => put(t, true));
    s = s.replace(/\\\[([\s\S]+?)\\\]/g, (_, t) => put(t, true));
    s = s.replace(/\\begin\{(equation|align|gather|multline|eqnarray|cases|matrix|pmatrix|bmatrix|array)(\*?)\}([\s\S]+?)\\end\{\1\2\}/g, (m) => put(m, true));
    s = s.replace(/\\\(([\s\S]+?)\\\)/g, (_, t) => put(t, false));
    s = s.replace(/(^|[^\\$\w])\$(?!\s)((?:\\\$|[^$\n])+?)(?<!\s)\$(?![\w$])/g, (m, pre, t) => pre + put(t, false));
    parts[i] = s;
  }
  return { text: parts.join(""), store };
}
function restoreMath(html, store) {
  if (!store.length) return html;
  return html.replace(/\u0000M(\d+)\u0000/g, (_, i) => {
    const { tex, display } = store[+i];
    if (setting("chat.render_math") === false) return esc(display ? `$$${tex}$$` : `$${tex}$`);
    try {
      return katex.renderToString(tex, { displayMode: display, throwOnError: false, strict: "ignore", trust: false, output: "html" });
    } catch { return `<code>${esc(tex)}</code>`; }
  });
}

// ---- marked 配置 ----
const renderer = new marked.Renderer();
renderer.code = function ({ text, lang }) {
  const l = (lang || "").trim().split(/\s+/)[0].toLowerCase();
  return `<div class="code-src" data-lang="${esc(l)}">${esc(text)}</div>`;
};
renderer.link = function ({ href, title, tokens }) {
  const t = this.parser.parseInline(tokens);
  return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer"${title ? ` title="${esc(title)}"` : ""}>${t}</a>`;
};
marked.setOptions({ gfm: true, breaks: true, renderer });

DOMPurify.addHook("uponSanitizeAttribute", (node, data) => {
  if (data.attrName === "style" && /url\s*\(/i.test(data.attrValue)) data.keepAttr = false;
});

export function renderMarkdown(src, { streaming = false } = {}) {
  if (!src) return "";
  let text = src;
  // 流式时补齐未闭合的代码块，避免整段闪烁
  if (streaming) {
    const fences = (text.match(/^(```|~~~)/gm) || []).length;
    if (fences % 2 === 1) text += "\n```";
  }
  const { text: t, store } = protectMath(text);
  let html = marked.parse(t);
  html = restoreMath(html, store);
  return DOMPurify.sanitize(html, {
    ADD_TAGS: ["semantics", "annotation", "math", "mrow", "mi", "mo", "mn", "msup", "msub", "mfrac", "msqrt", "mtext", "mspace", "mtable", "mtr", "mtd", "mover", "munder", "munderover", "msubsup", "mstyle", "mpadded", "menclose", "mroot", "mphantom"],
    ADD_ATTR: ["target", "data-lang", "encoding", "mathvariant", "stretchy", "fence", "separator", "accent", "columnalign", "rowspacing", "columnspacing", "displaystyle", "scriptlevel", "aria-hidden"],
    FORBID_TAGS: ["style", "iframe", "form", "input", "script"],
  });
}

let mermaidReady = false;
function ensureMermaid() {
  if (mermaidReady || !window.mermaid) return !!window.mermaid;
  const dark = document.documentElement.dataset.theme !== "light";
  window.mermaid.initialize({ startOnLoad: false, theme: dark ? "dark" : "default", securityLevel: "strict",
    themeVariables: { primaryColor: dark ? "#123a30" : "#d1fae5", primaryBorderColor: "#10b981", lineColor: "#2dd4bf", fontFamily: "inherit" } });
  mermaidReady = true;
  return true;
}
let mmdSeq = 0;

// iframe 预览文档（注入 KaTeX，让 HTML 中的数学公式也能渲染）
function previewDoc(code, kind) {
  if (kind === "svg") code = `<!doctype html><html><body style="margin:0;display:grid;place-items:center;min-height:100vh;background:#fff">${code}</body></html>`;
  // 仅当出现明显的 LaTeX 特征时才启用 $...$ 行内公式，避免把价格等普通 $ 误渲染
  const plausible = /\$\$|\\\(|\\\[|\$[^$\n]{0,200}?[\\^_{}][^$\n]{0,200}?\$/.test(code);
  const delims = `[{left:"$$",right:"$$",display:true},{left:"\\\\[",right:"\\\\]",display:true},{left:"\\\\(",right:"\\\\)",display:false}${plausible ? ',{left:"$",right:"$",display:false}' : ""}]`;
  const inject = `<link rel="stylesheet" href="/static/vendor/katex/katex.min.css"><script src="/static/vendor/katex/katex.min.js"><\/script><script src="/static/vendor/katex/contrib/auto-render.min.js"><\/script><script>addEventListener("DOMContentLoaded",function(){try{renderMathInElement(document.body,{delimiters:${delims},ignoredTags:["script","noscript","style","textarea","pre","code","option"],throwOnError:false})}catch(e){}})<\/script>`;
  if (!/<html[\s>]/i.test(code)) code = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>${code}</body></html>`;
  return code.replace(/<head([^>]*)>/i, `<head$1><base target="_blank">${inject}`);
}

export function openFullPreview(code, kind = "html", lang = "html") {
  const el = h(`<div class="pv-full"><div class="pvf-bar">${icon("eye")}<b>预览</b><span class="dim mono" style="font-size:12px">${esc(lang)}</span>
    <div class="grow"></div><span class="pvf-seg"></span>
    <button class="btn sm ghost" data-a="code">${icon("code", "sm")}源码</button>
    <button class="btn sm ghost" data-a="newtab">${icon("ext", "sm")}新标签页</button>
    <button class="btn sm ghost" data-a="dl">${icon("download", "sm")}下载</button>
    <button class="btn sm icon ghost" data-a="close">${icon("x")}</button></div><div class="pvf-body"></div></div>`);
  const body = el.querySelector(".pvf-body");
  const frame = h('<iframe sandbox="allow-scripts allow-forms allow-modals allow-popups allow-pointer-lock allow-downloads"></iframe>');
  const doc = kind === "md" ? `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/static/css/base.css"><link rel="stylesheet" href="/static/css/chat.css"><link rel="stylesheet" href="/static/vendor/katex/katex.min.css"></head><body style="overflow:auto;padding:30px;background:var(--bg)" data-theme="dark"><div class="md" style="max-width:860px;margin:auto">${renderMarkdown(code)}</div></body></html>` : previewDoc(code, kind);
  frame.srcdoc = doc;
  body.appendChild(frame);
  el.querySelector(".pvf-seg").appendChild(seg([["desktop", icon("monitor", "sm")], ["tablet", icon("tablet", "sm")], ["mobile", icon("mobile", "sm")]], "desktop", (v) => {
    body.classList.remove("mobile", "tablet");
    if (v !== "desktop") body.classList.add(v);
  }));
  let showCode = false;
  el.addEventListener("click", (e) => {
    const a = e.target.closest("[data-a]")?.dataset.a;
    if (!a) return;
    if (a === "close") close();
    if (a === "dl") download(`preview.${kind === "svg" ? "svg" : kind === "md" ? "md" : "html"}`, code, "text/html");
    if (a === "newtab") { const w = window.open("", "_blank"); if (w) { w.document.open(); w.document.write(doc); w.document.close(); } }
    if (a === "code") {
      showCode = !showCode;
      body.innerHTML = "";
      if (showCode) {
        const pre = h(`<pre class="pvf-code"><code class="hljs"></code></pre>`);
        pre.firstChild.innerHTML = highlight(code, kind === "svg" ? "xml" : kind === "md" ? "markdown" : "html");
        body.appendChild(pre);
      } else body.appendChild(frame);
    }
  });
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const close = () => { el.classList.remove("show"); document.removeEventListener("keydown", onKey); setTimeout(() => el.remove(), 250); };
  document.addEventListener("keydown", onKey);
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
}

function highlight(code, lang) {
  try {
    if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
    if (code.length < 20000) return hljs.highlightAuto(code).value;
  } catch { /* fallthrough */ }
  return esc(code);
}

// 把 .code-src 占位替换为完整代码块组件。streaming 时只做高亮，不挂预览（避免 iframe 反复重建）
export function enhance(root, { streaming = false } = {}) {
  root.querySelectorAll(".code-src").forEach((src, idx) => {
    const lang = src.dataset.lang || "";
    const code = src.textContent;
    const kind = PREVIEWABLE[lang] || (lang === "xml" && /^\s*<svg[\s>]/i.test(code) ? "svg" : null) || (!lang && /^\s*<!doctype html|^\s*<html[\s>]/i.test(code) ? "html" : null);
    const hlLang = lang === "vue" ? "xml" : lang === "svg" ? "xml" : lang === "md" ? "markdown" : lang;
    const lines = code.split("\n").length;
    const block = h(`<div class="code-block${setting("chat.code_wrap") ? " wrap" : ""}">
      <div class="code-head"><span class="lang">${esc(lang || "text")}</span><span class="lines">${lines} 行</span><div class="acts"></div></div>
      <pre><code class="hljs"></code></pre><div class="preview"></div><div class="resize-h"></div></div>`);
    block.querySelector("code").innerHTML = highlight(code, hlLang);
    const acts = block.querySelector(".acts");
    if (kind && !streaming) {
      const pv = block.querySelector(".preview");
      let built = false;
      const build = () => {
        if (built) return;
        built = true;
        if (kind === "html" || kind === "svg") {
          const f = h('<iframe sandbox="allow-scripts allow-forms allow-modals allow-popups allow-pointer-lock"></iframe>');
          f.srcdoc = previewDoc(code, kind);
          pv.appendChild(f);
          // 拖动调整预览高度
          const rh = block.querySelector(".resize-h");
          rh.onpointerdown = (e) => {
            const y0 = e.clientY, h0 = f.offsetHeight;
            f.style.pointerEvents = "none";
            const mv = (ev) => { f.style.height = Math.max(160, h0 + ev.clientY - y0) + "px"; };
            const up = () => { f.style.pointerEvents = ""; removeEventListener("pointermove", mv); removeEventListener("pointerup", up); };
            addEventListener("pointermove", mv);
            addEventListener("pointerup", up);
          };
        } else if (kind === "mermaid") {
          pv.classList.add("mermaid-pv");
          if (ensureMermaid()) {
            window.mermaid.render("mmd" + (++mmdSeq), code).then(({ svg }) => { pv.innerHTML = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true }, ADD_TAGS: ["foreignObject"] }); })
              .catch((e) => { pv.innerHTML = `<div class="dim">Mermaid 语法错误：${esc(e.message || e)}</div>`; });
          }
        } else if (kind === "md") {
          pv.classList.add("md-pv", "md");
          pv.innerHTML = renderMarkdown(code);
          enhance(pv);
        }
      };
      const defMode = kind === "mermaid" && setting("chat.render_mermaid") !== false ? "preview" : (setting("chat.html_default") === "preview" ? "preview" : "code");
      const s = seg([["code", "代码"], ["preview", "预览"]], defMode, (v) => {
        if (v === "preview") build();
        block.classList.toggle("show-preview", v === "preview");
      });
      acts.appendChild(s);
      if (defMode === "preview") { build(); block.classList.add("show-preview"); }
      const fb = h(`<button class="btn xs ghost icon" data-tip="全屏预览">${icon("expand", "sm")}</button>`);
      fb.onclick = () => openFullPreview(code, kind, lang);
      acts.appendChild(fb);
    }
    const wb = h(`<button class="btn xs ghost icon" data-tip="自动换行">${icon("wrapIco", "sm")}</button>`);
    wb.onclick = () => block.classList.toggle("wrap");
    const dl = h(`<button class="btn xs ghost icon" data-tip="下载">${icon("download", "sm")}</button>`);
    dl.onclick = () => download(`code-${idx + 1}.${EXT[lang] || "txt"}`, code);
    const cp = h(`<button class="btn xs ghost">${icon("copy", "sm")}<span>复制</span></button>`);
    cp.onclick = () => { copyText(code); cp.querySelector("span").textContent = "已复制"; setTimeout(() => (cp.querySelector("span").textContent = "复制"), 1500); };
    acts.append(wb, dl, cp);
    src.replaceWith(block);
  });
  root.querySelectorAll("a[href]").forEach((a) => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
}

export function renderInto(el, src, opts = {}) {
  el.innerHTML = renderMarkdown(src, opts);
  enhance(el, opts);
}

export { toast };
