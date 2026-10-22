// 首页：历史对话 + 消息流 + 输入框
import { del, get, on, patch, post, streamRun } from "../core/api.js";
import { icon } from "../core/icons.js";
import { renderInto } from "../core/markdown.js";
import { findModel, saveSettings, setting, store } from "../core/store.js";
import { $, $$, confirmBox, copyText, debounce, download, esc, fmtCtx, fmtMs, fmtNum, fmtRel, h, menu, promptBox, toast, toastErr } from "../core/ui.js";
import { THINK_META, openContextPop, openModelPicker, openParamsPop, openThinkPop } from "./chat_pops.js";

const S = {
  convs: [], cur: null, conv: null, run: null, streaming: false, attach: [], think: "off", search: "",
  stick: true, renderTimer: null, live: null,
};

export function mount(root) {
  S.think = setting("chat.default_think") || "off";
  root.innerHTML = `<div class="chat-view">
    <aside class="sidebar ${setting("ui.sidebar_open") === false ? "collapsed" : ""}"><div class="sidebar-inner">
      <div class="sb-head"><button class="btn sb-new" data-new>${icon("plus")}新对话<kbd>Ctrl+K</kbd></button>
      <div class="sb-search">${icon("search")}<input class="input" placeholder="搜索对话…"></div></div>
      <div class="sb-list"></div>
      <div class="sb-foot"><span class="sb-count"></span><div class="grow"></div><button class="btn xs ghost" data-clear data-tip="清空未置顶的对话">${icon("trash", "sm")}清空</button></div>
    </div></aside>
    <section class="chat-main">
      <div class="chat-top"><button class="btn ghost icon sm" data-side data-tip="折叠/展开历史 (Ctrl+B)">${icon("side")}</button>
        <div class="chat-title" data-title>新对话</div><span class="tag conv-model hidden"></span>
        <div class="tools"><button class="btn ghost icon sm" data-sys data-tip="本对话系统提示词">${icon("wand")}</button>
        <button class="btn ghost icon sm" data-export data-tip="导出">${icon("download")}</button><button class="btn ghost icon sm" data-cmenu data-tip="更多">${icon("more")}</button></div></div>
      <div class="messages"><div class="msg-col"></div></div>
      <button class="btn sm to-bottom" data-bottom>${icon("chev", "sm")}回到底部</button>
      <div class="composer-wrap"><div class="composer">
        <div class="attach-row"></div>
        <textarea rows="1" placeholder="给模型发送消息…  (Enter 发送，Shift+Enter 换行，可粘贴 / 拖入图片与文本文件)"></textarea>
        <div class="comp-bar">
          <div class="model-wrap"><button class="model-btn neu" data-model><span class="m-ico">${icon("cpu", "sm")}</span><span class="m-name">选择模型</span>${icon("chev", "chev")}</button>
            <div class="load-bar"><i></i></div></div>
          <button class="tool-btn icon-only unload-btn hidden" data-unload data-tip="一键卸载模型（释放显存）">${icon("power")}</button>
          <button class="tool-btn icon-only" data-attach data-tip="添加图片 / 文件">${icon("clip")}</button>
          <input type="file" class="hidden" multiple data-file accept="image/*,.txt,.md,.py,.js,.ts,.json,.csv,.html,.css,.xml,.yaml,.yml,.log,.java,.c,.cpp,.h,.go,.rs,.sql,.sh,.ps1,.ini,.toml,.vue,.jsx,.tsx">
          <div class="spacer"></div>
          <button class="tool-btn neu" data-ctx data-tip="上下文控制：最大输入 / 输出">${icon("layers")}<span class="lbl">上下文</span><span class="val ctx-val"></span></button>
          <button class="tool-btn neu" data-params data-tip="模型参数">${icon("sliders")}<span class="lbl">参数</span></button>
          <button class="tool-btn neu" data-think data-tip="深度思考强度">${icon("brain")}<span class="lbl">思考</span><span class="val think-val"></span></button>
          <button class="send-btn" data-send disabled aria-label="发送">${icon("send", "i-send")}${icon("stop", "i-stop")}</button>
        </div></div>
        <div class="comp-foot"><span class="load-text"></span><span class="cf-left"></span></div>
      </div>
    </section></div>`;
  bind(root);
  renderLoad(store.load);
  renderThink();
  renderCtx();
  loadConvs().then(() => {
    const last = localStorage.getItem("lastConv");
    if (last && S.convs.find((c) => c.id === last)) openConv(last);
    else renderWelcome();
  });
  on("load", renderLoad);
  on("groups", () => renderLoad(store.load));
  on("convs_changed", debounce(() => loadConvs(), 300));
  on("settings", () => renderCtx());
}

