// 生图：文生图 / 图生图（参考图 + 指令编辑 / 多参考图），后端走 stable-diffusion.cpp
import { del, get, on, post } from "../core/api.js";
import { icon } from "../core/icons.js";
import { saveSettings, setting } from "../core/store.js";
import { $, $$, esc, fmtBytes, fmtMs, h, toast, toastErr } from "../core/ui.js";

const S = {
  root: null, refs: [], history: [], status: null,
  // job：正在运行（排队/生成）的任务，只由进度与完成事件更新；viewing：正在查看的历史作品，与运行任务互不影响
  job: null, viewing: null,
  busy: false, startedAt: 0, previewTimer: null, tickTimer: null,
};

const SIZES = [
  ["1:1", 1024, 1024], ["3:4", 768, 1024], ["4:3", 1024, 768], ["9:16", 768, 1344], ["16:9", 1344, 768],
];
const SAMPLERS = ["euler", "euler_a", "heun", "dpm2", "dpm++2s_a", "dpm++2m", "dpm++2mv2",
  "ipndm", "ipndm_v", "lcm", "ddim_trailing", "tcd", "res_multistep", "res_2s",
  "er_sde", "euler_cfg_pp", "euler_a_cfg_pp", "euler_ge", "dpm++2m_sde", "dpm++2m_sde_bt", "lms"];
const SCHEDULERS = ["", "discrete", "karras", "exponential", "ays", "gits", "sgm_uniform",
  "simple", "smoothstep", "kl_optimal", "lcm", "bong_tangent", "ltx2", "logit_normal",
  "flux2", "flux", "beta", "llada_image"];

