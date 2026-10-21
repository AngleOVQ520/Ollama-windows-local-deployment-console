// 添加模型：分区管理 + 从 Ollama 下载 + 导入本地 GGUF + 任务队列
import { del, get, on, patch, post } from "../core/api.js";
import { icon } from "../core/icons.js";
import { refreshGroups } from "../core/store.js";
import { $, $$, confirmBox, debounce, esc, fmtBytes, fmtCtx, fmtMs, fmtNum, h, menu, modal, toast, toastErr } from "../core/ui.js";
import { pickPath } from "./filebrowser.js";

const S = { parts: [], sel: null, src: "ollama", jobs: [], gguf: null, cats: [] };
const COLORS = ["#10b981", "#2dd4bf", "#f4715e", "#84cc16", "#f43f5e", "#fb923c", "#22d3ee", "#a3a3a3"];

export function mount(root) {
  root.innerHTML = `<div class="page"><div class="page-inner">
    <div class="page-head"><div><h1>添加模型</h1><p>按分区管理模型：每个分区可放在任意磁盘的任意文件夹，分区之间互不影响。</p></div>
      <div class="actions"><button class="btn" data-newpart>${icon("folder")}新建分区</button></div></div>
    <div class="add-grid"><div class="col"><div class="label" style="margin-bottom:2px">${icon("hdd", "sm")}分区</div><div class="part-list"></div></div>
      <div class="col" style="gap:18px"><div class="source-tabs">
        <button class="src-tab" data-src="ollama"><span class="si">${icon("download", "lg")}</span><div><b>从 Ollama 下载</b><span>输入模型 ID，自动拉取到当前分区</span></div></button>
        <button class="src-tab" data-src="gguf"><span class="si">${icon("upload", "lg")}</span><div><b>导入 GGUF 文件</b><span>同盘硬链接秒级导入，不占额外空间</span></div></button></div>
        <div class="card src-panel"></div>
        <div class="card"><div class="card-title">${icon("download")}任务<span class="grow"></span><button class="btn xs ghost" data-clearjobs>${icon("trash", "sm")}清除已完成</button></div><div class="job-list"></div></div>
      </div></div></div></div>`;
  $("[data-newpart]", root).onclick = () => editPartition();
  $$("[data-src]", root).forEach((b) => (b.onclick = () => { S.src = b.dataset.src; renderSrc(root); }));
  $("[data-clearjobs]", root).onclick = async () => { await del("/api/jobs"); loadJobs(root); };
  S.root = root;
  loadParts(root);
  loadJobs(root);
  get("/api/models/categories").then((c) => (S.cats = c));
  on("job", (j) => upsertJob(root, j));
  on("models_changed", debounce(() => loadParts(root), 400));
  on("engines", debounce(() => loadParts(root), 600));
}

export function onShow() { if (S.root) { loadParts(S.root); loadJobs(S.root); } }

