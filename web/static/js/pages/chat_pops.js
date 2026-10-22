// 首页输入框的四个悬浮窗：模型切换、上下文控制、模型参数、深度思考
import { on, patch, post } from "../core/api.js";
import { icon } from "../core/icons.js";
import { findModel, refreshGroups, saveSettings, setting, store, clampNum, ctxLimit } from "../core/store.js";
import { $, $$, esc, fmtBytes, fmtCtx, fmtParams, h, popover, rangeFill, toast, toastErr } from "../core/ui.js";

export const THINK_META = {
  off: { name: "关闭", desc: "直接回答，最快" },
  mini: { name: "Mini", desc: "极简思考" },
  low: { name: "Low", desc: "轻度思考" },
  medium: { name: "Medium", desc: "均衡" },
  high: { name: "High", desc: "深入推理" },
  "x-high": { name: "X-High", desc: "更深入" },
  max: { name: "Max", desc: "大量推理" },
  ultra: { name: "Ultra", desc: "不设上限" },
};

const CAP_ICON = { vision: ["vision", "视觉"], tools: ["tool", "工具调用"], thinking: ["brain", "思考"], embedding: ["layers", "向量"] };

function initials(name) {
  const base = name.split("/").pop().split(":")[0];
  return base.replace(/[^a-zA-Z0-9]/g, "").slice(0, 2).toUpperCase() || "AI";
}

// ---------------- 模型切换 ----------------
export function openModelPicker(anchor, onPick) {
  const box = h(`<div class="mp"><div class="mp-search">${icon("search")}<input class="input" placeholder="搜索模型 / 分区 / 类别…"></div><div class="mp-list"></div>
    <div class="row" style="margin-top:8px;padding:6px 4px 0;border-top:1px solid var(--line)"><a href="#/add" class="btn xs ghost">${icon("plus", "sm")}添加模型</a><a href="#/models" class="btn xs ghost">${icon("list", "sm")}模型列表</a>
    <div class="grow"></div><button class="btn xs ghost" data-unload>${icon("power", "sm")}卸载当前</button></div></div>`);
  const list = $(".mp-list", box);
  const inp = $("input", box);
  const cur = store.load;
  const draw = () => {
    const q = inp.value.trim().toLowerCase();
    list.innerHTML = "";
    let total = 0;
    for (const g of store.groups) {
      const items = g.models.filter((m) => !q || [m.name, m.remark, g.name, m.display_category].join(" ").toLowerCase().includes(q));
      if (!items.length) continue;
      total += items.length;
      const sec = h(`<div class="mp-part"><div class="mp-part-h"><span class="sw" style="background:${esc(g.color || "var(--acc)")}"></span>${esc(g.name)}<span class="dim" style="margin-left:auto;font-weight:500">${items.length}</span></div></div>`);
      for (const m of items) {
        const on = cur.partition_id === g.id && cur.model === m.name;
        const caps = (m.capabilities || []).filter((c) => CAP_ICON[c]).map((c) => `<span data-tip="${CAP_ICON[c][1]}">${icon(CAP_ICON[c][0])}</span>`).join("");
        const it = h(`<div class="mp-item ${on ? "on" : ""} ${m.has_mtp ? "mtp" : ""}" tabindex="0">
          <div class="mi-ico">${esc(initials(m.name))}</div>
          <div class="mi-main"><div class="mi-name">${esc(m.remark || m.name)}${m.has_mtp ? `<span class="mp-mtp" data-tip="该模型 GGUF 内含 MTP/NextN 推测解码头，可在「参数」中开关加速">MTP</span>` : ""}</div>
          <div class="mi-sub">${m.remark ? `<span class="mono">${esc(m.name)}</span>` : `<span>${esc(m.display_category)}</span>`}<span>${esc(fmtParams(m.params, m.params_label))}</span><span>${fmtBytes(m.size)}</span>${m.context_length ? `<span>${fmtCtx(m.context_length)}</span>` : ""}${m.has_mtp ? `<span class="mp-mtp-sub">MTP ${m.mtp_tensor_count || 0} 张量${m.mtp_layers ? ` · ${m.mtp_layers} 层` : ""}</span>` : ""}</div></div>
          <div class="mi-caps">${caps}</div>${on ? `<span class="tag ${cur.status === "loaded" ? "ok" : "warn"}">${cur.status === "loaded" ? "已加载" : "加载中"}</span>` : ""}</div>`);
        const pick = () => { p.close(); onPick(g.id, m.name); };
        it.onclick = pick;
        it.onkeydown = (e) => { if (e.key === "Enter") pick(); };
        sec.appendChild(it);
      }
      list.appendChild(sec);
    }
    if (!total) list.innerHTML = `<div class="empty" style="padding:28px">${icon("box")}<div>${q ? "没有匹配的模型" : "还没有模型"}</div><a class="btn sm primary" href="#/add">${icon("plus", "sm")}去添加</a></div>`;
  };
  inp.oninput = draw;
  $("[data-unload]", box).onclick = () => { p.close(); post("/api/unload").catch(toastErr); };
  draw();
  const p = popover(anchor, box, { place: "top", align: "start" });
  setTimeout(() => inp.focus(), 60);
  return p;
}

