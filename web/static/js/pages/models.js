// 模型列表：备注名 / 模型ID / 类别 / 添加时间 / 参数量 / 大小 / 最大上下文
import { del, get, on, patch, post } from "../core/api.js";
import { icon } from "../core/icons.js";
import { refreshGroups, store } from "../core/store.js";
import { $, $$, confirmBox, copyText, debounce, esc, fmtBytes, fmtCtx, fmtNum, fmtParams, fmtTime, h, menu, modal, promptBox, toast, toastErr } from "../core/ui.js";

const S = { models: [], parts: [], cats: [], part: 0, cat: "", q: "", sort: "added_at", desc: true, running: [], sig: "", ldSig: "", loadSig: "", ldTimer: null };
const CAP = { vision: ["vision", "视觉"], tools: ["tool", "工具"], thinking: ["brain", "思考"], embedding: ["layers", "向量"], completion: null };
const COLS = [
  ["remark", "备注名称"], ["name", "模型 ID"], ["display_category", "类别"], ["added_at", "添加时间"],
  ["params", "参数量", "num"], ["size", "模型大小", "num"], ["context_length", "最大上下文", "num"],
];
export function mount(root) {
  root.innerHTML = `<div class="page"><div class="page-inner">
    <div class="page-head"><div><h1>模型列表</h1><p>所有分区中的模型。点击备注即可编辑；类别可手动修改。</p></div>
      <div class="actions"><button class="btn" data-refresh>${icon("refresh")}重新扫描</button><a class="btn primary" href="#/add">${icon("plus")}添加模型</a></div></div>
    <div class="ml-toolbar"><div class="sb-search">${icon("search")}<input class="input" placeholder="搜索名称、备注、类别…"></div><div class="chips" data-parts></div></div>
    <div class="chips" data-cats style="margin-bottom:14px"></div>
    <div class="table-wrap"><table class="dt"><thead><tr></tr></thead><tbody></tbody></table></div>
    <div class="ml-sum"></div></div></div>`;
  S.root = root;
  const tr = $("thead tr", root);
  for (const [k, label, cls] of COLS) {
    const th = h(`<th class="sortable ${cls || ""}" data-k="${k}">${label}${icon("chev", "sort-ico")}</th>`);
    th.onclick = () => { if (S.sort === k) S.desc = !S.desc; else { S.sort = k; S.desc = k !== "remark" && k !== "name"; } render(); };
    tr.appendChild(th);
  }
  tr.appendChild(h(`<th>能力</th>`));
  tr.appendChild(h(`<th data-tip="模型 GGUF 内含 MTP/NextN 推测解码头（多 Token 预测）。能否实际加速取决于推理引擎是否启用">MTP</th>`));
  tr.appendChild(h(`<th>分区</th>`));
  tr.appendChild(h(`<th style="text-align:right">操作</th>`));
  $(".sb-search input", root).oninput = debounce((e) => { S.q = e.target.value.trim().toLowerCase(); render(); }, 150);
  $("[data-refresh]", root).onclick = async (e) => {
    e.currentTarget.classList.add("loading");
    try { const r = await post("/api/models/refresh?deep=1"); toast(`扫描完成，更新 ${r.updated} 项`, "ok"); await load(); } catch (err) { toastErr(err); }
    e.currentTarget.classList.remove("loading");
  };
  load();
  on("models_changed", debounce(load, 300));
  // 加载事件每秒约 6~7 次（纯进度更新占多数）：只有「加载状态 / 模型 / 分区」变化时才重建表格，
  // 否则会整表重建导致闪烁、滚动跳动、正在编辑的备注输入框被销毁
  on("load", (st) => {
    if (!S.root) return;
    const sig = `${st.partition_id}|${st.model}|${st.status}|${st.pending?.model || ""}`;
    if (sig === S.loadSig) return;
    S.loadSig = sig;
    clearTimeout(S.ldTimer);
    S.ldTimer = setTimeout(() => load(), 500);
  });
}
export function onShow() { if (S.root) load(); }

async function load() {
  [S.models, S.parts, S.cats] = await Promise.all([get("/api/models"), get("/api/partitions"), get("/api/models/categories")]);
  // 数据与加载状态都没变时不重建表格（切换导航更快）
  const sig = JSON.stringify(S.models.map((m) => [m.id, m.remark, m.display_category, m.favorite, m.size, m.context_length, m.partition_id]));
  const ldSig = `${store.load.partition_id}|${store.load.model}|${store.load.status}`;
  if (sig === S.sig && ldSig === S.ldSig && $("tbody", S.root)?.children.length) return;
  S.sig = sig;
  S.ldSig = ldSig;
  render();
}