async function loadParts(root) {
  S.parts = await get("/api/partitions");
  if (!S.sel || !S.parts.find((p) => p.id === S.sel)) S.sel = (S.parts.find((p) => p.is_default) || S.parts[0])?.id;
  const list = $(".part-list", root);
  list.innerHTML = "";
  for (const p of S.parts) {
    const used = p.disk_total ? (1 - p.disk_free / p.disk_total) * 100 : 0;
    const es = p.engine?.status || "stopped";
    const card = h(`<div class="part-card ${p.id === S.sel ? "on" : ""}" style="--pc:${esc(p.color || "#10b981")}">
      <div class="pc-h"><span class="sw"></span><span class="ellipsis">${esc(p.name)}</span>${p.is_default ? '<span class="tag">默认</span>' : ""}</div>
      <div class="pc-path">${esc(p.path)}</div>
      <div class="pc-stats"><span>${icon("box", "sm")} ${p.model_count} 个模型</span><span>${fmtBytes(p.total_size)}</span>
        <span class="row" style="gap:5px"><i class="dot ${es === "running" ? "ok" : es === "starting" ? "warn" : es === "error" ? "err" : ""}"></i>${{ running: "引擎运行", starting: "启动中", error: "引擎错误", stopped: "引擎休眠" }[es] || es}</span></div>
      ${p.exists ? `<div class="pc-disk"><div class="bar" style="height:4px" data-tip="磁盘已用 ${used.toFixed(0)}%，剩余 ${fmtBytes(p.disk_free)}"><i style="width:${used}%"></i></div></div>` : `<div class="hint" style="color:var(--err)">${icon("alert", "sm")} 文件夹不存在</div>`}
      <div class="pc-act"><button class="btn xs ghost icon" data-m>${icon("more", "sm")}</button></div></div>`);
    card.onclick = (e) => { if (e.target.closest("[data-m]")) return; S.sel = p.id; loadParts(root); };
    $("[data-m]", card).onclick = (e) => menu(e.currentTarget, [
      { label: "编辑分区", icon: "edit", action: () => editPartition(p) },
      { label: "在资源管理器中打开", icon: "folder", action: () => post("/api/fs/open", { path: p.path }).catch(toastErr) },
      { label: "重新扫描模型", icon: "refresh", action: async () => { const r = await post(`/api/partitions/${p.id}/sync?deep=1`); toast(`扫描完成，更新 ${r.updated} 项`, "ok"); refreshGroups(); loadParts(root); } },
      { label: es === "running" ? "停止引擎" : "启动引擎", icon: "power", action: async () => { await post(`/api/partitions/${p.id}/engine/${es === "running" ? "stop" : "start"}`).catch(toastErr); loadParts(root); } },
      { label: "查看引擎日志", icon: "terminal", action: () => engineLog(p) },
      "-",
      { label: "删除分区", icon: "trash", danger: true, hidden: S.parts.length <= 1, action: () => deletePartition(p) },
    ]);
    list.appendChild(card);
  }
  list.appendChild(Object.assign(h(`<div class="part-card part-add">${icon("plus")}新建分区</div>`), { onclick: () => editPartition() }));
  renderSrc(root);
}

async function engineLog(p) {
  const text = await get(`/api/logs/engine/${p.id}`);
  const m = modal({ title: `引擎日志 · ${p.name}`, body: `<pre class="raw" style="max-height:60vh">${esc(text.slice(-30000) || "（暂无日志）")}</pre>`, wide: true, foot: false, icon: "terminal" });
  const pre = $("pre", m.body);
  pre.scrollTop = pre.scrollHeight;
}

function editPartition(p) {
  const isNew = !p;
  let color = p?.color || COLORS[S.parts.length % COLORS.length];
  const body = h(`<div class="col" style="gap:14px">
    <div class="field"><label>分区名称</label><input class="input" data-name value="${esc(p?.name || "")}" placeholder="例如：D 盘大模型、实验区…"></div>
    <div class="field"><label>存放文件夹</label><div class="input-group"><input class="input mono" data-path value="${esc(p?.path || "")}" placeholder="例如：D:\\AI\\models"><button class="btn" data-pick>${icon("folder", "sm")}浏览</button></div>
      <div class="hint">该分区下载/导入的模型都会保存在这个文件夹（Ollama 标准结构：blobs + manifests）。可以指向已有的 Ollama 模型目录直接复用。</div></div>
    <div class="field"><label>颜色</label><div class="accent-pick">${COLORS.map((c) => `<button style="background:${c}" data-c="${c}" class="${c === color ? "on" : ""}"></button>`).join("")}</div></div>
    ${!isNew ? `<div class="hint" style="color:var(--warn)">${icon("info", "sm")} 修改路径会重启该分区引擎，并从新路径重新扫描模型（不会移动旧文件）。</div>` : ""}</div>`);
  const foot = h(`<div style="display:contents"><button class="btn ghost" data-x2>取消</button><button class="btn primary" data-ok>${isNew ? "创建分区" : "保存"}</button></div>`);
  const m = modal({ title: isNew ? "新建分区" : "编辑分区", body, foot, icon: "hdd" });
  $$("[data-c]", body).forEach((b) => (b.onclick = () => { color = b.dataset.c; $$("[data-c]", body).forEach((x) => x.classList.toggle("on", x === b)); }));
  $("[data-pick]", body).onclick = async () => { const r = await pickPath({ mode: "dir", start: $("[data-path]", body).value }); if (r) $("[data-path]", body).value = r; };
  $("[data-x2]", foot).onclick = m.close;
  $("[data-ok]", foot).onclick = async (e) => {
    const btn = e.currentTarget;
    btn.classList.add("loading");
    try {
      const data = { name: $("[data-name]", body).value.trim(), path: $("[data-path]", body).value.trim(), color };
      const r = isNew ? await post("/api/partitions", data) : await patch(`/api/partitions/${p.id}`, data);
      S.sel = r.id;
      toast(isNew ? "分区已创建" : "分区已更新", "ok");
      m.close();
      loadParts(S.root);
      refreshGroups();
    } catch (err) { toastErr(err); } finally { btn.classList.remove("loading"); }
  };
  setTimeout(() => $("[data-name]", body).focus(), 60);
}