/** 3D 拟态按钮的按压弹簧：按下压入、松手回弹，并用弹簧速度做轻微非等比形变（果冻感） */
function jellyPress(btn) {
  if (!btn) return;
  let s = 1, v = 0, target = 1, raf = 0, last = 0;
  const off = () => document.documentElement.dataset.anim === "off" ||
    matchMedia("(prefers-reduced-motion: reduce)").matches;
  const apply = () => {
    // 幅度钳在 8% 内，避免里面的文字跟着抖
    const sq = Math.max(-0.08, Math.min(0.08, v * 0.024));
    btn.style.transform = `scale(${(s * (1 + sq)).toFixed(4)},${(s * (1 - sq * 0.6)).toFixed(4)})`;
  };
  const start = () => {
    if (off()) { s = target; v = 0; apply(); return; }
    if (raf) return;
    last = 0;
    const frame = (now) => {
      const dt = last ? Math.min(0.034, (now - last) / 1000) : 0.016;
      last = now;
      v += (-600 * (s - target) - 26 * v) * dt;
      s += v * dt;
      if (Math.abs(v) < 0.005 && Math.abs(s - target) < 0.0008) {
        s = target; v = 0; apply(); raf = 0; return;
      }
      apply();
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
  };
  btn.addEventListener("pointerdown", () => { target = 0.91; btn.classList.add("pressing"); start(); });
  const up = () => {
    if (target === 1) return;
    target = 1;
    btn.classList.remove("pressing");
    start();
  };
  btn.addEventListener("pointerup", up);
  btn.addEventListener("pointercancel", up);
  btn.addEventListener("pointerleave", up);
}

function bind(root) {
  const ta = $("textarea", root);
  S.root = root;
  S.ta = ta;
  S.list = $(".sb-list", root);
  S.col = $(".msg-col", root);
  S.scroller = $(".messages", root);
  S.sendBtn = $("[data-send]", root);
  const autosize = () => { ta.style.height = "auto"; ta.style.height = Math.min(260, ta.scrollHeight) + "px"; updSend(); };
  ta.addEventListener("input", autosize);
  ta.addEventListener("keydown", (e) => {
    const mode = setting("chat.send_key") || "enter";
    if (e.key === "Enter" && !e.isComposing) {
      const wantSend = mode === "enter" ? !e.shiftKey && !e.ctrlKey : e.ctrlKey || e.metaKey;
      if (wantSend) { e.preventDefault(); if (!S.streaming) send(); }
    }
    if (e.key === "ArrowUp" && !ta.value && S.conv) {
      const lastUser = [...S.conv.messages].reverse().find((m) => m.role === "user");
      if (lastUser) { e.preventDefault(); ta.value = lastUser.content; autosize(); }
    }
  });
  ta.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) { e.preventDefault(); addFiles(files); }
  });
  const comp = $(".composer", root);
  comp.addEventListener("dragover", (e) => { e.preventDefault(); comp.classList.add("drag"); });
  comp.addEventListener("dragleave", () => comp.classList.remove("drag"));
  comp.addEventListener("drop", (e) => { e.preventDefault(); comp.classList.remove("drag"); addFiles([...e.dataTransfer.files]); });
  $("[data-attach]", root).onclick = () => $("[data-file]", root).click();
  $("[data-file]", root).onchange = (e) => { addFiles([...e.target.files]); e.target.value = ""; };
  S.sendBtn.onclick = () => (S.streaming ? stop() : send());
  $("[data-unload]", root).onclick = async (e) => {
    const b = e.currentTarget;
    if (b.disabled) return;
    b.classList.add("loading");
    try {
      await post("/api/unload");
      toast("已卸载，显存已释放", "ok");
    } catch (err) { toastErr(err); } finally { b.classList.remove("loading"); }
  };
  ["[data-model]", "[data-ctx]", "[data-params]", "[data-think]"].forEach((sel) => jellyPress($(sel, root)));
  $("[data-model]", root).onclick = (e) => openModelPicker(e.currentTarget, selectModel);
  $("[data-ctx]", root).onclick = (e) => openContextPop(e.currentTarget, renderCtx);
  $("[data-params]", root).onclick = (e) => openParamsPop(e.currentTarget);
  $("[data-think]", root).onclick = (e) => openThinkPop(e.currentTarget, S.think, (v) => { S.think = v; saveSettings({ chat: { default_think: v } }); renderThink(); });
  $("[data-new]", root).onclick = newConv;
  $("[data-side]", root).onclick = toggleSide;
  $("[data-clear]", root).onclick = async () => {
    if (!(await confirmBox("将删除所有<b>未置顶</b>的对话，此操作不可恢复。", { danger: true, ok: "全部删除" }))) return;
    const r = await del("/api/conversations?keep_pinned=1");
    toast(`已删除 ${r.deleted} 个对话`, "ok");
    if (S.cur && !S.convs.find((c) => c.id === S.cur && c.pinned)) { S.cur = null; S.conv = null; renderWelcome(); }
    loadConvs();
  };
  $(".sb-search input", root).oninput = debounce((e) => { S.search = e.target.value.trim(); loadConvs(); }, 250);
  $("[data-title]", root).onclick = () => S.conv && renameConv(S.conv.id, S.conv.title);
  $("[data-sys]", root).onclick = editSystem;
  $("[data-export]", root).onclick = (e) => S.conv && menu(e.currentTarget, [
    { label: "导出为 Markdown", icon: "file", action: () => exportConv("md") },
    { label: "导出为 JSON", icon: "code", action: () => exportConv("json") },
    { label: "复制全部内容", icon: "copy", action: () => copyText(S.conv.messages.map((m) => `【${m.role === "user" ? "用户" : "助手"}】\n${m.content}`).join("\n\n")) },
  ]);
  $("[data-cmenu]", root).onclick = (e) => S.conv && menu(e.currentTarget, convMenuItems(S.conv));
  S.scroller.addEventListener("scroll", () => {
    const near = S.scroller.scrollHeight - S.scroller.scrollTop - S.scroller.clientHeight < 80;
    S.stick = near;
    $("[data-bottom]", root).classList.toggle("show", !near);
    $(".chat-top", root).classList.toggle("scrolled", S.scroller.scrollTop > 4);
  });
  $("[data-bottom]", root).onclick = () => { S.stick = true; scrollBottom(true); };
  document.addEventListener("keydown", (e) => {
    if (!root.closest(".view.on")) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); newConv(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") { e.preventDefault(); toggleSide(); }
    if (e.key === "Escape" && S.streaming && !document.querySelector(".popover, .modal-mask")) stop();
    if (e.key === "/" && document.activeElement === document.body) { e.preventDefault(); ta.focus(); }
  });
}