function filtered() {
  return S.models.filter((m) => (!S.part || m.partition_id === S.part) && (!S.cat || m.display_category === S.cat)
    && (!S.q || [m.remark, m.name, m.display_category, m.family, m.quant, m.partition_name].join(" ").toLowerCase().includes(S.q)));
}

function render() {
  const root = S.root;
  if (!root) return;
  const pc = $("[data-parts]", root);
  pc.innerHTML = "";
  const mk = (id, label, n, color) => {
    const c = h(`<button class="chip ${S.part === id ? "on" : ""}">${color ? `<span class="sw" style="background:${esc(color)}"></span>` : ""}${esc(label)}<span class="n">${n}</span></button>`);
    c.onclick = () => { S.part = id; render(); };
    pc.appendChild(c);
  };
  mk(0, "全部分区", S.models.length);
  S.parts.forEach((p) => mk(p.id, p.name, S.models.filter((m) => m.partition_id === p.id).length, p.color));
  const cc = $("[data-cats]", root);
  cc.innerHTML = "";
  const cats = [...new Set(S.models.filter((m) => !S.part || m.partition_id === S.part).map((m) => m.display_category))];
  if (cats.length > 1) {
    const all = h(`<button class="chip ${!S.cat ? "on" : ""}">全部类别</button>`);
    all.onclick = () => { S.cat = ""; render(); };
    cc.appendChild(all);
    for (const c of cats) {
      const b = h(`<button class="chip ${S.cat === c ? "on" : ""}">${esc(c)}<span class="n">${S.models.filter((m) => m.display_category === c && (!S.part || m.partition_id === S.part)).length}</span></button>`);
      b.onclick = () => { S.cat = c; render(); };
      cc.appendChild(b);
    }
  }
  $$("th[data-k]", root).forEach((th) => { th.classList.toggle("sorted", th.dataset.k === S.sort); th.classList.toggle("desc", th.dataset.k === S.sort && S.desc); });
  const rows = filtered().sort((a, b) => {
    let x = a[S.sort], y = b[S.sort];
    if (S.sort === "remark") { x = a.remark || a.name; y = b.remark || b.name; }
    if (x == null) return 1;
    if (y == null) return -1;
    const r = typeof x === "string" ? x.localeCompare(y, "zh") : x - y;
    return S.desc ? -r : r;
  });
  const tb = $("tbody", root);
  tb.innerHTML = "";
  const ld = store.load;
  if (!rows.length) {
    tb.innerHTML = `<tr><td colspan="11"><div class="empty">${icon("box")}<div>${S.models.length ? "没有匹配的模型" : "还没有模型"}</div>${S.models.length ? "" : `<a class="btn primary sm" href="#/add">${icon("plus", "sm")}添加第一个模型</a>`}</div></td></tr>`;
  }
  rows.forEach((m, i) => {
    const isLoaded = ld.partition_id === m.partition_id && ld.model === m.name;
    const caps = (m.capabilities || []).filter((c) => CAP[c]).map((c) => `<span data-tip="${CAP[c][1]}">${icon(CAP[c][0])}</span>`).join("");
    const mtpTag = m.has_mtp
      ? `<span class="tag ok" data-tip="GGUF 内含 MTP/NextN 推测解码头（${m.mtp_tensor_count || "?"} 个张量${m.mtp_layers ? ` · ${m.mtp_layers} 层` : ""}），能否加速取决于引擎">MTP ✓</span>`
      : `<span class="dim" data-tip="该模型 GGUF 中没有 MTP/NextN 结构">—</span>`;
    const tr = h(`<tr class="${isLoaded ? "loaded" : ""}" style="animation-delay:${Math.min(i, 20) * 18}ms">
      <td><span class="remark ${m.remark ? "" : "empty"}" data-remark>${esc(m.remark || "添加备注")}</span>${m.favorite ? ` ${icon("star", "sm")}` : ""}</td>
      <td class="mid">${esc(m.name)}${isLoaded ? ` <span class="tag ${ld.status === "loaded" ? "ok" : "warn"}" style="margin-left:6px">${ld.status === "loaded" ? "已加载" : "加载中"}</span>` : ""}</td>
      <td><span class="tag acc" data-cat style="cursor:pointer" data-tip="点击修改类别">${esc(m.display_category)}</span></td>
      <td class="tnum dim" data-tip="${fmtTime(m.added_at)}">${fmtTime(m.added_at)}</td>
      <td class="num" data-tip="${m.params ? fmtNum(m.params) + " 个参数" : ""}">${esc(fmtParams(m.params, m.params_label))}</td>
      <td class="num">${(m.size / 1073741824).toFixed(2)} G</td>
      <td class="num">${m.context_length ? `<span class="ctx-pill" data-tip="${fmtNum(m.context_length)} tokens">${fmtCtx(m.context_length)}</span>` : ""}</td>
      <td><span class="cap-ico">${caps}</span></td>
      <td>${mtpTag}</td>
      <td><span class="tag" style="border-color:${esc(m.partition_color)}55">${esc(m.partition_name)}</span></td>
      <td><div class="row-act"><button class="btn xs ${isLoaded ? "" : "primary"}" data-load>${icon(isLoaded ? "chat" : "play", "sm")}${isLoaded ? "对话" : "加载"}</button>${isLoaded ? `<button class="btn xs" data-unload data-tip="卸载模型并释放显存">${icon("power", "sm")}卸载</button>` : ""}<button class="btn xs ghost icon" data-info data-tip="详情">${icon("info", "sm")}</button><button class="btn xs ghost icon" data-m>${icon("more", "sm")}</button></div></td></tr>`);
    $("[data-remark]", tr).onclick = () => inlineEdit($("[data-remark]", tr), m);
    $("[data-cat]", tr).onclick = (e) => pickCat(e.currentTarget, m);
    $("[data-unload]", tr)?.addEventListener("click", async (e) => {
      e.currentTarget.classList.add("loading");
      try { await post("/api/unload"); toast(`已卸载 ${m.name}`, "ok"); } catch (err) { toastErr(err); } finally { e.currentTarget.classList.remove("loading"); }
    });
    $("[data-load]", tr).onclick = async () => {
      try { if (!isLoaded) await post("/api/load", { partition_id: m.partition_id, model: m.name }); location.hash = "#/chat"; } catch (e) { toastErr(e); }
    };
    $("[data-info]", tr).onclick = () => detail(m.id);
    $("[data-m]", tr).onclick = (e) => menu(e.currentTarget, [
      { label: "加载并对话", icon: "chat", action: () => $("[data-load]", tr).click() },
      isLoaded ? { label: "卸载（释放显存）", icon: "power", action: () => post("/api/unload").then(() => { toast("已卸载", "ok"); load(); refreshGroups(); }).catch(toastErr) } : null,
      { label: m.favorite ? "取消收藏" : "收藏", icon: "star", action: () => patch(`/api/models/${m.id}`, { favorite: !m.favorite }).then(load) },
      { label: "编辑备注", icon: "edit", action: () => inlineEdit($("[data-remark]", tr), m) },
      { label: "复制模型 ID", icon: "copy", action: () => copyText(m.name) },
      { label: "复制为新模型", icon: "layers", action: () => copyModel(m) },
      { label: "查看详情 / 元数据", icon: "info", action: () => detail(m.id) },
      { label: "打开所在文件夹", icon: "folder", action: () => post("/api/fs/open", { path: S.parts.find((p) => p.id === m.partition_id)?.path }).catch(toastErr) },
      "-",
      { label: "删除模型", icon: "trash", danger: true, action: () => removeModel(m) },
    ]);
    tb.appendChild(tr);
  });
  const total = rows.reduce((a, m) => a + (m.size || 0), 0);
  $(".ml-sum", root).innerHTML = `<span>共 <b>${rows.length}</b> 个模型</span><span>总大小 <b>${fmtBytes(total)}</b></span><span>分区 <b>${S.parts.length}</b></span>`;
}