async function deletePartition(p) {
  const r = await confirmBox(`删除分区「${esc(p.name)}」？分区记录将被移除。`, {
    danger: true, ok: "删除分区",
    extra: `<label class="row" style="margin-top:14px;font-size:13px"><input type="checkbox" data-extra> 同时删除该分区中的所有模型文件（不可恢复）</label>`,
  });
  if (!r) return;
  try {
    await del(`/api/partitions/${p.id}${r.checked ? "?files=1" : ""}`);
    toast("分区已删除", "ok");
    loadParts(S.root);
    refreshGroups();
  } catch (e) { toastErr(e); }
}

// ---------------- 来源面板 ----------------
function renderSrc(root) {
  $$("[data-src]", root).forEach((b) => b.classList.toggle("on", b.dataset.src === S.src));
  const panel = $(".src-panel", root);
  const p = S.parts.find((x) => x.id === S.sel);
  if (!p) { panel.innerHTML = `<div class="empty">${icon("hdd")}<div>请先创建一个分区</div></div>`; return; }
  const target = `<div class="row" style="margin-bottom:14px;font-size:12.5px"><span class="dim">目标分区</span><span class="tag" style="border-color:${esc(p.color)}55;color:${esc(p.color)}">${esc(p.name)}</span><span class="mono dim ellipsis">${esc(p.path)}</span></div>`;
  if (panel.dataset.src === S.src && panel.dataset.pid == p.id) { $(".tgt", panel).innerHTML = target; return; }
  panel.dataset.src = S.src;
  panel.dataset.pid = p.id;
  if (S.src === "ollama") renderPull(panel, p, target);
  else renderGguf(panel, p, target);
}