function toggleSide() {
  const sb = $(".sidebar", S.root);
  sb.classList.toggle("collapsed");
  saveSettings({ ui: { sidebar_open: !sb.classList.contains("collapsed") } });
}

// ---------------- 模型选择与加载进度 ----------------
async function selectModel(pid, name) {
  try {
    const st = await post("/api/load", { partition_id: pid, model: name });
    if (st.pending) toast(`正在输出，将在本次回复结束后切换到 ${name}`, "info");
  } catch (e) { toastErr(e); }
}

function curModel() {
  const ld = store.load;
  if (ld.pending) return { pid: ld.pending.partition_id, name: ld.pending.model };
  if (ld.model) return { pid: ld.partition_id, name: ld.model };
  return null;
}

function renderLoad(st) {
  if (!S.root) return;
  const btn = $("[data-model]", S.root);
  const bar = $(".load-bar", S.root);
  const txt = $(".load-text", S.root);
  const unloadBtn = $("[data-unload]", S.root);
  clearTimeout(S.textTimer);
  txt.classList.remove("fade");
  const m = st.model ? findModel(st.partition_id, st.model) : null;
  btn.classList.toggle("loaded", st.status === "loaded");
  btn.classList.toggle("loading", st.status === "loading");
  // 只有真的有模型驻留时才显示「一键卸载」
  unloadBtn.classList.toggle("hidden", !(st.model && (st.status === "loaded" || st.status === "loading")));
  unloadBtn.classList.toggle("on", st.status === "loaded");
  unloadBtn.dataset.tip = st.pending ? "等待切换中，暂不能卸载" : `一键卸载 ${st.model || ""}（释放显存）`;
  unloadBtn.disabled = !!st.pending || S.streaming;
  $(".m-ico", btn).innerHTML = icon(st.status === "loading" ? "refresh" : st.status === "error" ? "alert" : "cpu", "sm");
  $(".m-name", btn).textContent = st.model ? (m?.remark || st.model) : "选择模型";
  btn.dataset.tip = st.model ? `${st.model}${m ? " · " + m.partition_name : ""}` : "选择模型（按分区分类）";
  bar.className = "load-bar";
  const i = $("i", bar);
  if (st.status === "loading") {
    bar.classList.add("show");
    i.style.width = st.progress + "%";
    txt.textContent = `${st.stage || "加载中"} · ${Math.round(st.progress)}%`;
  } else if (st.status === "loaded") {
    bar.classList.add("show", "done");
    i.style.width = "100%";
    txt.textContent = `已就绪 · ${fmtCtx(st.num_ctx)} ctx · ${(st.load_ms / 1000).toFixed(1)}s`;
    txt.classList.remove("fade");
    clearTimeout(S.barTimer);
    S.barTimer = setTimeout(() => {
      if (store.load.status !== "loaded") return;
      bar.classList.remove("show");
      // 就绪提示留几秒后淡出，避免长期占据底栏（右侧已有常驻的 ctx 信息）
      S.textTimer = setTimeout(() => {
        const cur = store.load;
        if (cur.status === "loaded" && cur.model === st.model && !cur.pending) {
          txt.classList.add("fade");
          setTimeout(() => { if (txt.classList.contains("fade")) txt.textContent = ""; }, 400);
        }
      }, 5000);
    }, 2200);
  } else if (st.status === "error") {
    bar.classList.add("show", "err");
    txt.textContent = "加载失败：" + (st.error || "");
    txt.title = st.error || "";
  } else {
    txt.textContent = "";
  }
  if (st.pending) txt.textContent = `⏳ 回复结束后切换到 ${st.pending.model}`;
  updSend();
  renderThink();
}

function renderThink() {
  if (!S.root) return;
  const b = $("[data-think]", S.root);
  const ld = store.load;
  const m = ld.model ? findModel(ld.partition_id, ld.model) : null;
  const unsupported = m && !(m.capabilities || []).includes("thinking");
  b.classList.toggle("on", S.think !== "off" && !unsupported);
  $(".think-val", b).textContent = unsupported ? "不支持" : THINK_META[S.think]?.name || S.think;
}