// ---------------- 通用：带滑块的数字行 ----------------
function numRow({ label, tip, min, max, step, value, onChange, fmt }) {
  const row = h(`<div class="pp-row"><label ${tip ? `data-tip="${esc(tip)}"` : ""}>${esc(label)}${tip ? icon("info", "sm") : ""}</label>
    <input class="input" type="number" min="${min}" max="${max}" step="${step}" value="${value}"><input class="range" type="range" min="${min}" max="${max}" step="${step}" value="${value}"></div>`);
  const [num, rng] = [$("input[type=number]", row), $("input[type=range]", row)];
  const upd = rangeFill(rng);
  // 手动输入同样钳制到 [min, max]，越界时回写输入框并提示，避免非法值进入引擎
  const clamp = (raw, notify) => {
    let v = +raw;
    if (isNaN(v)) v = +rng.min;
    const c = clampNum(v, +rng.min, +rng.max);
    if (notify && c !== v && String(raw).trim() !== "") toast(`${label} 已限制在 ${fmt ? fmt(c) : `${min} ~ ${max}`}`, "warn");
    return c;
  };
  rng.oninput = () => { num.value = rng.value; upd(); onChange(+rng.value); };
  num.onchange = () => {
    const v = clamp(num.value, true);
    num.value = v;
    rng.value = v;
    upd();
    onChange(v);
  };
  // 范围随模型/设置动态变化时同步更新上下限（不传 step 则保留原步进）
  row.setRange = (lo, hi) => {
    for (const el of [num, rng]) { el.min = lo; el.max = hi; }
    upd();
  };
  row.setValue = (v) => { num.value = v; rng.value = v; upd(); };
  return row;
}