function renderPull(panel, p, target) {
  panel.innerHTML = `<div class="card-title">${icon("download")}从 Ollama 下载</div><div class="tgt">${target}</div>
    <div class="pull-box"><div class="grow" style="position:relative">${icon("box", "pb-ico")}<input class="input" data-model placeholder="模型 ID，例如 qwen3.5:2b、deepseek-r1:7b、gemma3:4b"></div><button class="btn primary" data-pull>${icon("download")}开始下载</button></div>
    <div class="field" style="margin-top:12px"><input class="input sm" data-remark placeholder="备注名称（可选，显示在模型列表）"></div>
    <div class="cmd-preview"><span class="p">$</span><span data-cmd>ollama run &lt;模型ID&gt;</span><span class="dim" style="margin-left:auto">→ 保存到 ${esc(p.path)}</span></div>
    <div class="row" style="margin-top:18px"><div class="label">${icon("sparkle", "sm")}模型库</div><div class="grow"></div><div class="sb-search" style="width:260px">${icon("search")}<input class="input sm" data-q placeholder="搜索 ollama.com 模型库…" style="padding-left:32px"></div></div>
    <div class="lib-grid"></div>`;
  const inp = $("[data-model]", panel);
  const upd = () => { $("[data-cmd]", panel).textContent = `ollama run ${inp.value.trim().replace(/^ollama\s+(run|pull)\s+/, "") || "<模型ID>"}`; };
  inp.oninput = upd;
  inp.onkeydown = (e) => { if (e.key === "Enter") startPull(); };
  const startPull = async () => {
    const model = inp.value.trim();
    if (!model) { inp.focus(); return; }
    try {
      await post("/api/jobs/pull", { partition_id: p.id, model, remark: $("[data-remark]", panel).value.trim() });
      toast(`已开始下载 ${model}`, "ok");
      inp.value = "";
      $("[data-remark]", panel).value = "";
      upd();
      loadJobs(S.root);
    } catch (e) { toastErr(e); }
  };
  $("[data-pull]", panel).onclick = startPull;
  const grid = $(".lib-grid", panel);
  const search = async (q) => {
    grid.innerHTML = Array.from({ length: 6 }, () => '<div class="skeleton" style="height:96px;border-radius:14px"></div>').join("");
    try {
      const r = await get("/api/library/search?q=" + encodeURIComponent(q));
      grid.innerHTML = "";
      grid.classList.add("stagger");
      for (const it of r.items) {
        const c = h(`<div class="lib-card"><div class="row"><b>${esc(it.name)}</b>${it.pulls ? `<span class="dim" style="margin-left:auto;font-size:11px">${esc(it.pulls)}</span>` : ""}</div><p>${esc(it.desc || "")}</p>
          <div class="tags">${(it.tags || []).slice(0, 8).map((t) => `<span class="tag" data-t="${esc(t)}">${esc(t)}</span>`).join("")}</div></div>`);
        c.onclick = (e) => {
          const t = e.target.closest("[data-t]")?.dataset.t;
          inp.value = t ? `${it.name}:${t}` : it.name;
          upd();
          inp.focus();
          if (!t) loadTags(it.name, c);
        };
        grid.appendChild(c);
      }
      if (!r.items.length) grid.innerHTML = `<div class="empty">${icon("search")}<div>没有找到</div></div>`;
    } catch (e) { grid.innerHTML = `<div class="hint">${esc(e.message)}</div>`; }
  };
  const loadTags = async (name, card) => {
    try {
      const tags = await get("/api/library/tags?name=" + encodeURIComponent(name));
      $(".tags", card).innerHTML = tags.slice(0, 24).map((t) => `<span class="tag" data-t="${esc(t.tag)}" data-tip="${esc(t.size || "")}">${esc(t.tag)}</span>`).join("");
    } catch { /* 忽略 */ }
  };
  $("[data-q]", panel).oninput = debounce((e) => search(e.target.value.trim()), 400);
  search("");
}

function renderGguf(panel, p, target) {
  panel.innerHTML = `<div class="card-title">${icon("upload")}导入本地 GGUF</div><div class="tgt">${target}</div>
    <div class="drop-zone">${icon("upload")}<div style="font-weight:650;margin-bottom:4px">把 .gguf 拖到这里，或选择文件</div>
      <div class="hint">工具会直接解析 GGUF 元数据（架构、参数量、量化、最大上下文、MTP 头等）</div>
      <div class="row" style="justify-content:center;margin-top:14px"><button class="btn primary" data-pickf>${icon("file")}浏览文件</button><button class="btn" data-scan>${icon("folder")}扫描文件夹</button></div>
      <div class="input-group" style="margin-top:12px;max-width:620px;margin-left:auto;margin-right:auto"><input class="input sm mono" data-gpath placeholder="或直接粘贴完整路径，例如 D:\\models\\xxx.gguf"><button class="btn sm" data-insp>解析</button></div>
      <div class="up-state hidden"></div></div>
    <div class="gg-detail"></div><div class="gg-scan"></div>`;
  $("[data-pickf]", panel).onclick = async () => { const f = await pickPath({ mode: "file", start: S.lastDir || "" }); if (f) { S.lastDir = f.replace(/[\\/][^\\/]+$/, ""); inspect(panel, p, f); } };
  $("[data-insp]", panel).onclick = () => inspect(panel, p, $("[data-gpath]", panel).value.trim());
  $("[data-gpath]", panel).onkeydown = (e) => { if (e.key === "Enter") inspect(panel, p, e.target.value.trim()); };
  // ---- 拖入 GGUF 自动识别（浏览器不暴露本地绝对路径，先上传到项目临时目录再解析）----
  const zone = $(".drop-zone", panel);
  let dragDepth = 0;
  zone.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; zone.classList.add("over"); });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; });
  zone.addEventListener("dragleave", (e) => { e.preventDefault(); if (--dragDepth <= 0) { dragDepth = 0; zone.classList.remove("over"); } });
  zone.addEventListener("drop", (e) => {
    e.preventDefault(); e.stopPropagation();
    dragDepth = 0; zone.classList.remove("over");
    const f = e.dataTransfer?.files?.[0];
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".gguf")) { toast("只支持 .gguf 文件", "warn"); return; }
    uploadGguf(panel, p, f);
  });
  $("[data-scan]", panel).onclick = async () => {
    const d = await pickPath({ mode: "dir", title: "选择要扫描的文件夹", start: S.lastDir || "" });
    if (!d) return;
    const box = $(".gg-scan", panel);
    box.innerHTML = '<div class="skeleton" style="height:60px;margin-top:14px"></div>';
    try {
      const files = await post("/api/fs/scan", { path: d });
      box.innerHTML = files.length ? `<div class="label" style="margin:16px 0 8px">找到 ${files.length} 个 GGUF 文件</div>` : `<div class="hint" style="margin-top:14px">该文件夹下没有 GGUF 文件</div>`;
      for (const f of files) {
        const r = h(`<div class="fb-item file" style="border:1px solid var(--line);border-radius:10px;margin-bottom:6px">${icon("file")}<span class="ellipsis mono" style="font-size:12.5px">${esc(f.path)}</span><span class="sz">${fmtBytes(f.size)}</span><button class="btn xs primary" style="margin-left:10px">解析</button></div>`);
        r.onclick = () => inspect(panel, p, f.path);
        box.appendChild(r);
      }
    } catch (e) { box.innerHTML = ""; toastErr(e); }
  };
}