function renderCtx() {
  if (!S.root) return;
  const c = setting("context") || {};
  $(".ctx-val", S.root).textContent = fmtCtx(c.num_ctx);
  const p = setting("params") || {};
  $(".cf-left", S.root).innerHTML = `<span>ctx ${fmtCtx(c.num_ctx)}</span><span>· 输出上限 ${c.max_output || "∞"}</span><span>· 温度 ${p.use_model_defaults ? "模型默认" : p.temperature}</span><span>· 内容由本地模型生成，请注意甄别</span>`;
}

function updSend() {
  if (!S.sendBtn) return;
  S.sendBtn.classList.toggle("stop", S.streaming);
  S.sendBtn.setAttribute("aria-label", S.streaming ? "停止" : "发送");
  S.sendBtn.dataset.tip = S.streaming ? "停止生成 (Esc)" : "发送 (Enter)";
  const un = S.root && $("[data-unload]", S.root);
  if (un) {
    const st = store.load;
    un.disabled = S.streaming || !!st.pending;
    un.dataset.tip = S.streaming ? "生成中不可卸载" : st.pending ? "等待切换中，暂不能卸载" : `一键卸载 ${st.model || ""}（释放显存）`;
  }
  const has = S.ta.value.trim() || S.attach.length;
  S.sendBtn.disabled = !S.streaming && (!has || !curModel());
}

// ---------------- 附件 ----------------
const TEXT_EXT = /\.(txt|md|py|js|ts|json|csv|html?|css|xml|ya?ml|log|java|c|cpp|h|hpp|go|rs|sql|sh|ps1|ini|toml|vue|jsx|tsx|bat|cfg|conf|kt|swift|rb|php|lua|r|tex)$/i;
async function addFiles(files) {
  for (const f of files) {
    if (f.type.startsWith("image/")) {
      if (f.size > 20 * 1024 * 1024) { toast(`${f.name} 超过 20MB`, "warn"); continue; }
      const data = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(f); });
      S.attach.push({ type: "image", name: f.name, data });
    } else if (TEXT_EXT.test(f.name) || f.type.startsWith("text/")) {
      if (f.size > 2 * 1024 * 1024) { toast(`${f.name} 超过 2MB`, "warn"); continue; }
      S.attach.push({ type: "file", name: f.name, text: await f.text(), size: f.size });
    } else toast(`不支持的文件类型：${f.name}`, "warn");
  }
  const ld = store.load;
  const m = ld.model ? findModel(ld.partition_id, ld.model) : null;
  if (S.attach.some((a) => a.type === "image") && m && !(m.capabilities || []).includes("vision")) toast("当前模型不支持图片输入，图片将被忽略", "warn");
  renderAttach();
}
function renderAttach() {
  const row = $(".attach-row", S.root);
  row.innerHTML = "";
  S.attach.forEach((a, i) => {
    const el = h(`<div class="att-item">${a.type === "image" ? `<img src="${a.data}" alt="">` : `${icon("file", "sm")}<span class="ellipsis" style="max-width:160px">${esc(a.name)}</span>`}<button class="x">${icon("x")}</button></div>`);
    $(".x", el).onclick = () => { S.attach.splice(i, 1); renderAttach(); };
    row.appendChild(el);
  });
  updSend();
}