// ---------------- 上下文控制 ----------------
export function openContextPop(anchor, onChange) {
  const c = setting("context");
  const ld = store.load;
  const m = ld.model ? findModel(ld.partition_id, ld.model) : null;
  const modelMax = m?.context_length || 0;
  // 上限取模型声明的上下文（不超过 1M）；模型未知时才回退到 128K
  // 声明为 let：浮窗打开期间切换模型时 syncRange 会更新上限
  let maxCtx = ctxLimit(ld.partition_id, ld.model);
  const box = h(`<div class="pp"><div class="pop-title">${icon("layers")}上下文控制<span class="tag" style="margin-left:auto">${modelMax ? "模型上限 " + fmtCtx(modelMax) : "未知上限"}</span></div></div>`);
  const presets = h(`<div class="row wrap" style="gap:5px;margin-bottom:12px"></div>`);
  // 预设档位与输入框同一上限：不足 128K 的模型不能给出超过声明值的档位
  [2048, 4096, 8192, 16384, 32768, 65536, 131072].filter((v) => v <= maxCtx).forEach((v) => {
    const b = h(`<button class="chip">${fmtCtx(v)}</button>`);
    b.onclick = () => { ctxRow.setValue(v); set({ num_ctx: v }); };
    presets.appendChild(b);
  });
  const set = (patch) => {
    saveSettings({ context: patch });
    onChange?.();
    // c 是浮窗打开时的快照，需同步本地，后续比较才准确
    Object.assign(c, patch);
    // 钳制逻辑在 append 之前就会调用 set()，此时提示元素还不存在，需判空
    const warnEl = $(".warn-ctx", box);
    if (patch.num_ctx && warnEl) warnEl.classList.toggle("hidden", !(ld.status === "loaded" && ld.num_ctx !== c.num_ctx));
  };
  const ctxRow = numRow({ label: "上下文窗口 num_ctx", tip: "模型一次能看到的总 token 数（输入 + 输出），越大越占显存", min: 512, max: maxCtx, step: 512, value: c.num_ctx, onChange: (v) => set({ num_ctx: v }), fmt: fmtCtx });
  const inRow = numRow({ label: "最大输入 tokens", tip: "发送前按此限制裁剪较早的历史消息，0 表示不限制", min: 0, max: maxCtx, step: 256, value: c.max_input, onChange: (v) => set({ max_input: v }) });
  const outRow = numRow({ label: "最大输出 tokens", tip: "num_predict：单次回复的最大长度（包含思考），0 表示不限制", min: 0, max: 65536, step: 128, value: c.max_output, onChange: (v) => set({ max_output: v }) });
  const histRow = numRow({ label: "保留历史轮数", tip: "只携带最近 N 轮对话，0 表示全部", min: 0, max: 100, step: 1, value: c.history_turns, onChange: (v) => set({ history_turns: v }) });
  // 已保存的值可能超过当前模型上限（例如换到 4K 模型）：显示时即钳制并同步，避免滑块/输入框越界
  const ctxV = clampNum(c.num_ctx, 512, maxCtx);
  if (ctxV !== c.num_ctx) {
    ctxRow.setValue(ctxV);
    set({ num_ctx: ctxV });
    toast(`当前模型上限为 ${fmtCtx(maxCtx)}，上下文窗口已限制为 ${fmtCtx(ctxV)}`, "warn", 4000);
  }
  const inV = clampNum(c.max_input, 0, maxCtx);
  if (inV !== c.max_input) { inRow.setValue(inV); set({ max_input: inV }); }
  // 浮窗打开期间切换了模型：同步缩小上限，并把超出的值钳制掉
  const syncRange = () => {
    const lim = ctxLimit(store.load.partition_id, store.load.model);
    if (lim === maxCtx) return;
    maxCtx = lim;
    for (const [row, lo] of [[ctxRow, 512], [inRow, 0]]) {
      row.setRange(lo, maxCtx);
      const v = clampNum(row.querySelector("input[type=number]").value, lo, maxCtx);
      if (String(v) !== row.querySelector("input[type=number]").value) {
        row.setValue(v);
        const key = row === ctxRow ? "num_ctx" : "max_input";
        set({ [key]: v });
        toast(`模型上限为 ${fmtCtx(maxCtx)}，已限制为 ${fmtCtx(v)}`, "warn", 4000);
      }
    }
  };
  const unsub = on("load", () => syncRange());
  box.append(presets, ctxRow, inRow, outRow, histRow,
    h(`<div class="hint warn-ctx ${ld.status === "loaded" && ld.num_ctx !== c.num_ctx ? "" : "hidden"}" style="color:var(--warn)">${icon("info", "sm")} 上下文窗口变更将在下次发送时自动重新加载模型</div>`),
    h(`<div class="hint">当前已加载：${ld.status === "loaded" ? fmtCtx(ld.num_ctx) + " tokens" : "—"}</div>`));
  const p = popover(anchor, box, { place: "top", align: "end", onClose: () => unsub() });
  return p;
}