export function mount(root) {
  S.root = root;
  root.innerHTML = `<div class="page"><div class="page-inner">
    <div class="page-head"><div><h1>生图</h1><p>本地扩散模型出图：文生图、图生图（参考图编辑）、多参考图合成。全程离线，不上传云端。</p></div>
      <div class="actions"><button class="btn" data-open-folder>${icon("folder")}打开输出目录</button><button class="btn" data-refresh>${icon("refresh")}刷新状态</button></div></div>
    <div class="img-grid">
      <div class="col" style="gap:16px">
        <div class="card img-composer">
          <div class="card-title">${icon("wand")}创作<span class="grow"></span><span class="hint" data-engine-hint></span></div>
          <div class="ref-zone" data-refzone>
            <input type="file" class="hidden" accept="image/*" multiple data-reffile>
            <div class="ref-empty">${icon("image", "lg")}<div><b>拖入参考图</b>（可选）</div><span>图生图：把图片拖到这里，或点击选择。支持多张参考图。</span></div>
            <div class="ref-list"></div>
          </div>
          <div class="field" style="margin-top:14px"><label>提示词 PROMPT</label>
            <textarea class="textarea img-prompt" data-prompt rows="4" placeholder="例如：专业电商白底商品图，一条波西米亚印花长裤，正面平铺，柔和影棚光，细节清晰"></textarea>
            <div class="hint">越具体越好：主体 + 材质 + 构图 + 光线 + 风格。Ctrl/⌘ + Enter 直接生成。</div></div>
          <details class="img-neg"><summary>反向提示词 NEGATIVE（可选）</summary>
            <textarea class="textarea" data-negative rows="2" placeholder="例如：文字, 水印, 模糊, 变形, 多余手指"></textarea></details>
          <div class="row" style="margin-top:14px;gap:10px">
            <button class="btn primary" data-gen>${icon("sparkle")}开始生成</button>
            <button class="btn danger hidden" data-cancel>${icon("stop", "sm")}停止</button>
            <span class="grow"></span>
            <span class="hint" data-queuehint></span>
          </div>
        </div>
        <div class="card img-result">
          <div class="card-title">${icon("image")}结果<span class="grow"></span><span class="hint" data-result-hint></span></div>
          <div class="img-progress hidden">
            <div class="ip-head">
              <div class="grow"><div class="row" style="justify-content:space-between"><b data-stage>准备中</b><span class="mono hint" data-pmeta></span></div>
                <div class="bar" style="height:8px;margin-top:8px"><i data-pbar style="width:0%"></i></div>
                <div class="hint" style="margin-top:6px" data-ptime></div></div>
              <div class="ip-preview hidden"><img data-previewimg alt="实时预览"><span>实时预览</span></div>
            </div>
          </div>
          <div class="img-outputs"></div>
          <div class="empty img-empty">${icon("image")}<div>还没有生成结果</div><span>填写提示词后点击「开始生成」</span></div>
        </div>
      </div>
      <div class="col" style="gap:16px">
        <div class="card img-params">
          <div class="card-title">${icon("sliders")}参数<span class="grow"></span><span class="hint">自动保存</span></div>
          <div class="label">画面尺寸</div>
          <div class="size-grid">
            ${SIZES.map(([n, w, hh]) => `<button class="size-item" data-size="${w}x${hh}"><b>${n}</b><span>${w}×${hh}</span></button>`).join("")}
          </div>
          <div class="pp-row pp-row-wide" style="margin-top:10px"><label>宽 × 高</label>
            <div class="row" style="gap:6px;flex:none;justify-content:flex-end"><input class="input mono" type="number" min="256" max="2048" step="32" data-w><span class="dim">×</span><input class="input mono" type="number" min="256" max="2048" step="32" data-h></div></div>
          <div class="pp-row"><label>步数 steps</label><input class="input" type="number" min="1" max="100" step="1" data-steps></div>
          <div class="pp-row"><label>提示词强度 CFG</label><input class="input" type="number" min="1" max="20" step="0.5" data-cfg></div>
          <div class="pp-row"><label>随机种子 seed <span class="dim">(-1 随机)</span></label><input class="input" type="number" data-seed></div>
          <div class="pp-row"><label>生成张数</label><input class="input" type="number" min="1" max="4" step="1" data-batch></div>
          <div class="pp-row"><label>采样器 sampler</label><select class="select" data-sampling>
            ${SAMPLERS.map((s) => `<option>${s}</option>`).join("")}</select></div>
          <div class="pp-row"><label>调度器 scheduler</label><select class="select" data-scheduler>
            ${SCHEDULERS.map((s) => `<option value="${s}">${s || "模型默认"}</option>`).join("")}</select></div>
          <div class="pp-row"><label>流量偏移 flow-shift</label><input class="input" type="number" min="0" max="12" step="0.5" data-flow></div>
          <div class="i2i-only hidden">
            <div class="pp-sec">图生图</div>
            <div class="pp-row"><label data-tip="越低越接近参考图，越高越自由">重绘强度 strength</label><input class="input" type="number" min="0.05" max="1" step="0.05" data-strength></div>
            <div class="pp-row"><label data-tip="参考图引导强度，0 表示跟随 CFG">图像引导 img-CFG</label><input class="input" type="number" min="0" max="20" step="0.5" data-imgcfg></div>
          </div>
          <details class="img-adv"><summary>高级参数</summary>
            <div class="pp-row"><label data-tip="蒸馏引导（部分模型支持）">guidance</label><input class="input" type="number" min="0" max="20" step="0.5" data-guidance></div>
            <div class="pp-row"><label data-tip="Skip Layer Guidance，仅 DiT 模型，0 关闭">SLG scale</label><input class="input" type="number" min="0" max="10" step="0.1" data-slg></div>
            <div class="pp-row"><label data-tip="跳过 CLIP 最后 N 层，1 表示不跳过">CLIP skip</label><input class="input" type="number" min="1" max="12" step="1" data-clipskip></div>
            <div class="pp-row"><label data-tip="每步输出一张低清预览，会略微降低速度">实时预览</label>
              <select class="select" data-preview>
                <option value="none">关闭</option><option value="proj">proj（快）</option><option value="vae">vae（清晰但慢）</option>
              </select></div>
            <div class="pp-row"><label data-tip="大分辨率解码时降低显存峰值">VAE 分块解码</label>
              <label class="switch"><input type="checkbox" data-vaetiling><span></span></label></div>
          </details>
        </div>
        <div class="card">
          <div class="card-title">${icon("box")}模型与引擎</div>
          <div class="img-assets" data-assets></div>
        </div>
      </div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-title">${icon("history")}历史作品<span class="grow"></span><button class="btn xs ghost" data-clear>${icon("trash", "sm")}清空历史</button></div>
      <div class="img-gallery"></div></div>
  </div></div>`;

  bind(root);
  loadStatus();
  loadHistory();
  const t = setting("image") || {};
  if (t.prompt) $("[data-prompt]", root).value = t.prompt;
  if (t.negative) $("[data-negative]", root).value = t.negative;
  on("image", (e) => {
    if (!S.job || e.id !== S.job.id) return;
    Object.assign(S.job, e);
    renderProgress();
  });
  on("image_done", (e) => {
    if (!S.job || e.id !== S.job.id) return;
    stopPreview();
    S.busy = false;
    Object.assign(S.job, { status: e.status, error: e.error });
    renderProgress();
    if (e.status === "done") {
      toast(`生成完成 · ${e.outputs.length} 张 · ${fmtMs(e.elapsed_ms)}`, "ok", 4000);
      S.viewing = null;
      renderOutputs(e.outputs);
    } else if (e.status === "error") {
      toast("生成失败：" + (e.error || "未知错误"), "err", 8000);
    } else if (e.status === "cancelled") {
      toast("已取消生成", "warn");
    }
    loadHistory();
  });
}