// ---------------- 会话列表 ----------------
async function loadConvs() {
  S.convs = await get("/api/conversations" + (S.search ? "?q=" + encodeURIComponent(S.search) : ""));
  renderConvs();
}
function groupOf(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = (day(now) - day(d)) / 86400000;
  if (diff < 1) return "今天";
  if (diff < 2) return "昨天";
  if (diff < 7) return "7 天内";
  if (diff < 30) return "30 天内";
  return "更早";
}
function renderConvs() {
  const list = S.list;
  list.innerHTML = "";
  $(".sb-count", S.root).textContent = `${S.convs.length} 个对话`;
  if (!S.convs.length) {
    list.innerHTML = `<div class="empty" style="padding:40px 10px">${icon("message")}<div>${S.search ? "没有找到匹配的对话" : "暂无对话"}</div></div>`;
    return;
  }
  let lastG = null;
  for (const c of S.convs) {
    const g = c.pinned ? "置顶" : groupOf(c.updated_at);
    if (g !== lastG) { list.appendChild(h(`<div class="sb-group">${g === "置顶" ? icon("pin", "sm") : ""}${g}</div>`)); lastG = g; }
    const it = h(`<div class="conv-item ${c.id === S.cur ? "on" : ""}" data-id="${c.id}">
      ${c.running ? '<span class="ci-run"></span>' : ""}
      <div class="ci-main"><div class="ci-title">${esc(c.title)}</div><div class="ci-sub">${esc(c.model || "")}${c.model ? " · " : ""}${fmtRel(c.updated_at)} · ${c.msg_count} 条</div></div>
      ${c.pinned ? icon("pin", "ci-pin") : ""}
      <div class="ci-act"><button class="btn xs ghost icon" data-m>${icon("more", "sm")}</button></div></div>`);
    it.onclick = (e) => { if (!e.target.closest("[data-m]")) openConv(c.id); };
    it.ondblclick = () => renameConv(c.id, c.title);
    $("[data-m]", it).onclick = (e) => {
      e.stopPropagation();
      it.classList.add("menu-open");
      menu(e.currentTarget, convMenuItems(c), { onClose: () => it.classList.remove("menu-open") });
    };
    list.appendChild(it);
  }
}
function convMenuItems(c) {
  return [
    { label: "打开", icon: "chat", action: () => openConv(c.id) },
    { label: c.pinned ? "取消置顶" : "置顶", icon: "pin", action: async () => { await patch(`/api/conversations/${c.id}`, { pinned: !c.pinned }); loadConvs(); } },
    { label: "重命名", icon: "edit", action: () => renameConv(c.id, c.title) },
    { label: "复制对话", icon: "copy", action: async () => { const n = await post(`/api/conversations/${c.id}/duplicate`); await loadConvs(); openConv(n.id); } },
    "-",
    { label: "删除", icon: "trash", danger: true, action: () => deleteConv(c) },
  ];
}
async function renameConv(id, title) {
  const v = await promptBox("重命名对话", { value: title });
  if (v === null || !v.trim()) return;
  await patch(`/api/conversations/${id}`, { title: v.trim() });
  if (S.conv?.id === id) { S.conv.title = v.trim(); $("[data-title]", S.root).textContent = v.trim(); }
  loadConvs();
}
async function deleteConv(c) {
  if (setting("chat.confirm_delete") !== false && !(await confirmBox(`确定删除对话「${esc(c.title)}」？`, { danger: true, ok: "删除" }))) return;
  const el = S.list.querySelector(`[data-id="${c.id}"]`);
  el?.classList.add("removing");
  await del(`/api/conversations/${c.id}`);
  if (S.cur === c.id) { S.cur = null; S.conv = null; localStorage.removeItem("lastConv"); renderWelcome(); }
  setTimeout(loadConvs, 200);
}
function newConv() {
  if (S.live) { S.live.close(); S.live = null; }
  S.cur = null;
  S.conv = null;
  S.streaming = false;
  localStorage.removeItem("lastConv");
  renderConvs();
  renderWelcome();
  S.ta.focus();
}
async function editSystem() {
  if (!S.conv) { toast("请先开始一个对话，或在 设置 → 对话 中设置全局系统提示词", "info"); return; }
  const presets = await get("/api/presets");
  const body = h(`<div class="col"><div class="row wrap" style="gap:6px">${presets.map((p) => `<button class="chip" data-p="${p.id}">${esc(p.name)}</button>`).join("")}</div>
    <textarea class="textarea" style="min-height:180px" placeholder="为本对话单独设置系统提示词（留空则使用全局设置）">${esc(S.conv.system_prompt || "")}</textarea></div>`);
  const foot = h(`<div style="display:contents"><button class="btn ghost" data-c>取消</button><button class="btn primary" data-o>保存</button></div>`);
  const m = (await import("../core/ui.js")).modal({ title: "本对话系统提示词", body, foot, icon: "wand", wide: true });
  $$("[data-p]", body).forEach((b) => (b.onclick = () => { $("textarea", body).value = presets.find((p) => p.id == b.dataset.p).content; }));
  $("[data-c]", foot).onclick = m.close;
  $("[data-o]", foot).onclick = async () => {
    await patch(`/api/conversations/${S.conv.id}`, { system_prompt: $("textarea", body).value });
    S.conv.system_prompt = $("textarea", body).value;
    toast("已保存", "ok");
    m.close();
  };
}
function exportConv(fmt) {
  const a = document.createElement("a");
  a.href = `/api/conversations/${S.conv.id}/export?format=${fmt}`;
  a.click();
}

// ---------------- 打开对话 ----------------
async function openConv(id) {
  if (S.live) { S.live.close(); S.live = null; }
  S.cur = id;
  localStorage.setItem("lastConv", id);
  renderConvs();
  let c;
  try { c = await get(`/api/conversations/${id}`); } catch (e) { toastErr(e); return; }
  if (S.cur !== id) return;
  S.conv = c;
  $("[data-title]", S.root).textContent = c.title;
  const tag = $(".conv-model", S.root);
  tag.classList.toggle("hidden", !c.model);
  tag.textContent = c.model || "";
  S.col.innerHTML = "";
  c.messages.forEach((m) => S.col.appendChild(msgEl(m)));
  if (!c.messages.length) renderWelcome(true);
  S.stick = true;
  scrollBottom(true);
  S.streaming = false;
  // 正在生成的对话：接回流
  if (c.run_id) attachRun(c.run_id, true);
  updSend();
  // 若对话使用的模型与当前不同，提示可一键切换
  if (c.model && c.partition_id && store.load.model !== c.model && findModel(c.partition_id, c.model) && !store.load.pending && store.load.status !== "loading") {
    toast(`此对话使用 ${c.model}，可在左下角切换`, "info", 2600);
  }
}