// ---------------- 模型参数 ----------------
const PARAM_DEF = [
  ["采样", [
    ["temperature", "Temperature 温度", 0, 2, 0.05, "越高越随机、越有创意；越低越确定"],
    ["top_p", "Top P", 0, 1, 0.01, "核采样：只在累计概率前 P 的词中采样"],
    ["top_k", "Top K", 0, 200, 1, "只在概率最高的 K 个词中采样，0 = 不限"],
    ["min_p", "Min P", 0, 1, 0.01, "过滤概率低于 (最高概率 × min_p) 的词"],
    ["typical_p", "Typical P", 0, 1, 0.01, "局部典型性采样，1 = 关闭"],
  ]],
  ["惩罚", [
    ["repeat_penalty", "重复惩罚", 0.5, 2, 0.01, "抑制重复内容，1 = 不惩罚"],
    ["repeat_last_n", "重复检测窗口", -1, 512, 1, "回看多少 token 判断重复，-1 = 整个上下文"],
    ["presence_penalty", "存在惩罚", -2, 2, 0.05, "出现过的词降低概率，鼓励新话题"],
    ["frequency_penalty", "频率惩罚", -2, 2, 0.05, "按出现次数降低概率"],
  ]],
  ["Mirostat", [
    ["mirostat", "Mirostat 模式", 0, 2, 1, "0 关闭 / 1 Mirostat / 2 Mirostat 2.0"],
    ["mirostat_tau", "Mirostat τ", 0, 10, 0.1, "目标困惑度，越低越聚焦"],
    ["mirostat_eta", "Mirostat η", 0, 1, 0.01, "学习率"],
  ]],
  ["性能", [
    ["num_thread", "CPU 线程数", 0, 64, 1, "0 = 自动"],
    ["num_batch", "批大小 num_batch", 32, 4096, 32, "提示词处理批大小"],
    ["num_gpu", "GPU 层数", -1, 200, 1, "-1 = 自动；0 = 纯 CPU（修改后重新加载生效）"],
  ]],
];
const PARAM_PRESETS = {
  "精确": { temperature: 0.2, top_p: 0.8, top_k: 20, repeat_penalty: 1.05 },
  "均衡": { temperature: 0.7, top_p: 0.9, top_k: 40, repeat_penalty: 1.1 },
  "创意": { temperature: 1.1, top_p: 0.95, top_k: 80, repeat_penalty: 1.05 },
  "代码": { temperature: 0.1, top_p: 0.9, top_k: 30, repeat_penalty: 1.0 },
};
// 各参数合法范围（由 PARAM_DEF 派生，供预设按钮钳制用）
const PARAM_RANGE = Object.fromEntries(PARAM_DEF.flatMap(([, defs]) => defs.map(([k, , min, max]) => [k, [min, max]])));