export function onShow() {
  if (!S.root) return;
  loadStatus();
  loadHistory();
}

function bind(root) {
  $("[data-refresh]", root).onclick = () => { loadStatus(); loadHistory(); };
  $("[data-open-folder]", root).onclick = () => post("/api/image/open").catch(() => toast("请手动打开 data/images", "warn"));
  $("[data-gen]", root).onclick = generate;
  $("[data-cancel]", root).onclick = async () => {
    if (!S.job) return;
    try { await post(`/api/image/jobs/${S.job.id}/cancel`); } catch (e) { toastErr(e); }
  };
  $("[data-clear]", root).onclick = async () => {
    for (const j of S.history) {
      try { await del(`/api/image/jobs/${j.id}`); } catch { /* 单项失败继续 */ }
    }
    S.history = [];
    $(".img-outputs", root).innerHTML = "";
    $(".img-empty", root).classList.remove("hidden");
    renderGallery();
    toast("历史已清空", "ok");
  };
  $("[data-prompt]", root).oninput = (e) => saveSettings({ image: { prompt: e.target.value } });
  $("[data-negative]", root).oninput = (e) => saveSettings({ image: { negative: e.target.value } });
  $("[data-refzone]", root).onclick = (e) => {
    if (e.target.closest(".ref-item")) return;
    $("[data-reffile]", root).click();
  };
  $("[data-reffile]", root).onchange = (e) => { uploadRefs([...e.target.files]); e.target.value = ""; };
  const zone = $("[data-refzone]", root);
  let depth = 0;
  zone.addEventListener("dragenter", (e) => { e.preventDefault(); depth++; zone.classList.add("over"); });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; });
  zone.addEventListener("dragleave", (e) => { e.preventDefault(); if (--depth <= 0) { depth = 0; zone.classList.remove("over"); } });
  zone.addEventListener("drop", (e) => {
    e.preventDefault(); e.stopPropagation();
    depth = 0; zone.classList.remove("over");
    const files = [...(e.dataTransfer?.files || [])].filter((f) => f.type.startsWith("image/") || /\.(png|jpe?g|webp|bmp)$/i.test(f.name));
    if (!files.length) { toast("只能拖入图片文件", "warn"); return; }
    uploadRefs(files);
  });
  $$("[data-size]", root).forEach((b) => {
    b.onclick = () => {
      const [w, hh] = b.dataset.size.split("x").map(Number);
      saveSettings({ image: { width: w, height: hh } });
      syncSizeUi();
    };
  });
  const bindNum = (sel, key, parse = Number) => {
    const el = $(sel, root);
    el.onchange = () => {
      const v = parse(el.value);
      if (Number.isNaN(v)) return;
      saveSettings({ image: { [key]: v } });
      syncSizeUi();
    };
  };
  bindNum("[data-steps]", "steps", (v) => parseInt(v, 10));
  bindNum("[data-cfg]", "cfg_scale");
  bindNum("[data-seed]", "seed", (v) => parseInt(v, 10));
  bindNum("[data-batch]", "batch", (v) => parseInt(v, 10));
  bindNum("[data-flow]", "flow_shift");
  bindNum("[data-strength]", "strength");
  bindNum("[data-imgcfg]", "img_cfg_scale");
  bindNum("[data-guidance]", "guidance");
  bindNum("[data-slg]", "slg_scale");
  bindNum("[data-clipskip]", "clip_skip", (v) => parseInt(v, 10));
  bindNum("[data-w]", "width", (v) => parseInt(v, 10));
  bindNum("[data-h]", "height", (v) => parseInt(v, 10));
  $("[data-sampling]", root).onchange = (e) => saveSettings({ image: { sampling: e.target.value } });
  $("[data-scheduler]", root).onchange = (e) => saveSettings({ image: { scheduler: e.target.value } });
  $("[data-preview]", root).onchange = (e) => saveSettings({ image: { preview: e.target.value } });
  $("[data-vaetiling]", root).onchange = (e) => saveSettings({ image: { vae_tiling: e.target.checked } });
  $("[data-prompt]", root).onkeydown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); generate(); }
  };
}