function renderWelcome(keepConv) {
  if (!keepConv) {
    $("[data-title]", S.root).textContent = "新对话";
    $(".conv-model", S.root).classList.add("hidden");
  }
  const hasModel = !!curModel();
  const tips = [
    ["code", "写一个网页", "用 HTML+CSS 写一个带动画的番茄钟页面"],
    ["sigma", "数学推导", "推导一元二次方程求根公式，用 LaTeX 书写"],
    ["chart", "画流程图", "用 mermaid 画出 TCP 三次握手的时序图"],
    ["sparkle", "创意写作", "以「本地大模型」为主题写一首现代诗"],
  ];
  S.col.innerHTML = "";
  const w = h(`<div class="welcome"><div class="w-logo">${icon("logo")}</div><h2>你好，今天想<em>聊点什么</em>？</h2>
    <p>${hasModel ? `当前模型：<b>${esc(store.load.model || store.load.pending?.model)}</b>` : `先点击左下角 <b>选择模型</b>，选中后会立即开始加载`}</p>
    <div class="suggests stagger">${tips.map(([ic, t, d]) => `<button class="suggest" data-q="${esc(d)}">${icon(ic)}<div><b>${t}</b><span>${d}</span></div></button>`).join("")}</div></div>`);
  $$("[data-q]", w).forEach((b) => (b.onclick = () => { S.ta.value = b.dataset.q; S.ta.dispatchEvent(new Event("input")); S.ta.focus(); }));
  S.col.appendChild(w);
}

// ---------------- 消息渲染 ----------------
function statsHtml(s) {
  if (!s || (!s.output_tokens && !s.error)) return "";
  const items = [
    ["arrowIn", "输入", fmtNum(s.input_tokens) + " tok"],
    ["arrowOut", "输出", fmtNum(s.output_tokens) + " tok"],
    ["zap", "速度", (s.tps || 0).toFixed(1) + " tok/s"],
    ["brain", "推理", s.think_ms ? fmtMs(s.think_ms) + (s.thinking_tokens ? ` · ${fmtNum(s.thinking_tokens)} tok` : "") : "—"],
    ["timer", "首 Token", fmtMs(s.ttft_ms)],
    ["clock", "总耗时", fmtMs(s.total_ms)],
  ];
  let extra = "";
  if (s.budget_hit) extra += `<span class="st warn">${icon("alert")}思考达到预算</span>`;
  if (s.done_reason === "length") extra += `<span class="st warn">${icon("alert")}达到输出上限</span>`;
  if (s.done_reason === "stop_by_user") extra += `<span class="st warn">${icon("stop")}已手动停止</span>`;
  if (s.truncated) extra += `<span class="st warn">${icon("filter")}已省略 ${s.truncated} 条历史</span>`;
  // MTP / 推测解码状态：只在探测到明确证据时显示，未探测到不显示（避免误导）
  const mtp = store.load.mtp;
  if (mtp && mtp.detected) extra += `<span class="st ok" data-tip="${esc(mtp.evidence || "")}">${icon("zap")}MTP 加速中</span>`;
  return `<div class="stats">${items.map(([ic, k, v]) => `<span class="st" data-tip="${k}">${icon(ic)}${k} <b>${v}</b></span>`).join("")}${extra}</div>`;
}

function thinkEl(text, live, ms) {
  const open = live;
  const el = h(`<div class="think ${open ? "open" : ""} ${live ? "live" : ""}"><div class="think-head">${icon("sparkle", "spark")}<span class="label">${live ? "正在思考…" : `已深度思考${ms ? "（用时 " + fmtMs(ms) + "）" : ""}`}</span>${icon("chev", "chev")}</div>
    <div class="think-body"><div><div class="md think-md"></div></div></div></div>`);
  $(".think-head", el).onclick = () => el.classList.toggle("open");
  if (text) renderInto($(".think-md", el), text);
  return el;
}

function msgEl(m) {
  if (m.role === "user") {
    const imgs = (m.images || []).map((s) => `<img src="${s}" alt="">`).join("");
    const files = (m.files || []).map((f) => `<span class="file-chip">${icon("file", "sm")}${esc(f.name)}</span>`).join("");
    const el = h(`<div class="msg user" data-id="${m.id}"><div class="avatar">${icon("message", "sm")}</div><div class="body">
      ${imgs || files ? `<div class="att">${imgs}${files}</div>` : ""}${m.content ? `<div class="bubble">${esc(m.content)}</div>` : ""}
      <div class="msg-actions"><button class="btn xs ghost icon" data-a="copy" data-tip="复制">${icon("copy", "sm")}</button><button class="btn xs ghost icon" data-a="edit" data-tip="编辑并重新发送">${icon("edit", "sm")}</button><button class="btn xs ghost icon" data-a="del" data-tip="删除">${icon("trash", "sm")}</button></div></div></div>`);
    $$(".att img", el).forEach((img) => (img.onclick = () => viewImg(img.src)));
    el.querySelector(".msg-actions").onclick = (e) => msgAction(e, m, el);
    return el;
  }
  const s = m.stats || {};
  const el = h(`<div class="msg assistant ${m.status === "error" ? "err" : ""}" data-id="${m.id}"><div class="avatar">${icon("logo", "sm")}</div><div class="body">
    <div class="meta"><b>${esc(m.model || "助手")}</b><span>${fmtRel(m.created_at)}</span>${s.think_level && s.think_level !== "off" ? `<span class="tag">${THINK_META[s.think_level]?.name || s.think_level}</span>` : ""}</div>
    <div class="think-slot"></div><div class="md msg-md"></div><div class="stats-slot"></div>
    <div class="msg-actions"><button class="btn xs ghost icon" data-a="copy" data-tip="复制">${icon("copy", "sm")}</button><button class="btn xs ghost icon" data-a="regen" data-tip="重新生成">${icon("regen", "sm")}</button><button class="btn xs ghost icon" data-a="md" data-tip="复制 Markdown 源码">${icon("code", "sm")}</button><button class="btn xs ghost icon" data-a="del" data-tip="删除">${icon("trash", "sm")}</button></div></div></div>`);
  if (m.thinking) $(".think-slot", el).appendChild(thinkEl(m.thinking, false, s.think_ms));
  // 注意：必须用 .msg-md 精确取正文容器。思考框内部也有 .md，
  // 若用 $(".md", el) 会命中文档顺序更靠前的思考框，导致正文覆盖思考内容。
  const md = $(".msg-md", el);
  if (m.status === "error") md.innerHTML = `${icon("alert", "sm")} ${esc(s.error || "生成失败")}`;
  else renderInto(md, m.content || (m.status === "stopped" ? "*（已停止，未产生内容）*" : ""));
  if (setting("chat.show_stats") !== false) $(".stats-slot", el).innerHTML = statsHtml(s);
  el.querySelector(".msg-actions").onclick = (e) => msgAction(e, m, el);
  return el;
}