function inlineEdit(span, m) {
  const inp = h(`<input class="input sm" style="width:180px" value="${esc(m.remark || "")}" placeholder="备注名称">`);
  span.replaceWith(inp);
  inp.focus();
  let done = false;
  const save = async () => {
    if (done) return;
    done = true;
    try { await patch(`/api/models/${m.id}`, { remark: inp.value.trim() }); m.remark = inp.value.trim(); refreshGroups(); } catch (e) { toastErr(e); }
    render();
  };
  inp.onblur = save;
  inp.onkeydown = (e) => { if (e.key === "Enter") inp.blur(); if (e.key === "Escape") { done = true; render(); } };
}

function pickCat(anchor, m) {
  menu(anchor, [
    { label: `自动识别（${m.category_auto || "其他"}）`, icon: "sparkle", action: () => setCat(m, "") },
    "-",
    ...S.cats.map((c) => ({ label: c, icon: c === m.display_category ? "check" : "hash", action: () => setCat(m, c) })),
    "-",
    { label: "自定义类别…", icon: "edit", action: async () => { const v = await promptBox("自定义类别", { value: m.category }); if (v !== null) setCat(m, v.trim()); } },
  ], { align: "start" });
}
async function setCat(m, c) {
  await patch(`/api/models/${m.id}`, { category: c });
  load();
}

