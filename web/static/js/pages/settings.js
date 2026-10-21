// 设置页：外观 / 对话 / 思考 / 默认参数 / 上下文 / 引擎 / API / 预设 / 数据 / 日志 / 快捷键 / 关于
import { del, get, on, post, put } from "../core/api.js";
import { icon } from "../core/icons.js";
import { saveSettings, setting, store } from "../core/store.js";
import { $, $$, confirmBox, copyText, download, esc, fmtBytes, fmtMs, fmtTime, h, modal, seg, toast, toastErr } from "../core/ui.js";
import { THINK_META } from "./chat_pops.js";
import { pickPath } from "./filebrowser.js";

const SECTIONS = [
  ["ui", "palette", "外观"], ["chat", "chat", "对话"], ["think", "brain", "深度思考"], ["params", "sliders", "默认参数"], ["context", "layers", "上下文"],
  ["engine", "cpu", "Ollama 引擎"], ["image", "palette", "生图"], ["api", "globe", "API 服务"], ["server", "monitor", "界面服务"], ["presets", "wand", "提示词预设"],
  ["data", "db", "数据与备份"], ["logs", "terminal", "运行日志"], ["keys", "keyboard", "快捷键"], ["about", "info", "关于"],
];
const ACCENTS = [["emerald", "#10b981", "翡翠"], ["teal", "#14b8a6", "青碧"], ["coral", "#f4715e", "珊瑚"], ["lime", "#84cc16", "青柠"], ["rose", "#f43f5e", "玫红"], ["graphite", "#a1a1aa", "石墨"]];

let root, savePill, saveTimer;
const S = { lastSig: "" };

export function mount(r) {
  root = r;
  root.innerHTML = `<div class="page" data-scroll><div class="page-inner">
    <div class="page-head"><div><h1>设置</h1><p>所有设置自动保存到 data/settings.json。</p></div>
      <div class="actions"><button class="btn" data-export>${icon("download")}导出设置</button><button class="btn" data-import>${icon("upload")}导入设置</button><button class="btn ghost danger" data-resetall>${icon("refresh")}全部恢复默认</button></div></div>
    <div class="set-grid"><nav class="set-nav">${SECTIONS.map(([id, ic, name]) => `<a href="javascript:;" data-go="${id}">${icon(ic)}${name}</a>`).join("")}</nav><div class="set-body"></div></div></div></div>`;
  savePill = h(`<div class="save-pill">${icon("check")}已保存</div>`);
  document.body.appendChild(savePill);
  $$("[data-go]", root).forEach((a) => (a.onclick = () => $(`#set-${a.dataset.go}`, root)?.scrollIntoView({ behavior: "smooth", block: "start" })));
  $("[data-export]", root).onclick = () => { location.href = "/api/settings/export"; };
  $("[data-import]", root).onclick = importSettings;
  $("[data-resetall]", root).onclick = async () => {
    if (!(await confirmBox("将所有设置恢复为默认值（不影响对话、模型与统计数据）。", { danger: true, ok: "恢复默认" }))) return;
    store.settings = await post("/api/settings/reset", {});
    (await import("../core/store.js")).applyUi();
    render();
    toast("已恢复默认设置", "ok");
  };
  const scroller = $("[data-scroll]", root);
  scroller.addEventListener("scroll", () => {
    let curId = SECTIONS[0][0];
    for (const [id] of SECTIONS) { const el = $(`#set-${id}`, root); if (el && el.offsetTop - scroller.scrollTop < 140) curId = id; }
    $$("[data-go]", root).forEach((a) => a.classList.toggle("on", a.dataset.go === curId));
  });
  on("settings_saved", (r) => {
    // 只有停留在设置页时才提示，避免在首页改思考档位之类时跨页弹出浮标
    if (!root.closest(".view.on")) return;
    savePill.classList.add("show");
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => savePill.classList.remove("show"), 1400);
    if (r.restart_required) toast("界面端口/地址已修改，重启 app.py 后生效", "warn", 6000);
  });
  render();
}
export function onShow() {
  if (!root) return;
  // 设置未变化时不重建 DOM（避免每次切换导航重排十几个区块）
  const sig = JSON.stringify(store.settings);
  if (sig === S.lastSig && $(".set-body", root)?.children.length) return;
  render();
}