async function msgAction(e, m, el) {
  const a = e.target.closest("[data-a]")?.dataset.a;
  if (!a) return;
  if (a === "copy") copyText(m.content);
  if (a === "md") copyText(m.content);
  if (a === "del") {
    await del(`/api/conversations/${S.conv.id}/messages/${m.id}`);
    S.conv.messages = S.conv.messages.filter((x) => x.id !== m.id);
    el.style.animation = "slideOut .25s var(--ease) both";
    setTimeout(() => el.remove(), 240);
  }
  if (a === "regen") {
    if (S.streaming) return toast("请等待当前输出完成", "warn");
    const last = S.conv.messages[S.conv.messages.length - 1];
    if (last?.id !== m.id) {
      if (!(await confirmBox("将删除这条回复之后的所有消息，并重新生成。", { ok: "重新生成" }))) return;
      await del(`/api/conversations/${S.conv.id}/messages/${m.id}?after=1`);
      await openConv(S.conv.id);
    } else el.remove();
    send({ regenerate: true });
  }
  if (a === "edit") {
    if (S.streaming) return toast("请等待当前输出完成", "warn");
    const body = $(".body", el);
    const box = h(`<div class="edit-box col"><textarea class="textarea" style="min-height:90px">${esc(m.content)}</textarea>
      <div class="row" style="justify-content:flex-end"><button class="btn sm ghost" data-c>取消</button><button class="btn sm primary" data-o>${icon("send", "sm")}保存并重新发送</button></div></div>`);
    const old = body.innerHTML;
    body.innerHTML = "";
    body.appendChild(box);
    $("textarea", box).focus();
    $("[data-c]", box).onclick = () => { body.innerHTML = old; el.querySelector(".msg-actions").onclick = (ev) => msgAction(ev, m, el); };
    $("[data-o]", box).onclick = async () => {
      const text = $("textarea", box).value.trim();
      if (!text) return;
      await del(`/api/conversations/${S.conv.id}/messages/${m.id}?after=1`);
      await openConv(S.conv.id);
      S.ta.value = text;
      send({ images: m.images, files: m.files });
    };
  }
}

function viewImg(src) {
  const v = h(`<div class="img-view"><img src="${src}" alt=""></div>`);
  v.onclick = () => v.remove();
  document.body.appendChild(v);
}

function scrollBottom(force) {
  if (!S.stick && !force) return;
  S.scroller.scrollTop = S.scroller.scrollHeight;
}

// ---------------- 发送与流式 ----------------
async function send(extra = {}) {
  const cm = curModel();
  if (!cm) { toast("请先在左下角选择模型", "warn"); return; }
  const content = S.ta.value.trim();
  const images = extra.images || S.attach.filter((a) => a.type === "image").map((a) => a.data);
  const files = extra.files || S.attach.filter((a) => a.type === "file").map((a) => ({ name: a.name, text: a.text, size: a.size }));
  if (!extra.regenerate && !content && !images.length && !files.length) return;
  try {
    if (!S.conv) {
      const c = await post("/api/conversations", { model: cm.name, partition_id: cm.pid });
      S.cur = c.id;
      S.conv = c;
      localStorage.setItem("lastConv", c.id);
      S.col.innerHTML = "";
    }
    const ctxS = setting("context");
    // 上下文窗口与已加载不一致时，自动以新 num_ctx 重新加载
    if (store.load.status === "loaded" && store.load.model === cm.name && store.load.num_ctx !== ctxS.num_ctx) {
      await post("/api/load", { partition_id: cm.pid, model: cm.name, num_ctx: ctxS.num_ctx });
    }
    const r = await post(`/api/conversations/${S.conv.id}/send`, {
      content, images, files, partition_id: cm.pid, model: cm.name, think: S.think, regenerate: !!extra.regenerate,
    });
    if (!extra.regenerate) {
      const um = { id: r.user_message_id, role: "user", content, images, files, created_at: Date.now() / 1000 };
      S.conv.messages.push(um);
      $(".welcome", S.col)?.remove();
      S.col.appendChild(msgEl(um));
    }
    S.ta.value = "";
    S.ta.style.height = "auto";
    S.attach = [];
    renderAttach();
    S.stick = true;
    attachRun(r.run_id);
    loadConvs();
  } catch (e) { toastErr(e); }
}