async function inspect(panel, p, path, preInfo) {
  if (!path && !preInfo) return;
  const box = $(".gg-detail", panel);
  box.innerHTML = '<div class="skeleton" style="height:180px;margin-top:16px;border-radius:14px"></div>';
  let s = preInfo;
  if (!s) {
    try { s = await post("/api/gguf/inspect", { path }); } catch (e) { box.innerHTML = ""; toastErr(e); return; }
  }
  showGgufInfo(panel, p, s, box);
}

// 拖拽上传：把文件传到项目临时目录 → 解析元数据 → 自动填充表单
function uploadGguf(panel, p, file) {
  const state = $(".up-state", panel);
  state.classList.remove("hidden");
  state.innerHTML = `<div class="up-card"><div class="row"><b class="ellipsis">${esc(file.name)}</b><span class="dim">${fmtBytes(file.size)}</span></div>
    <div class="bar" style="margin-top:8px"><i style="width:0%"></i></div><div class="up-txt hint" style="margin-top:5px">正在上传到项目临时目录…</div></div>`;
  const bar = $(".bar i", state), txt = $(".up-txt", state);
  const xhr = new XMLHttpRequest();
  const fd = new FormData();
  fd.append("file", file);
  xhr.open("POST", "/api/gguf/upload");
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = e.loaded / e.total * 100;
    bar.style.width = pct.toFixed(1) + "%";
    txt.textContent = `上传中 ${pct.toFixed(1)}% · ${fmtBytes(e.loaded)} / ${fmtBytes(e.total)}`;
  };
  xhr.onload = () => {
    let d = null;
    try { d = JSON.parse(xhr.responseText); } catch { /* ignore */ }
    if (!d || !d.ok) {
      state.classList.add("hidden");
      toast(d?.error || "上传失败", "err", 5000);
      return;
    }
    bar.style.width = "100%";
    txt.textContent = "上传完成，已解析元数据（导入后临时文件会自动删除）";
    showGgufInfo(panel, p, d.data, $(".gg-detail", panel));
    toast("已识别 " + file.name, "ok");
    setTimeout(() => state.classList.add("hidden"), 1500);
  };
  xhr.onerror = () => { state.classList.add("hidden"); toast("上传失败（网络错误）", "err"); };
  xhr.send(fd);
}