function syncSizeUi() {
  const root = S.root;
  const t = setting("image") || {};
  const cur = `${t.width || 1024}x${t.height || 1024}`;
  $$("[data-size]", root).forEach((b) => b.classList.toggle("on", b.dataset.size === cur));
  $("[data-w]", root).value = t.width || 1024;
  $("[data-h]", root).value = t.height || 1024;
  $("[data-queuehint]", root).textContent = S.refs.length ? `图生图模式 · ${S.refs.length} 张参考图` : "文生图模式";
  $(".i2i-only", root).classList.toggle("hidden", S.refs.length === 0);
}

function fillParams() {
  const root = S.root;
  const t = setting("image") || {};
  $("[data-steps]", root).value = t.steps ?? 24;
  $("[data-cfg]", root).value = t.cfg_scale ?? 4;
  $("[data-seed]", root).value = t.seed ?? -1;
  $("[data-batch]", root).value = t.batch ?? 1;
  $("[data-flow]", root).value = t.flow_shift ?? 3;
  $("[data-strength]", root).value = t.strength ?? 0.75;
  $("[data-imgcfg]", root).value = t.img_cfg_scale ?? 0;
  $("[data-guidance]", root).value = t.guidance ?? 0;
  $("[data-slg]", root).value = t.slg_scale ?? 0;
  $("[data-clipskip]", root).value = t.clip_skip ?? 1;
  $("[data-sampling]", root).value = t.sampling || "euler";
  $("[data-scheduler]", root).value = t.scheduler || "";
  $("[data-preview]", root).value = t.preview || "none";
  $("[data-vaetiling]", root).checked = !!t.vae_tiling;
  syncSizeUi();
}

async function loadStatus() {
  try {
    S.status = await get("/api/image/status");
  } catch { return; }
  const root = S.root;
  const st = S.status;
  const eng = st.engine || {};
  $("[data-engine-hint]", root).innerHTML = eng.available
    ? `<span class="dot ok"></span> 引擎就绪${eng.cuda ? " · CUDA" : " · CPU"}`
    : `<span class="dot err"></span> 未找到 sd-cli.exe`;
  const rows = [
    ["扩散模型", "diffusion_model", "diffusion"],
    ["VAE", "vae", "vae"],
    ["文本编码器", "llm", "llm"],
    ["视觉投影", "llm_vision", "vision"],
  ];
  $("[data-assets]", root).innerHTML = rows.map(([label, key, kind]) => {
    const p = st.resolved?.[key] || "";
    const name = p ? p.split(/[\\/]/).pop() : "未配置";
    const need = kind !== "vision";
    return `<div class="asset-row ${p ? "" : need ? "miss" : "opt"}">
      <span class="lbl">${label}${need ? "" : '<span class="dim">（图生图）</span>'}</span>
      <span class="mono ellipsis" data-tip="${esc(p)}">${esc(name)}</span></div>`;
  }).join("") + (st.missing?.length ? `<div class="hint" style="color:var(--warn);margin-top:8px">${icon("alert", "sm")} 缺少：${st.missing.map((k) => rows.find((r) => r[1] === k)?.[0] || k).join("、")}。把对应文件放进 <span class="mono">models/image</span>，或在设置 → 生图中指定路径。</div>` : "");
  fillParams();
}