async function copyModel(m) {
  const n = await promptBox("复制为新模型", { value: m.name.replace(/:/, "-copy:"), hint: "在同一分区中创建一个共享权重文件的新模型名（不占额外空间）" });
  if (!n) return;
  try { await post(`/api/models/${m.id}/copy`, { name: n }); toast("已复制", "ok"); load(); } catch (e) { toastErr(e); }
}

async function removeModel(m) {
  if (!(await confirmBox(`确定删除模型 <b>${esc(m.name)}</b>？<br><span class="dim">将从分区「${esc(m.partition_name)}」中移除，未被其他模型共享的文件会被删除。${m.source === "gguf" ? "<br>导入的原始 GGUF 文件不会被删除。" : ""}</span>`, { danger: true, ok: "删除" }))) return;
  try { await del(`/api/models/${m.id}`); toast("已删除", "ok"); load(); refreshGroups(); } catch (e) { toastErr(e); }
}

async function detail(id) {
  const m = await get(`/api/models/${id}`);
  const meta = m.meta || {};
  const mi = meta.model_info || {};
  const mtp = meta.mtp || {};
  const nameLooksMtp = /(^|[-_.:])mtp([-_.:]|$)/i.test(m.name);
  const mtpVal = (m.has_mtp || mtp.tensors)
    ? `内含 ${mtp.tensors || "?"} 个 MTP 张量${mtp.layers ? ` · ${mtp.layers} 层` : ""}${mtp.native_keys?.length ? " · 引擎上报键 " + mtp.native_keys.join(",") : ""}`
    : (nameLooksMtp
        ? "未检测到 —— 文件名虽含 MTP，但 GGUF 内没有 nextn/mtp 张量与 nextn_predict_layers 声明，引擎无法启用（模型列表的“—”是准确的）"
        : "无");
  const body = h(`<div><div class="gguf-info">${[
    ["模型 ID", m.name], ["备注", m.remark || "—"], ["类别", m.display_category], ["架构", m.arch || "—"], ["参数量", fmtParams(m.params, m.params_label) + (m.params ? `（${fmtNum(m.params)}）` : "")],
    ["量化", m.quant || "—"], ["大小", fmtBytes(m.size)], ["最大上下文", m.context_length ? fmtNum(m.context_length) : "—"], ["来源", { ollama: "Ollama 下载", gguf: "GGUF 导入", existing: "已存在" }[m.source] || m.source],
    ["分区", m.partition_name], ["添加时间", fmtTime(m.added_at)], ["能力", (m.capabilities || []).join(" / ") || "—"],
    ["MTP 推测解码头", mtpVal],
  ].map(([k, v]) => `<div class="kv"><div class="k">${k}</div><div class="v" style="font-size:13px">${esc(v)}</div></div>`).join("")}</div>
    <div class="detail-tabs"><button class="on" data-t="meta">元数据</button><button data-t="params">默认参数</button><button data-t="tpl">模板</button><button data-t="lic">许可证</button><button data-t="notes">笔记</button></div><div class="dt-body"></div></div>`);
  const tb = $(".dt-body", body);
  const show = (t) => {
    $$(".detail-tabs button", body).forEach((b) => b.classList.toggle("on", b.dataset.t === t));
    if (t === "meta") tb.innerHTML = `<div style="max-height:46vh;overflow:auto"><table class="meta-table">${Object.entries(mi).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</td></tr>`).join("") || "<tr><td>无</td></tr>"}</table></div>
      ${m.source_path ? `<div class="hint" style="margin-top:10px">源文件：<span class="mono">${esc(m.source_path)}</span></div>` : ""}${m.blob_path ? `<div class="hint">权重文件：<span class="mono">${esc(m.blob_path)}</span></div>` : ""}`;
    if (t === "params") tb.innerHTML = `<pre class="raw">${esc(meta.parameters || "（无）")}</pre>`;
    if (t === "tpl") tb.innerHTML = `<pre class="raw">${esc(meta.template || "（无）")}</pre>`;
    if (t === "lic") tb.innerHTML = `<pre class="raw">${esc(meta.license || "（无）")}</pre>`;
    if (t === "notes") {
      tb.innerHTML = `<textarea class="textarea" style="min-height:200px" placeholder="记录这个模型的使用心得、适用场景…">${esc(m.notes || "")}</textarea><div class="row" style="justify-content:flex-end;margin-top:8px"><button class="btn sm primary">保存笔记</button></div>`;
      $("button", tb).onclick = async () => { await patch(`/api/models/${m.id}`, { notes: $("textarea", tb).value }); toast("已保存", "ok"); };
    }
  };
  $$(".detail-tabs button", body).forEach((b) => (b.onclick = () => show(b.dataset.t)));
  show("meta");
  modal({ title: m.remark || m.name, body, wide: true, foot: false, icon: "box" });
}