export function openParamsPop(anchor, onChange) {
  const p = setting("params");
  const box = h(`<div class="pp" style="width:400px"><div class="pop-title">${icon("sliders")}模型参数<button class="btn xs ghost" data-reset>${icon("refresh", "sm")}恢复默认</button></div></div>`);
  const pre = h(`<div class="row wrap" style="gap:5px;margin-bottom:6px"></div>`);
  const rows = {};
  for (const [name, vals] of Object.entries(PARAM_PRESETS)) {
    const b = h(`<button class="chip">${name}</button>`);
    b.onclick = () => {
      // 预设值同样按各行范围钳制，避免与手动输入的取值范围不一致
      const out = {};
      for (const [k, v] of Object.entries(vals)) {
        const def = PARAM_RANGE[k];
        out[k] = def ? clampNum(v, def[0], def[1]) : v;
        rows[k]?.setValue(out[k]);
      }
      saveSettings({ params: out });
      onChange?.();
    };
    pre.appendChild(b);
  }
  const useDef = h(`<label class="row" style="justify-content:space-between;margin:6px 0 4px;font-size:12.5px"><span class="muted">使用模型自带默认参数（忽略下方采样设置）</span><span class="switch"><input type="checkbox" ${p.use_model_defaults ? "checked" : ""}><span></span></span></label>`);
  $("input", useDef).onchange = (e) => { saveSettings({ params: { use_model_defaults: e.target.checked } }); onChange?.(); };
  box.append(pre, useDef);
  // ---- MTP 加速（仅对当前加载的、带 MTP 头的模型显示）----
  const ld = store.load;
  const curModel = ld.model ? findModel(ld.partition_id, ld.model) : null;
  if (curModel && curModel.has_mtp) {
    const enabled = curModel.mtp_enabled !== 0;
    const mtpBox = h(`<div class="pp-mtp">
      <div class="row" style="justify-content:space-between;gap:12px;align-items:flex-start">
        <div class="grow"><div class="pp-mtp-t">${icon("zap", "sm")}MTP 推测解码加速</div>
          <div class="hint">该模型内含 ${curModel.mtp_tensor_count || 0} 个 MTP 张量${curModel.mtp_layers ? ` · ${curModel.mtp_layers} 层` : ""}。开启后引擎以 draft-mtp 模式生成；关闭则按普通模式。切换会重新加载模型。</div></div>
        <label class="switch"><input type="checkbox" ${enabled ? "checked" : ""}><span></span></label>
      </div></div>`);
    $("input", mtpBox).onchange = async (e) => {
      const on = e.target.checked;
      e.target.disabled = true;
      try {
        await patch(`/api/models/${curModel.id}`, { mtp_enabled: on });
        toast(on ? "已开启 MTP，正在重新加载模型…" : "已关闭 MTP，正在重新加载模型…", "ok", 4000);
        await refreshGroups();
      } catch (err) {
        toastErr(err);
        e.target.checked = !on;
      }
      e.target.disabled = false;
    };
    box.appendChild(mtpBox);
  }
  for (const [sec, defs] of PARAM_DEF) {
    box.appendChild(h(`<div class="pp-sec">${sec}</div>`));
    for (const [k, label, min, max, step, tip] of defs) {
      rows[k] = numRow({ label, tip, min, max, step, value: p[k] ?? 0, onChange: (v) => { saveSettings({ params: { [k]: v } }); onChange?.(); } });
      box.appendChild(rows[k]);
    }
  }
  box.appendChild(h(`<div class="pp-sec">其他</div>`));
  const seedRow = h(`<div class="pp-row"><label data-tip="固定种子可复现输出，-1 为随机">随机种子 seed ${icon("info", "sm")}</label><input class="input" type="number" value="${p.seed}"></div>`);
  $("input", seedRow).onchange = (e) => {
    // 种子：留空或非法时视为随机（-1），负数同样归为 -1
    const raw = e.target.value.trim();
    const seed = raw === "" || !Number.isFinite(+raw) ? -1 : Math.max(-1, Math.trunc(+raw));
    e.target.value = seed;
    saveSettings({ params: { seed } });
    onChange?.();
  };
  const stopRow = h(`<div class="field" style="margin-bottom:6px"><label class="label">停止词（逗号分隔）</label><input class="input sm" value="${esc((p.stop || []).join(","))}" placeholder="例如：<|end|>,###"></div>`);
  $("input", stopRow).onchange = (e) => { saveSettings({ params: { stop: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } }); onChange?.(); };
  box.append(seedRow, stopRow);
  $("[data-reset]", box).onclick = () => {
    const d = store.defaults.params;
    saveSettings({ params: d });
    for (const [k, r] of Object.entries(rows)) r.setValue(d[k]);
    $("input", seedRow).value = d.seed;
    $("input", stopRow).value = "";
    $("input", useDef).checked = false;
    onChange?.();
  };
  return popover(anchor, box, { place: "top", align: "end" });
}

// ---------------- 深度思考 ----------------
export function openThinkPop(anchor, value, onPick) {
  const budgets = setting("thinking.budgets") || {};
  const ld = store.load;
  const m = ld.model ? findModel(ld.partition_id, ld.model) : null;
  const supports = !m || (m.capabilities || []).includes("thinking");
  const levels = store.thinkLevels;
  const box = h(`<div class="tk"><div class="pop-title">${icon("brain")}深度思考强度</div>
    ${supports ? "" : `<div class="hint" style="color:var(--warn);margin-bottom:8px">${icon("alert", "sm")} 当前模型不支持思考模式，设置将被忽略</div>`}<div class="tk-list"></div>
    <div class="hint" style="margin-top:10px">预算 = 最多思考的 token 数，达到后自动收尾并输出答案。可在 设置 → 思考 中调整。</div></div>`);
  const list = $(".tk-list", box);
  levels.forEach((lv, i) => {
    const meta = THINK_META[lv];
    const bars = Array.from({ length: 7 }, (_, j) => `<i class="${j < i ? "f" : ""}" style="height:${4 + j * 2}px"></i>`).join("");
    const b = budgets[lv];
    const it = h(`<div class="tk-item ${lv === value ? "on" : ""}"><span class="lv">${bars}</span><b>${meta.name}</b><span>${meta.desc}</span>
      <span class="bud">${lv === "off" ? "" : lv === "ultra" || !b ? "∞" : b >= 1000 ? b / 1024 + "K" : b}</span></div>`);
    it.onclick = () => { p.close(); onPick(lv); };
    list.appendChild(it);
  });
  const p = popover(anchor, box, { place: "top", align: "end" });
  return p;
}