async function uploadRefs(files) {
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files.slice(0, 8)) fd.append("files", f);
  try {
    const r = await fetch("/api/image/upload", { method: "POST", body: fd });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || "上传失败");
    S.refs.push(...d.data);
    renderRefs();
    toast(`已添加 ${d.data.length} 张参考图`, "ok");
  } catch (e) { toastErr(e); }
}

function renderRefs() {
  const list = $(".ref-list", S.root);
  const empty = $(".ref-empty", S.root);
  empty.classList.toggle("hidden", S.refs.length > 0);
  list.innerHTML = "";
  S.refs.forEach((r, i) => {
    const el = h(`<div class="ref-item"><img src="${r.url}" alt=""><button class="rm" data-tip="移除">${icon("x", "sm")}</button>
      <span class="nm ellipsis">${esc(r.name)}</span></div>`);
    $(".rm", el).onclick = (e) => { e.stopPropagation(); S.refs.splice(i, 1); renderRefs(); };
    list.appendChild(el);
  });
  syncSizeUi();
}

async function generate() {
  if (S.busy) return;
  const prompt = $("[data-prompt]", S.root).value.trim();
  if (!prompt) { toast("请先填写提示词", "warn"); $("[data-prompt]", S.root).focus(); return; }
  const t = setting("image") || {};
  S.busy = true;
  S.startedAt = Date.now();
  $("[data-gen]", S.root).classList.add("loading");
  $("[data-cancel]", S.root).classList.remove("hidden");
  $("[data-result-hint]", S.root).textContent = "";
  try {
    const r = await post("/api/image/generate", {
      prompt, negative: $("[data-negative]", S.root).value.trim(),
      refs: S.refs.map((x) => x.path),
      width: t.width, height: t.height, steps: t.steps, cfg_scale: t.cfg_scale,
      seed: t.seed, batch: t.batch, sampling: t.sampling, scheduler: t.scheduler,
      flow_shift: t.flow_shift, strength: t.strength, img_cfg_scale: t.img_cfg_scale,
      guidance: t.guidance, slg_scale: t.slg_scale, clip_skip: t.clip_skip,
      preview: t.preview, vae_tiling: t.vae_tiling,
    });
    S.job = { id: r.id, status: "queued", stage: "排队中", progress: 0, step: 0, total_steps: 0, it_s: 0, eta_s: 0 };
    S.viewing = null;
    $(".img-empty", S.root).classList.add("hidden");
    $(".img-outputs", S.root).innerHTML = "";
    $(".img-progress", S.root).classList.remove("hidden");
    renderProgress();
    startPreview();
    startTick();
  } catch (e) {
    S.busy = false;
    $("[data-gen]", S.root).classList.remove("loading");
    $("[data-cancel]", S.root).classList.add("hidden");
    toastErr(e);
  }
}

function startTick() {
  clearInterval(S.tickTimer);
  S.tickTimer = setInterval(() => {
    if (!S.busy) { clearInterval(S.tickTimer); return; }
    renderProgress();
  }, 1000);
}