// ---------- 行构造器 ----------
function row(title, desc, control) {
  const r = h(`<div class="set-row"><div class="sr-l"><b>${title}</b>${desc ? `<span>${desc}</span>` : ""}</div><div class="sr-r"></div></div>`);
  $(".sr-r", r).append(...[].concat(control));
  return r;
}
function sw(path) {
  const el = h(`<label class="switch"><input type="checkbox" ${setting(path) ? "checked" : ""}><span></span></label>`);
  $("input", el).onchange = (e) => save(path, e.target.checked);
  return el;
}
function num(path, { min, max, step = 1, cls = "w-s", unit } = {}) {
  const wrap = h(`<div class="row" style="gap:6px"><input class="input ${cls}" type="number" ${min !== undefined ? `min="${min}"` : ""} ${max !== undefined ? `max="${max}"` : ""} step="${step}" value="${setting(path) ?? ""}">${unit ? `<span class="dim" style="font-size:12px">${unit}</span>` : ""}</div>`);
  $("input", wrap).onchange = (e) => {
    let v = parseFloat(e.target.value);
    if (isNaN(v)) v = 0;
    if (min !== undefined) v = Math.max(min, v);
    if (max !== undefined) v = Math.min(max, v);
    e.target.value = v;
    save(path, v);
  };
  return wrap;
}
function txt(path, { cls = "", placeholder = "", type = "text" } = {}) {
  const el = h(`<input class="input ${cls}" type="${type}" value="${esc(setting(path) ?? "")}" placeholder="${esc(placeholder)}">`);
  el.onchange = () => save(path, el.value);
  return el;
}
function sel(path, options) {
  const el = h(`<select class="select">${options.map(([v, l]) => `<option value="${esc(v)}" ${String(setting(path)) === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`);
  el.onchange = () => save(path, isNaN(+el.value) || el.value === "" ? el.value : +el.value);
  return el;
}
function segc(path, options) { return seg(options, String(setting(path)), (v) => save(path, v)); }
function save(path, value) {
  const keys = path.split(".");
  const obj = {};
  let cur = obj;
  keys.forEach((k, i) => { cur[k] = i === keys.length - 1 ? value : {}; cur = cur[k]; });
  return saveSettings(obj).catch(toastErr);
}
function section(id, ic, title, desc, ...children) {
  const s = h(`<section class="set-sec" id="set-${id}"><h3>${icon(ic)}${title}</h3>${desc ? `<p>${desc}</p>` : ""}<div class="set-card"></div></section>`);
  $(".set-card", s).append(...children.filter(Boolean));
  return s;
}
function resetBtn(sec) {
  const b = h(`<button class="btn xs ghost">${icon("refresh", "sm")}恢复本节默认</button>`);
  b.onclick = async () => { store.settings = await post("/api/settings/reset", { section: sec }); (await import("../core/store.js")).applyUi(); render(); toast("已恢复", "ok"); };
  return b;
}

// ---------- 渲染 ----------
function render() {
  const body = $(".set-body", root);
  const y = $("[data-scroll]", root).scrollTop;
  body.innerHTML = "";
  body.append(
    secUi(), secChat(), secThink(), secParams(), secContext(), secEngine(), secImage(), secApi(), secServer(), secPresets(), secData(), secLogs(), secKeys(), secAbout(),
  );
  $("[data-scroll]", root).scrollTop = y;
  S.lastSig = JSON.stringify(store.settings);
}

function secUi() {
  const acc = h(`<div class="accent-pick">${ACCENTS.map(([k, c, n]) => `<button style="background:${c}" data-a="${k}" data-tip="${n}" class="${setting("ui.accent") === k ? "on" : ""}"></button>`).join("")}</div>`);
  $$("[data-a]", acc).forEach((b) => (b.onclick = () => { save("ui.accent", b.dataset.a); $$("[data-a]", acc).forEach((x) => x.classList.toggle("on", x === b)); }));
  return section("ui", "palette", "外观", "主题、配色、字号与动画。",
    row("主题", "深色 / 浅色 / 跟随系统", segc("ui.theme", [["dark", "深色"], ["light", "浅色"], ["auto", "跟随系统"]])),
    row("界面语言", "导航、按钮与提示的语言。「跟随启动器」由 app-cn.py / app-en.py 决定", segc("ui.language", [["auto", "跟随启动器"], ["zh", "中文"], ["en", "English"]])),
    row("强调色", "按钮、进度条、高亮等使用的颜色", acc),
    row("字体大小", "全局基础字号", num("ui.font_size", { min: 12, max: 20, unit: "px" })),
    row("消息区宽度", "对话内容的最大宽度", num("ui.msg_width", { min: 600, max: 1600, step: 20, unit: "px" })),
    row("界面动画", "关闭后所有过渡与动效立即完成", sw("ui.animations")),
    row("命令行开机动画", "启动 app-cn.py / app-en.py 时在终端里播放的动画（完整约 8 秒，快速约 3 秒）", segc("ui.boot_animation", [["full", "完整"], ["quick", "快速"], ["off", "关闭"]])),
    row("动画速度", "数值越大动画越快", sel("ui.anim_speed", [[0.6, "舒缓 0.6×"], [0.8, "柔和 0.8×"], [1, "标准 1×"], [1.3, "轻快 1.3×"], [1.8, "迅速 1.8×"]])),
    row("显示历史侧栏", "首页左侧的对话列表（Ctrl+B 切换）", sw("ui.sidebar_open")),
    row("自动启用 MTP 推测解码", "为带 MTP 头的模型自动以 draft-mtp 模式重启引擎，加载后在统计行显示「MTP 加速中」；对无 MTP 头的模型无影响。关闭后 MTP 模型按普通模式运行", sw("ui.mtp_auto")),
    row("", "", resetBtn("ui")));
}

function secChat() {
  const sys = h(`<div class="set-row col"><div class="sr-l"><b>全局系统提示词</b><span>对所有对话生效（单个对话可在顶部 ✦ 按钮中单独覆盖）</span></div><textarea class="textarea" placeholder="例如：你是一个乐于助人的助手，回答使用简体中文。">${esc(setting("chat.system_prompt"))}</textarea></div>`);
  $("textarea", sys).onchange = (e) => save("chat.system_prompt", e.target.value);
  return section("chat", "chat", "对话", "发送方式、渲染选项与对话行为。", sys,
    row("发送快捷键", "另一种组合用于换行", segc("chat.send_key", [["enter", "Enter 发送"], ["ctrl_enter", "Ctrl+Enter 发送"]])),
    row("自动命名对话", "首条消息截取 / 让模型生成标题", segc("chat.auto_title", [["first", "截取首句"], ["ai", "AI 生成"], ["off", "关闭"]])),
    row("显示统计行", "在每条回复下方显示输入/输出/速度/推理/首 Token", sw("chat.show_stats")),
    row("渲染数学公式", "KaTeX 渲染 $...$、$$...$$、\\(...\\)、\\[...\\]（含化学式 \\ce{}）", sw("chat.render_math")),
    row("自动渲染 Mermaid 图表", "mermaid 代码块默认显示为图表", sw("chat.render_mermaid")),
    row("HTML 代码块默认显示", "可在每个代码块上随时切换", segc("chat.html_default", [["code", "代码"], ["preview", "预览"]])),
    row("代码自动换行", "长代码行自动折行显示", sw("chat.code_wrap")),
    row("启动时自动加载上次的模型", "默认关闭：启动后不占用显存，等你选好模型再加载", sw("chat.auto_load_last")),
    row("删除对话前确认", "", sw("chat.confirm_delete")),
    row("默认思考强度", "新消息默认使用的深度思考档位", sel("chat.default_think", store.thinkLevels.map((l) => [l, THINK_META[l].name + " · " + THINK_META[l].desc]))),
    row("", "", resetBtn("chat")));
}

function secThink() {
  const grid = h(`<div class="budget-grid"></div>`);
  for (const lv of store.thinkLevels.filter((l) => l !== "off")) {
    const f = h(`<div class="field"><label>${THINK_META[lv].name}<span class="dim" style="font-weight:400">${THINK_META[lv].desc}</span></label><input class="input" type="number" min="0" step="128" value="${setting("thinking.budgets")[lv] ?? 0}"></div>`);
    $("input", f).onchange = (e) => saveSettings({ thinking: { budgets: { [lv]: Math.max(0, parseInt(e.target.value) || 0) } } });
    grid.appendChild(f);
  }
  return section("think", "brain", "深度思考", "每个档位允许的最大思考 tokens。达到上限后会自动结束思考并基于已有推理输出答案；0 表示不限制。支持 low/medium/high 原生档位的模型（如 gpt-oss）会自动映射。",
    grid, row("", "", resetBtn("thinking")));
}

function secParams() {
  const items = [
    ["temperature", "Temperature 温度", "越高越发散", 0, 2, 0.05], ["top_p", "Top P", "核采样阈值", 0, 1, 0.01], ["top_k", "Top K", "0 = 不限", 0, 200, 1],
    ["min_p", "Min P", "", 0, 1, 0.01], ["typical_p", "Typical P", "1 = 关闭", 0, 1, 0.01], ["repeat_penalty", "重复惩罚", "1 = 不惩罚", 0.5, 2, 0.01],
    ["repeat_last_n", "重复检测窗口", "-1 = 全部上下文", -1, 4096, 1], ["presence_penalty", "存在惩罚", "", -2, 2, 0.05], ["frequency_penalty", "频率惩罚", "", -2, 2, 0.05],
    ["seed", "随机种子", "-1 = 随机", -1, 2147483647, 1], ["mirostat", "Mirostat", "0 关 / 1 / 2", 0, 2, 1], ["mirostat_tau", "Mirostat τ", "", 0, 10, 0.1], ["mirostat_eta", "Mirostat η", "", 0, 1, 0.01],
    ["num_thread", "CPU 线程数", "0 = 自动", 0, 256, 1], ["num_batch", "批大小", "", 1, 8192, 1], ["num_gpu", "GPU 层数", "-1 = 自动，0 = 纯 CPU", -1, 999, 1],
  ];
  const stop = h(`<input class="input w-l" value="${esc((setting("params.stop") || []).join(","))}" placeholder="逗号分隔">`);
  stop.onchange = () => save("params.stop", stop.value.split(",").map((s) => s.trim()).filter(Boolean));
  return section("params", "sliders", "默认参数", "与首页「参数」浮窗同步。",
    row("使用模型自带默认参数", "开启后忽略温度/TopP 等采样参数，使用模型 Modelfile 中的配置", sw("params.use_model_defaults")),
    ...items.map(([k, t, d, min, max, step]) => row(t, d, num("params." + k, { min, max, step }))),
    row("停止词", "遇到这些字符串时停止生成", stop),
    row("", "", resetBtn("params")));
}

function secContext() {
  return section("context", "layers", "上下文", "与首页「上下文」浮窗同步。",
    row("上下文窗口 num_ctx", "越大越占显存；超过模型声明上限可能导致效果下降", num("context.num_ctx", { min: 512, max: 1048576, step: 512, unit: "tokens", cls: "" })),
    row("最大输入", "发送前裁剪较早历史，0 = 不限制", num("context.max_input", { min: 0, max: 1048576, step: 256, unit: "tokens", cls: "" })),
    row("最大输出", "单次回复上限（含思考），0 = 不限制", num("context.max_output", { min: 0, max: 262144, step: 128, unit: "tokens", cls: "" })),
    row("保留历史轮数", "只发送最近 N 轮对话，0 = 全部", num("context.history_turns", { min: 0, max: 1000 })),
    row("", "", resetBtn("context")));
}

function secEngine() {
  const pathRow = h(`<div class="row"></div>`);
  const pin = txt("engine.ollama_path", { cls: "w-l mono", placeholder: store.app.ollama || "自动检测" });
  const pb = h(`<button class="btn sm">${icon("folder", "sm")}浏览</button>`);
  pb.onclick = async () => { const f = await pickPath({ mode: "file", title: "选择 ollama.exe" }); if (f) { pin.value = f; save("engine.ollama_path", f); } };
  pathRow.append(pin, pb);
  const engList = h(`<div class="set-row col"><div class="sr-l"><b>运行中的引擎</b><span>每个分区一个独立的 ollama serve 进程，所有缓存写入项目 runtime 目录</span></div><div class="eng-list"></div></div>`);
  const drawEng = () => {
    $(".eng-list", engList).innerHTML = store.engines.length ? `<div class="table-wrap" style="border-radius:12px"><table class="dt"><thead><tr><th>分区</th><th>端口</th><th>状态</th><th>PID</th><th>版本</th><th>运行时长</th><th>模型目录</th></tr></thead><tbody>
      ${store.engines.map((e) => `<tr><td>${esc(e.name)}</td><td class="mono">${e.port || "—"}</td><td><span class="row" style="gap:6px"><i class="dot ${e.status === "running" ? "ok" : e.status === "starting" ? "warn" : e.status === "error" ? "err" : ""}"></i>${esc(e.status)}</span>${e.error ? `<div class="hint" style="color:var(--err)">${esc(e.error)}</div>` : ""}</td><td class="mono">${e.pid || "—"}</td><td class="mono">${esc(e.version || "—")}</td><td class="mono">${e.uptime ? fmtMs(e.uptime * 1000) : "—"}</td><td class="mono dim ellipsis" style="max-width:280px">${esc(e.models_dir)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="hint">暂无运行中的引擎</div>`;
  };
  drawEng();
  on("engines", drawEng);
  return section("engine", "cpu", "Ollama 引擎", "修改以下选项会自动重启所有分区引擎（当前加载的模型会被卸载）。",
    row("ollama.exe 路径", `当前：${esc(store.app.ollama || "未找到")}`, pathRow),
    row("引擎起始端口", "分区引擎端口 = 起始端口 + 分区 ID（被占用时自动顺延）", num("engine.base_port", { min: 1024, max: 65000 })),
    row("模型保持时间 keep_alive", "空闲多久后自动卸载模型，例如 5m、30m、2h、-1（永不）", txt("engine.keep_alive", { cls: "w-s mono" })),
    row("推测解码 spec_type", "自动 = 由「自动启用 MTP」按模型能力决定；强制 draft-mtp 对所有模型生效（无 MTP 头的模型会忽略）；none 强制关闭", sel("engine.spec_type", [["", "自动（推荐）"], ["draft-mtp", "强制 draft-mtp"], ["none", "强制关闭"]])),
    row("Flash Attention", "降低显存占用、提升长上下文速度（需显卡支持）", sw("engine.flash_attention")),
    row("KV 缓存量化", "q8_0 / q4_0 可显著节省显存（需开启 Flash Attention）", sel("engine.kv_cache_type", [["f16", "f16（默认）"], ["q8_0", "q8_0（省一半）"], ["q4_0", "q4_0（省 3/4）"]])),
    row("并行请求数", "同一模型同时处理的请求数（越大越占显存）", num("engine.num_parallel", { min: 1, max: 16 })),
    row("预留显存", "为其他程序保留的显存", num("engine.gpu_overhead_mb", { min: 0, max: 65536, step: 128, unit: "MB" })),
    row("加载超时", "模型加载卡住多久后放弃，例如 5m", txt("engine.load_timeout", { cls: "w-s mono" })),
    row("禁用 Ollama 云功能", "OLLAMA_NO_CLOUD=1", sw("engine.no_cloud")),
    row("多 GPU 平铺", "OLLAMA_SCHED_SPREAD：总是把模型分布到所有 GPU", sw("engine.sched_spread")),
    row("退出时关闭引擎", "关闭程序时同时结束所有 ollama 进程", sw("engine.stop_on_exit")),
    engList,
    row("", "", resetBtn("engine")));
}

function secImage() {
  const st = h(`<div class="set-row col"><div class="sr-l"><b>引擎与资产</b><span>生图由 stable-diffusion.cpp（sd-cli.exe）执行，与 Ollama 引擎相互独立</span></div><div class="img-st"></div></div>`);
  const drawSt = async () => {
    const s = await get("/api/image/status").catch(() => null);
    if (!s) { $(".img-st", st).innerHTML = `<div class="hint">无法获取生图状态</div>`; return; }
    const eng = s.engine || {};
    $(".img-st", st).innerHTML = `<div class="row wrap" style="gap:8px">
      <span class="tag ${eng.available ? "ok" : "err"}">${eng.available ? "sd-cli 就绪" : "缺少 sd-cli"}</span>
      <span class="tag ${eng.cuda ? "" : "warn"}">${eng.cuda ? "CUDA 运行时" : "仅 CPU / 未检测到 CUDA"}</span>
      ${s.missing?.length ? `<span class="tag err">缺少 ${s.missing.length} 项资产</span>` : `<span class="tag ok">资产齐全</span>`}
      <div class="grow"></div><button class="btn xs" data-rf>${icon("refresh", "sm")}刷新</button></div>
      <div class="hint mono" style="margin-top:8px">${esc(eng.version || "")}</div>`;
    $("[data-rf]", st).onclick = drawSt;
  };
  drawSt();
  const picker = (path, title, ph) => {
    const wrap = h(`<div class="row"></div>`);
    const inp = txt(path, { cls: "w-l mono", placeholder: ph });
    const b = h(`<button class="btn sm">${icon("folder", "sm")}浏览</button>`);
    b.onclick = async () => { const f = await pickPath({ mode: "file", title }); if (f) { inp.value = f; save(path, f); } };
    wrap.append(inp, b);
    return wrap;
  };
  return section("image", "palette", "生图", "扩散模型与默认参数。模型路径留空时自动在 models/image 与项目根目录中查找；修改后到「生图」页刷新即可生效。",
    row("启用生图", "关闭后「生图」页不再接受新任务", sw("image.enabled")),
    st,
    row("扩散模型", "例如 qwen_image_2.1-Q4_K_M.gguf", picker("image.diffusion_model", "选择扩散模型", "自动检测")),
    row("VAE", "必须是模型配套的 VAE，例如 qwen_image_2.1_vae_bf16.safetensors", picker("image.vae", "选择 VAE", "自动检测")),
    row("文本编码器", "例如 Qwen3VL-8B-Instruct-Q4_K_M.gguf", picker("image.llm", "选择文本编码器", "自动检测")),
    row("视觉投影", "图生图（参考图编辑）必需：mmproj-*.gguf", picker("image.llm_vision", "选择视觉投影", "可选")),
    row("默认步数", "新任务的默认采样步数", num("image.steps", { min: 1, max: 100 })),
    row("默认 CFG", "提示词引导强度，越高越贴合提示词", num("image.cfg_scale", { min: 1, max: 20, step: 0.5 })),
    row("默认采样器", "与生图页参数面板同步", sel("image.sampling", ["euler", "euler_a", "heun", "dpm2", "dpm++2s_a", "dpm++2m", "dpm++2mv2", "ipndm", "ipndm_v", "lcm", "ddim_trailing", "tcd", "res_multistep", "res_2s", "er_sde", "euler_cfg_pp", "euler_a_cfg_pp", "euler_ge", "dpm++2m_sde", "dpm++2m_sde_bt", "lms"].map((x) => [x, x]))),
    row("默认调度器", "留空使用模型自带调度", sel("image.scheduler", [["", "模型默认"], ...["discrete", "karras", "exponential", "ays", "gits", "sgm_uniform", "simple", "smoothstep", "kl_optimal", "lcm", "bong_tangent", "ltx2", "logit_normal", "flux2", "flux", "beta", "llada_image"].map((x) => [x, x])])),
    row("实时预览", "每步输出一张预览（proj 快、vae 清晰但慢）", sel("image.preview", [["none", "关闭"], ["proj", "proj"], ["vae", "vae"]])),
    row("权重卸载到内存", "显存不足时把权重放内存按需载入（--offload-to-cpu），速度略降", sw("image.offload_to_cpu")),
    row("生图前卸载语言模型", "Ollama 模型与扩散模型会争抢显存，建议开启", sw("image.unload_llm")),
    row("产物保留天数", "0 表示不自动清理；清理同时删除数据库记录", num("image.keep_days", { min: 0, max: 3650, unit: "天" })),
    row("", "", resetBtn("image")));
}

function secApi() {
  const status = h(`<div class="set-row col"><div class="sr-l"><b>服务状态</b></div><div class="api-st"></div></div>`);
  const drawSt = async () => {
    const s = await get("/api/api-server");
    const base = s.url ? s.url + "/v1" : "";
    const key = setting("api.api_key");
    $(".api-st", status).innerHTML = `<div class="row wrap"><span class="tag ${s.running ? "ok" : s.error ? "err" : ""}">${s.running ? "运行中" : s.enabled ? "未运行" : "已关闭"}</span>${base ? `<span class="mono">${esc(base)}</span><button class="btn xs" data-cp>${icon("copy", "sm")}复制</button>` : ""}${s.error ? `<span class="hint" style="color:var(--err)">${esc(s.error)}</span>` : ""}<div class="grow"></div><button class="btn xs" data-rs>${icon("refresh", "sm")}重启 API 服务</button></div>
      <pre class="raw" style="margin-top:10px">curl ${esc(base || "http://127.0.0.1:" + setting("api.port") + "/v1")}/chat/completions \\
  -H "Content-Type: application/json" ${setting("api.require_key") ? `\\\n  -H "Authorization: Bearer ${esc(key || "<API_KEY>")}" ` : ""}\\
  -d '{"model": "${esc(store.load.model || "qwen3.5:2b")}", "messages": [{"role": "user", "content": "你好"}], "stream": false}'</pre>
      <div class="hint">兼容 OpenAI（/v1/chat/completions、/v1/completions、/v1/embeddings、/v1/models）与 Ollama 原生（/api/chat、/api/generate、/api/tags…）。模型名可写成「分区名/模型ID」指定分区。</div>`;
    $("[data-cp]", status)?.addEventListener("click", () => copyText(base));
    $("[data-rs]", status).onclick = async () => { await post("/api/api-server/restart"); drawSt(); toast("API 服务已重启", "ok"); };
  };
  drawSt();
  on("settings_saved", () => setTimeout(drawSt, 500));
  const keyRow = h(`<div class="row"></div>`);
  const kin = txt("api.api_key", { cls: "w-l mono", placeholder: "未设置", type: "password" });
  const show = h(`<button class="btn sm icon" data-tip="显示/隐藏">${icon("eye", "sm")}</button>`);
  show.onclick = () => { kin.type = kin.type === "password" ? "text" : "password"; };
  const gen = h(`<button class="btn sm">${icon("key", "sm")}生成</button>`);
  gen.onclick = async () => { const r = await post("/api/api-server/genkey"); kin.value = r.api_key; store.settings.api.api_key = r.api_key; kin.type = "text"; toast("已生成新密钥", "ok"); drawSt(); };
  keyRow.append(kin, show, gen);
  const authSw = sw("api.require_key");
  $("input", authSw).addEventListener("change", async (e) => {
    const r = await saveSettings({ api: { require_key: e.target.checked } }, { immediate: true });
    if (e.target.checked && r.settings.api.api_key) { kin.value = r.settings.api.api_key; kin.type = "text"; toast("已自动生成 API 密钥", "ok", 4000); }
    drawSt();
  });
  return section("api", "globe", "API 服务", "为其他应用（如 Cherry Studio、Open WebUI、VS Code 插件）提供统一接口，自动路由到对应分区的模型。",
    row("启用 API 服务", "", sw("api.enabled")),
    row("API 端口", "修改后自动重启 API 服务", num("api.port", { min: 1024, max: 65535 })),
    row("允许局域网访问", "监听 0.0.0.0（请同时开启密钥验证）", sw("api.lan")),
    row("需要 API 密钥", "开启时若尚未设置密钥，会自动生成一个并填入下方", authSw),
    row("API 密钥", "", keyRow),
    row("允许跨域 CORS", "浏览器网页可直接调用", sw("api.cors")),
    row("记录 API 用量", "计入「用量统计」", sw("api.record_usage")),
    status, row("", "", resetBtn("api")));
}

function secServer() {
  return section("server", "monitor", "界面服务", "Web 界面的监听设置，修改后需重启 app.py。",
    row("界面端口", `当前访问地址：${location.origin}`, num("server.port", { min: 1024, max: 65535 })),
    row("监听地址", "127.0.0.1 仅本机；0.0.0.0 允许局域网访问界面（无鉴权，请谨慎）", sel("server.host", [["127.0.0.1", "127.0.0.1（仅本机）"], ["0.0.0.0", "0.0.0.0（局域网）"]])),
    row("启动时自动打开浏览器", "", sw("server.open_browser")),
    row("关闭程序", "停止后台服务与所有引擎", Object.assign(h(`<button class="btn danger sm">${icon("power", "sm")}退出程序</button>`), {
      onclick: async () => { if (await confirmBox("确定退出程序？后台服务和所有模型引擎都会停止。", { danger: true, ok: "退出" })) { await post("/api/app/shutdown"); document.body.innerHTML = `<div class="empty" style="height:100vh">${icon("power")}<div>程序已退出，可以关闭此页面</div></div>`; } },
    })));
}

function secPresets() {
  const box = h(`<div></div>`);
  const draw = async () => {
    const list = await get("/api/presets");
    box.innerHTML = "";
    for (const p of list) {
      const it = h(`<div class="preset-item"><div class="pi-main"><b>${esc(p.name)}</b><p>${esc(p.content)}</p></div><button class="btn xs ghost icon" data-e>${icon("edit", "sm")}</button><button class="btn xs ghost icon danger" data-d>${icon("trash", "sm")}</button></div>`);
      $("[data-e]", it).onclick = () => edit(p);
      $("[data-d]", it).onclick = async () => { if (await confirmBox(`删除预设「${esc(p.name)}」？`, { danger: true })) { await del(`/api/presets/${p.id}`); draw(); } };
      box.appendChild(it);
    }
    const add = h(`<div class="preset-item"><button class="btn sm">${icon("plus", "sm")}新建预设</button></div>`);
    $("button", add).onclick = () => edit();
    box.appendChild(add);
  };
  const edit = (p) => {
    const body = h(`<div class="col"><div class="field"><label>名称</label><input class="input" value="${esc(p?.name || "")}"></div><div class="field"><label>提示词内容</label><textarea class="textarea" style="min-height:200px">${esc(p?.content || "")}</textarea></div></div>`);
    const foot = h(`<div style="display:contents"><button class="btn ghost" data-c>取消</button><button class="btn primary" data-o>保存</button></div>`);
    const m = modal({ title: p ? "编辑预设" : "新建预设", body, foot, wide: true, icon: "wand" });
    $("[data-c]", foot).onclick = m.close;
    $("[data-o]", foot).onclick = async () => {
      const data = { name: $("input", body).value.trim(), content: $("textarea", body).value };
      try { if (p) await put(`/api/presets/${p.id}`, data); else await post("/api/presets", data); m.close(); draw(); } catch (e) { toastErr(e); }
    };
  };
  draw();
  return section("presets", "wand", "提示词预设", "在对话顶部 ✦ 按钮中一键套用为该对话的系统提示词。", box);
}

function secData() {
  const stBox = h(`<div class="set-row col"><div class="sr-l"><b>设置存储</b><span>所有参数（含亮色/暗色主题、模型参数、上下文、引擎选项）都写入 SQLite 数据库，重启后自动恢复</span></div><div class="st-info"></div></div>`);
  const drawStore = async () => {
    try {
      const m = await get("/api/settings/meta");
      const latest = (m.sections || []).reduce((a, s) => Math.max(a, s.updated_at || 0), 0);
      $(".st-info", stBox).innerHTML = `<div class="gguf-info" style="margin:0">${[
        ["真源（数据库）", m.db_path + "  ·  " + m.rows + " 行"],
        ["镜像（可读备份）", m.mirror_path],
        ["最近写入", latest ? fmtTime(latest) : "—"],
        ["本次载入来源", { db: "数据库", json: "由 settings.json 迁移", defaults: "默认值" }[m.source] || m.source],
      ].map(([k, v]) => `<div class="kv"><div class="k">${k}</div><div class="v mono" style="font-size:12px;word-break:break-all">${esc(v)}</div></div>`).join("")}</div>
      <div class="hint" style="margin-top:8px">界面主题/配色同时缓存在浏览器本地，打开页面即刻套用，不会再先闪一下深色。</div>`;
    } catch (e) { $(".st-info", stBox).innerHTML = `<div class="hint">${esc(e.message)}</div>`; }
  };
  drawStore();
  const bk = h(`<div class="set-row col"><div class="sr-l"><b>备份列表</b><span>保存在 data/backups，包含数据库与设置</span></div><div class="bk-list"></div></div>`);
  const drawBk = async () => {
    const list = await get("/api/data/backups");
    $(".bk-list", bk).innerHTML = list.length ? list.map((b) => `<div class="row" style="padding:6px 0;border-bottom:1px dashed var(--line)"><span class="mono" style="font-size:12.5px">${esc(b.name)}</span><span class="dim" style="font-size:12px">${fmtTime(b.ts)} · ${fmtBytes(b.size)}</span><div class="grow"></div><a class="btn xs" href="/api/data/backups/${encodeURIComponent(b.name)}">${icon("download", "sm")}下载</a><button class="btn xs ghost danger" data-del="${esc(b.name)}">${icon("trash", "sm")}</button></div>`).join("") : `<div class="hint">暂无备份</div>`;
    $$("[data-del]", bk).forEach((b) => (b.onclick = async () => { await del(`/api/data/backups/${encodeURIComponent(b.dataset.del)}`); drawBk(); }));
  };
  drawBk();
  const act = (label, ic, fn, danger) => Object.assign(h(`<button class="btn sm ${danger ? "danger" : ""}">${icon(ic, "sm")}${label}</button>`), { onclick: fn });
  return section("data", "db", "数据与备份", "所有数据都保存在项目文件夹内。",
    stBox,
    row("启动时自动备份", "每次启动自动备份，保留最近 5 份", sw("data.auto_backup")),
    row("用量记录保留天数", "超过天数的用量记录在启动时清理，0 = 永久保留", num("data.usage_retention_days", { min: 0, max: 3650, unit: "天" })),
    row("立即备份", "", act("创建备份", "db", async () => { const r = await post("/api/data/backup"); toast("已备份：" + r.name, "ok"); drawBk(); })),
    row("压缩数据库", "回收已删除数据占用的空间", act("VACUUM", "refresh", async () => { const r = await post("/api/data/vacuum"); toast(`完成，数据库大小 ${fmtBytes(r.size)}`, "ok"); })),
    row("清理日志", "清空 runtime/logs 中的日志文件", act("清理", "trash", async () => { await post("/api/data/clear-logs"); toast("日志已清理", "ok"); })),
    row("清理临时文件", "清空 runtime/tmp", act("清理", "trash", async () => { const r = await post("/api/data/clear-tmp"); toast(`已清理 ${r.cleared} 项`, "ok"); })),
    row("删除全部对话", "包括置顶对话，不可恢复", act("全部删除", "trash", async () => {
      if (!(await confirmBox("删除<b>所有</b>对话（包括置顶）？此操作不可恢复。", { danger: true, ok: "全部删除" }))) return;
      const r = await del("/api/conversations?keep_pinned=0");
      toast(`已删除 ${r.deleted} 个对话`, "ok");
      localStorage.removeItem("lastConv");
    }, true)),
    bk);
}

function secLogs() {
  const box = h(`<div class="set-row col"><div class="row"><span class="dim" style="font-size:12px">实时刷新 · 与后端命令行同步</span><div class="grow"></div><button class="btn xs" data-dl>${icon("download", "sm")}下载</button></div><div class="log-box"></div></div>`);
  const lb = $(".log-box", box);
  const line = (r) => `<div class="l-${r.level}"><span class="l-t">${fmtTime(r.ts, false)} [${esc(r.source)}]</span> ${esc(r.msg)}</div>`;
  get("/api/logs?n=300").then((rows) => { lb.innerHTML = rows.map(line).join(""); lb.scrollTop = lb.scrollHeight; });
  on("log", (r) => {
    if (!lb.isConnected) return;
    const stick = lb.scrollHeight - lb.scrollTop - lb.clientHeight < 40;
    lb.insertAdjacentHTML("beforeend", line(r));
    while (lb.children.length > 500) lb.firstElementChild.remove();
    if (stick) lb.scrollTop = lb.scrollHeight;
  });
  $("[data-dl]", box).onclick = () => download("app-log.txt", lb.innerText);
  return section("logs", "terminal", "运行日志", "", box);
}

function secKeys() {
  const keys = [["Enter", "发送消息（可在对话设置中改为 Ctrl+Enter）"], ["Shift + Enter", "换行"], ["Esc", "停止生成 / 关闭弹窗"], ["Ctrl + K", "新建对话"], ["Ctrl + B", "折叠 / 展开历史侧栏"],
    ["/", "聚焦输入框"], ["↑", "输入框为空时，填入上一条消息"], ["Alt + 1~5", "切换顶部导航页面"], ["Ctrl + V", "在输入框中粘贴图片"]];
  const box = h(`<div>${keys.map(([k, d]) => `<div class="set-row"><div class="sr-l"><b>${d}</b></div><div class="sr-r">${k.split(" + ").map((x) => `<kbd>${x}</kbd>`).join(" + ")}</div></div>`).join("")}</div>`);
  return section("keys", "keyboard", "快捷键", "", box);
}

function secAbout() {
  const box = h(`<div class="set-row col"><div class="about"></div></div>`);
  get("/api/system/about").then((a) => {
    $(".about", box).innerHTML = `<div class="gguf-info" style="margin:0">${[
      ["程序", `${a.app} v${a.version}`], ["Ollama", a.ollama_version ? "v" + a.ollama_version : "—"], ["Python", a.python], ["系统", a.platform],
      ["对话数", a.conversations], ["消息数", a.messages], ["模型数", a.models], ["数据大小", fmtBytes(a.data_size)],
    ].map(([k, v]) => `<div class="kv"><div class="k">${k}</div><div class="v" style="font-size:13px">${esc(v)}</div></div>`).join("")}</div>
    <div class="hint" style="margin-top:12px;line-height:1.9">项目目录：<span class="mono">${esc(a.root)}</span><br>数据库：<span class="mono">${esc(a.db_path)}</span><br>Ollama：<span class="mono">${esc(a.ollama_exe)}</span><br>API：<span class="mono">${esc(a.api_url || "未启用")}</span></div>
    <div class="row" style="margin-top:10px"><button class="btn sm" data-open>${icon("folder", "sm")}打开项目文件夹</button></div>`;
    $("[data-open]", box).onclick = () => post("/api/fs/open", { path: a.root }).catch(toastErr);
  });
  return section("about", "info", "关于", "", box);
}

function importSettings() {
  const inp = h(`<input type="file" accept=".json" class="hidden">`);
  inp.onchange = async () => {
    try {
      const data = JSON.parse(await inp.files[0].text());
      store.settings = await post("/api/settings/import", data);
      (await import("../core/store.js")).applyUi();
      render();
      toast("设置已导入", "ok");
    } catch (e) { toastErr(e); }
  };
  inp.click();
}