function showGgufInfo(panel, p, s, box) {
  S.gguf = s;
  const kv = [
    ["架构", s.architecture], ["模型名", s.name || "—"], ["参数量", s.params_label || "—"], ["量化", s.file_type || "—"],
    ["最大上下文", s.context_length ? `${s.context_length.toLocaleString("en-US")} (${fmtCtx(s.context_length)})` : "—"], ["文件大小", fmtBytes(s.file_size)],
    ["层数", s.block_count ?? "—"], ["隐藏维度", s.embedding_length ?? "—"], ["注意力头", s.head_count ?? "—"], ["专家数", s.expert_count ?? "—"],
    ["对话模板", s.has_chat_template ? "内置 ✓" : "无"], ["GGUF 版本", "v" + s.gguf_version],
  ];
  const mtpBadge = s.has_mtp
    ? `<div class="hint" style="color:var(--ok);margin-top:10px">${icon("zap", "sm")} 检测到 <b>MTP / NextN 推测解码头</b>：${s.mtp_tensor_count} 个 mtp 张量${s.mtp_layers ? `（${s.mtp_layers} 层）` : ""}。能否实际加速取决于推理引擎是否启用。</div>`
    : "";
  box.innerHTML = `<div class="fade-up" style="margin-top:18px">${s.exists ? `<div class="hint" style="color:var(--warn);margin-bottom:8px">${icon("info", "sm")} 该文件已导入过，再次导入将创建新的模型名</div>` : ""}
    <div class="label" style="word-break:break-all">${icon("file", "sm")}${esc(s.original_name || s.path)}${s.original_name ? ' <span class="dim">（已上传到项目临时目录，导入后自动删除）</span>' : ""}</div>
    <div class="gguf-info stagger">${kv.map(([k, v]) => `<div class="kv"><div class="k">${k}</div><div class="v">${esc(v)}</div></div>`).join("")}</div>
    ${mtpBadge}
    <div class="form-grid">
      <div class="field"><label>模型名称（Ollama 中的 ID）</label><input class="input mono" data-n value="${esc(s.suggest_name)}"></div>
      <div class="field"><label>备注名称</label><input class="input" data-r placeholder="可选" value="${esc(s.name || "")}"></div>
      <div class="field"><label>类别</label><select class="select" data-cat>${S.cats.map((c) => `<option ${c === s.category ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></div>
      <div class="field"><label>导入方式</label><select class="select" data-mode><option value="auto">自动（同盘硬链接，否则复制）</option><option value="link">仅硬链接（零拷贝）</option><option value="copy">复制到分区</option></select></div>
      <details class="full"><summary class="label" style="cursor:pointer">高级：默认参数 / 系统提示词</summary>
        <div class="form-grid" style="margin-top:10px"><div class="field"><label>默认温度</label><input class="input" data-temp type="number" step="0.05" placeholder="使用模型默认"></div>
        <div class="field"><label>默认上下文 num_ctx</label><input class="input" data-ctx type="number" step="512" placeholder="使用全局设置"></div>
        <div class="field full"><label>系统提示词 SYSTEM</label><textarea class="textarea" data-sys placeholder="可选"></textarea></div></div></details>
    </div>
    <div class="row" style="margin-top:16px;justify-content:flex-end"><button class="btn primary" data-go>${icon("upload")}导入到「${esc(p.name)}」</button></div></div>`;
  $("[data-go]", box).onclick = async (e) => {
    const btn = e.currentTarget;
    btn.classList.add("loading");
    const options = {};
    const t = $("[data-temp]", box).value, c = $("[data-ctx]", box).value, sy = $("[data-sys]", box).value.trim();
    if (t) options.temperature = +t;
    if (c) options.num_ctx = +c;
    if (sy) options.system = sy;
    try {
      await post("/api/jobs/import", { partition_id: p.id, path: s.path, name: $("[data-n]", box).value.trim(), remark: $("[data-r]", box).value.trim(),
        category: $("[data-cat]", box).value, mode: $("[data-mode]", box).value, options });
      toast("已开始导入", "ok");
      box.innerHTML = "";
      loadJobs(S.root);
    } catch (err) { toastErr(err); } finally { btn.classList.remove("loading"); }
  };
}

// ---------------- 任务 ----------------
async function loadJobs(root) {
  S.jobs = await get("/api/jobs");
  const list = $(".job-list", root);
  list.innerHTML = "";
  if (!S.jobs.length) list.innerHTML = `<div class="empty" style="padding:26px">${icon("download")}<div>暂无任务</div></div>`;
  for (const j of S.jobs) list.appendChild(jobEl(j));
}
function jobEl(j) {
  const part = S.parts.find((p) => p.id === j.partition_id);
  const el = h(`<div class="job ${j.status}" data-j="${j.id}"><div class="jh"><span class="ji">${icon(j.status === "done" ? "check" : j.status === "error" ? "alert" : j.kind === "pull" ? "download" : "upload")}</span>
    <div class="grow"><b>${esc(j.target)}</b><div class="dim" style="font-size:12px">${j.kind === "pull" ? "Ollama 下载" : "GGUF 导入"} → ${esc(part?.name || "")}</div></div>
    <span class="tag ${j.status === "done" ? "ok" : j.status === "error" ? "err" : j.status === "cancelled" ? "" : "acc"}" data-st>${esc(j.stage)}</span>
    ${j.status === "running" || j.status === "queued" ? `<button class="btn xs danger" data-cancel>取消</button>` : ""}
    ${j.status === "done" ? `<a class="btn xs" href="#/chat" data-use>${icon("chat", "sm")}去对话</a>` : ""}
    ${j.status === "error" || j.status === "cancelled" ? `<button class="btn xs" data-retry>${icon("regen", "sm")}重试</button>` : ""}</div>
    ${j.status === "running" || j.status === "queued" ? `<div class="bar striped"><i style="width:${j.percent}%"></i></div>` : ""}
    <div class="jm"><span data-pct>${j.percent.toFixed(1)}%</span>${j.total ? `<span data-sz>${fmtBytes(j.completed)} / ${fmtBytes(j.total)}</span>` : ""}${j.speed ? `<span data-sp>${fmtBytes(j.speed)}/s</span>` : ""}${j.eta ? `<span data-eta>剩余 ${fmtMs(j.eta * 1000)}</span>` : ""}${j.message && j.status !== "error" ? `<span>${esc(j.message)}</span>` : ""}</div>
    ${j.status === "error" ? `<div class="jmsg">${esc(j.message)}</div>` : ""}</div>`);
  $("[data-cancel]", el)?.addEventListener("click", () => post(`/api/jobs/${j.id}/cancel`).catch(toastErr));
  $("[data-retry]", el)?.addEventListener("click", () => {
    (j.kind === "pull" ? post("/api/jobs/pull", { partition_id: j.partition_id, model: j.target }) : Promise.reject(new Error("请重新选择文件导入"))).then(() => loadJobs(S.root)).catch(toastErr);
  });
  $("[data-use]", el)?.addEventListener("click", () => post("/api/load", { partition_id: j.partition_id, model: j.target }).catch(() => {}));
  return el;
}
function upsertJob(root, j) {
  const list = $(".job-list", root);
  if (!list) return;
  const old = list.querySelector(`[data-j="${j.id}"]`);
  // 运行中只更新数值，避免整块重绘
  if (old && old.classList.contains(j.status) && j.status === "running") {
    const bar = $(".bar i", old);
    if (bar) bar.style.width = j.percent + "%";
    $("[data-st]", old).textContent = j.stage;
    $(".jm", old).innerHTML = `<span>${j.percent.toFixed(1)}%</span>${j.total ? `<span>${fmtBytes(j.completed)} / ${fmtBytes(j.total)}</span>` : ""}${j.speed ? `<span>${fmtBytes(j.speed)}/s</span>` : ""}${j.eta ? `<span>剩余 ${fmtMs(j.eta * 1000)}</span>` : ""}`;
    return;
  }
  const el = jobEl(j);
  if (old) old.replaceWith(el);
  else { $(".empty", list)?.remove(); list.prepend(el); }
  if (j.status === "done") { toast(`${j.target} ${j.kind === "pull" ? "下载" : "导入"}完成`, "ok"); refreshGroups(); loadParts(root); }
  if (j.status === "error") toast(`${j.target}：${j.message}`, "err", 6000);
}