function startPreview() {
  stopPreview();
  const t = setting("image") || {};
  const box = $(".ip-preview", S.root);
  if (!t.preview || t.preview === "none") { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const img = $("[data-previewimg]", S.root);
  S.previewTimer = setInterval(() => {
    if (!S.busy || !S.job) return;
    img.src = `/api/image/preview/${S.job.id}?t=${Date.now()}`;
  }, 1500);
}

function stopPreview() {
  clearInterval(S.previewTimer);
  S.previewTimer = null;
  $(".ip-preview", S.root)?.classList.add("hidden");
}

function renderProgress() {
  const root = S.root;
  const j = S.job;
  if (!j) return;
  const running = j.status === "running" || j.status === "queued";
  $("[data-gen]", root).classList.toggle("loading", running);
  $("[data-cancel]", root).classList.toggle("hidden", !running);
  if (!running) {
    S.busy = false;
    $("[data-gen]", root).classList.remove("loading");
    clearInterval(S.tickTimer);
  }
  $("[data-pbar]", root).style.width = Math.max(2, Math.min(100, j.progress || 0)) + "%";
  $("[data-pbar]", root).parentElement.classList.toggle("indet", running && (j.progress || 0) < 2);
  $("[data-stage]", root).textContent = j.stage || "准备中";
  $("[data-pmeta]", root).textContent = j.total_steps ? `${j.step}/${j.total_steps} 步 · ${(j.it_s || 0).toFixed(2)} s/步` : "";
  const elapsed = Math.round(j.elapsed ?? (S.startedAt ? (Date.now() - S.startedAt) / 1000 : 0));
  const parts = [];
  if (running && elapsed) parts.push(`已用 ${elapsed}s`);
  if (j.eta_s) parts.push(`剩余约 ${Math.max(1, Math.round(j.eta_s))}s`);
  if (j.queued) parts.push(`队列 ${j.queued}`);
  $("[data-ptime]", root).textContent = parts.join(" · ");
  $("[data-result-hint]", root).textContent = running ? (j.status === "queued" ? (j.stage || "排队中") + "…" : "生成中…") : (S.viewing ? "查看历史作品" : j.status === "done" ? "已完成" : "");
}

function renderOutputs(outputs) {
  const box = $(".img-outputs", S.root);
  $(".img-empty", S.root).classList.add("hidden");
  box.innerHTML = "";
  if (!outputs?.length) return;
  const grid = h('<div class="out-grid stagger"></div>');
  for (const o of outputs) {
    const el = h(`<div class="out-item"><img src="${o.url}" alt="${esc(o.name)}" loading="lazy">
      <div class="out-act"><a class="btn xs" href="${o.url}" download="${esc(o.name)}">${icon("download", "sm")}下载</a>
      <a class="btn xs ghost" href="${o.url}" target="_blank">${icon("expand", "sm")}原图</a></div>
      <span class="out-meta">${o.width}×${o.height} · ${fmtBytes(o.size)}</span></div>`);
    $("img", el).onclick = () => window.open(o.url, "_blank");
    grid.appendChild(el);
  }
  box.appendChild(grid);
}

async function loadHistory() {
  try { S.history = await get("/api/image/jobs?limit=40"); } catch { return; }
  const last = S.history.find((j) => j.status === "done" && j.outputs?.length);
  // 只在既没有运行任务、也没有手动查看历史时才自动回填最近作品，避免覆盖用户正在看的进度/结果
  if (last && !$(".img-outputs", S.root).children.length && !S.busy && !S.viewing) {
    renderOutputs(last.outputs);
    $(".img-progress", S.root).classList.add("hidden");
  }
  renderGallery();
}

function renderGallery() {
  const box = $(".img-gallery", S.root);
  if (!box) return;
  const items = S.history.filter((j) => j.outputs?.length);
  if (!items.length) {
    box.innerHTML = `<div class="empty">${icon("image")}<div>还没有历史作品</div></div>`;
    return;
  }
  box.innerHTML = "";
  const grid = h('<div class="gal-grid stagger"></div>');
  for (const j of items) {
    for (const o of j.outputs) {
      const el = h(`<div class="gal-item"><img src="${o.url}" loading="lazy" alt="">
        <div class="gal-info"><span class="ellipsis">${esc(j.prompt)}</span><span class="dim">${fmtMs(j.elapsed_ms)} · ${o.width}×${o.height} · seed ${j.params?.seed ?? "—"}</span></div></div>`);
      // 只看结果，不碰运行中的任务：图片下方展示历史作品，运行任务的进度条照常更新
      el.onclick = () => {
        S.viewing = j;
        renderOutputs([o]);
        scrollTo({ top: 0, behavior: "smooth" });
      };
      grid.appendChild(el);
    }
  }
  box.appendChild(grid);
}