function attachRun(runId, resumed) {
  S.streaming = true;
  updSend();
  const modelName = curModel()?.name || S.conv?.model || "";
  const el = h(`<div class="msg assistant streaming"><div class="avatar">${icon("logo", "sm")}</div><div class="body">
    <div class="meta"><b>${esc(modelName)}</b><span>正在生成</span>${S.think !== "off" ? `<span class="tag acc">${THINK_META[S.think]?.name}</span>` : ""}</div>
    <div class="stage-line"><span class="typing"><i></i><i></i><i></i></span><span class="stage-text">${resumed ? "正在接回输出…" : "准备中…"}</span></div>
    <div class="think-slot"></div><div class="md msg-md"></div><div class="notice-slot"></div><div class="stats-slot"></div></div></div>`);
  S.col.appendChild(el);
  scrollBottom(true);
  const md = $(".msg-md", el);
  const stage = $(".stage-line", el);
  let content = "", thinking = "", thinkBox = null, thinkStart = 0;
  const convId = S.conv.id;
  const flush = () => {
    S.renderTimer = null;
    if (S.cur !== convId) return;
    if (thinkBox) renderInto($(".think-md", thinkBox), thinking, { streaming: true });
    if (content) { renderInto(md, content, { streaming: true }); md.classList.add("cursor"); }
    if (thinkBox) { const tm = $(".think-md", thinkBox); tm.scrollTop = tm.scrollHeight; }
    scrollBottom();
  };
  const sched = () => { if (!S.renderTimer) S.renderTimer = setTimeout(flush, 50); };
  S.live = streamRun(runId, {
    status: (d) => { $(".stage-text", el).textContent = d.text; },
    thinking: (d) => {
      if (!thinkBox) {
        stage.classList.add("hidden");
        thinkStart = performance.now();
        thinkBox = thinkEl("", true);
        $(".think-slot", el).appendChild(thinkBox);
      }
      thinking += d.t;
      sched();
    },
    content: (d) => {
      if (!content) {
        stage.classList.add("hidden");
        if (thinkBox) {
          thinkBox.classList.remove("live", "open");
          $(".label", thinkBox).textContent = `已深度思考（用时 ${fmtMs(performance.now() - thinkStart)}）`;
        }
      }
      content += d.t;
      sched();
    },
    notice: (d) => { $(".notice-slot", el).appendChild(h(`<div class="notice-line">${icon("info", "sm")}${esc(d.text)}</div>`)); },
    done: (d) => {
      S.live = null;
      clearTimeout(S.renderTimer);
      S.renderTimer = null;
      if (S.cur !== convId) { S.streaming = false; updSend(); loadConvs(); return; }
      const msg = { id: d.message_id, role: "assistant", content, thinking, model: d.stats.model, stats: d.stats, status: d.status, created_at: Date.now() / 1000 };
      S.conv.messages.push(msg);
      const final = msgEl(msg);
      const notices = $(".notice-slot", el).innerHTML;
      el.replaceWith(final);
      if (notices) $(".stats-slot", final).insertAdjacentHTML("beforebegin", `<div>${notices}</div>`);
      S.streaming = false;
      updSend();
      scrollBottom();
      if (d.status === "error") toast(d.error || "生成失败", "err", 6000);
      loadConvs();
      if (S.conv && S.conv.title === "新对话") get(`/api/conversations/${convId}`).then((c) => { if (S.cur === convId) { S.conv.title = c.title; $("[data-title]", S.root).textContent = c.title; } });
    },
    failed: (d) => {
      S.live = null;
      clearTimeout(S.renderTimer);
      S.renderTimer = null;
      if (S.cur !== convId) { S.streaming = false; updSend(); loadConvs(); return; }
      // 保留已生成的内容，把流式气泡收尾为一条错误提示（沿用 msgEl 的错误样式 + notice-line）
      el.classList.remove("streaming");
      el.classList.add("err");
      stage.remove();
      if (thinkBox) {
        thinkBox.classList.remove("live", "open");
        $(".label", thinkBox).textContent = `已深度思考（用时 ${fmtMs(performance.now() - thinkStart)}）`;
      }
      if (content) renderInto(md, content);
      md.classList.remove("cursor");
      $(".notice-slot", el).appendChild(h(`<div class="notice-line">${icon("alert", "sm")}${esc(d.error)}</div>`));
      S.streaming = false;
      updSend();
      scrollBottom();
      toast(d.error, "err", 6000);
      loadConvs();
    },
  });
}

async function stop() {
  if (!S.conv) return;
  try { await post(`/api/conversations/${S.conv.id}/stop`); } catch (e) { toastErr(e); }
}
