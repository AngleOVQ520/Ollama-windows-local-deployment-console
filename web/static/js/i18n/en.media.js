// 英文词表：pages/image.js（生图）、pages/stats.js（用量统计）
//
// 约定：
// - dict 收录静态文案：HTML 文本、按钮/标签、placeholder、data-tip / title / aria-label、toast 与弹窗文案、
//   图表标题 / 图例 / 轴名 / 系列名 / tooltip、表头。
// - 源码里带 ${表达式} 的模板文案，dict 用 {} 占位符作 key，实际替换由下方 rules 正则完成。
// - rules 不带 g 标志，捕获组用 $1 $2 引用。
// - 不收录：只出现在注释里的中文、采样器 / 调度器名称（euler / dpm++2m 等）、模型名、文件路径、
//   代码、JSON 字段名、纯数字与单位、与中文相同的英文。
export default {
  dict: {
    // ---------------- pages/image.js：页面骨架 / 创作区 ----------------
    "生图": "Generate Image",
    "本地扩散模型出图：文生图、图生图（参考图编辑）、多参考图合成。全程离线，不上传云端。": "Local diffusion generation: text-to-image, image-to-image (reference editing), and multi-reference composition. Fully offline, nothing is uploaded.",
    "打开输出目录": "Open Output Folder",
    "刷新状态": "Refresh Status",
    "创作": "Create",
    "拖入参考图": "Drop reference images",
    "（可选）": "(optional)",
    "图生图：把图片拖到这里，或点击选择。支持多张参考图。": "Image-to-image: drop an image here or click to choose. Multiple reference images are supported.",
    "提示词 PROMPT": "Prompt",
    "例如：专业电商白底商品图，一条波西米亚印花长裤，正面平铺，柔和影棚光，细节清晰": "e.g. professional e-commerce product shot on a white background, a pair of bohemian-print pants, laid flat, soft studio lighting, crisp details",
    "越具体越好：主体 + 材质 + 构图 + 光线 + 风格。Ctrl/⌘ + Enter 直接生成。": "The more specific the better: subject + material + composition + lighting + style. Ctrl/⌘ + Enter to generate directly.",
    "反向提示词 NEGATIVE（可选）": "Negative Prompt NEGATIVE (optional)",
    "例如：文字, 水印, 模糊, 变形, 多余手指": "e.g. text, watermark, blurry, deformed, extra fingers",
    "开始生成": "Start Generating",
    "停止": "Stop",
    "结果": "Result",
    "准备中": "Preparing",
    "实时预览": "Live Preview",
    "还没有生成结果": "No results yet",
    "填写提示词后点击「开始生成」": "Enter a prompt, then click \"Start Generating\"",

    // ---------------- pages/image.js：参数面板 ----------------
    "参数": "Parameters",
    "自动保存": "Auto-saved",
    "画面尺寸": "Image Size",
    "宽 × 高": "Width × Height",
    "步数 steps": "Steps",
    "提示词强度 CFG": "Prompt Strength CFG",
    "随机种子 seed": "Random seed",
    "(-1 随机)": "(-1 random)",
    "生成张数": "Number of Images",
    "采样器 sampler": "Sampler",
    "调度器 scheduler": "Scheduler",
    "模型默认": "Model default",
    "流量偏移 flow-shift": "Flow Shift",
    "图生图": "Image-to-Image",
    "越低越接近参考图，越高越自由": "Lower stays closer to the reference image; higher gives it more freedom",
    "重绘强度 strength": "Denoise Strength",
    "参考图引导强度，0 表示跟随 CFG": "Reference image guidance strength; 0 means follow CFG",
    "图像引导 img-CFG": "Image Guidance img-CFG",
    "高级参数": "Advanced Parameters",
    "蒸馏引导（部分模型支持）": "Distillation guidance (supported by some models)",
    "Skip Layer Guidance，仅 DiT 模型，0 关闭": "Skip Layer Guidance; DiT models only; 0 disables it",
    "跳过 CLIP 最后 N 层，1 表示不跳过": "Skip the last N CLIP layers; 1 means no skip",
    "每步输出一张低清预览，会略微降低速度": "Output a low-res preview each step; slightly slower",
    "关闭": "Off",
    "proj（快）": "proj (fast)",
    "vae（清晰但慢）": "vae (sharp but slow)",
    "大分辨率解码时降低显存峰值": "Lower the VRAM peak when decoding at high resolutions",
    "VAE 分块解码": "VAE Tiled Decoding",
    "模型与引擎": "Models & Engine",
    "历史作品": "History",
    "清空历史": "Clear History",

    // ---------------- pages/image.js：状态 / 提示 / 动态文案 ----------------
    "未知错误": "Unknown error",
    "已取消生成": "Generation cancelled",
    "请手动打开 data/images": "Please open data/images manually",
    "历史已清空": "History cleared",
    "只能拖入图片文件": "Only image files can be dropped here",
    "文生图模式": "Text-to-image mode",
    "未找到 sd-cli.exe": "sd-cli.exe not found",
    "扩散模型": "Diffusion Model",
    "文本编码器": "Text Encoder",
    "视觉投影": "Vision Projection",
    "未配置": "Not configured",
    "（图生图）": "(image-to-image)",
    "，或在设置 → 生图中指定路径。": ", or set the paths in Settings → Generate Image.",
    "上传失败": "Upload failed",
    "移除": "Remove",
    "请先填写提示词": "Please enter a prompt first",
    "排队中": "Queued",
    "排队中…": "Queued…",
    "生成中…": "Generating…",
    "已完成": "Completed",
    "下载": "Download",
    "原图": "Original",
    "查看历史作品": "Viewing history",
    "还没有历史作品": "No history yet",

    // ---------------- pages/stats.js：页面骨架 / 图表卡片 ----------------
    "用量统计": "Usage Stats",
    "所有对话与 API 调用的 token 用量、速度与耗时分析。": "Token usage, speed, and latency analysis for all chats and API calls.",
    "导出 CSV": "Export CSV",
    "清空": "Clear",
    "用量趋势": "Usage Trend",
    "每日输入 / 输出 / 思考 tokens": "Daily input / output / thinking tokens",
    "模型用量占比": "Model Usage Share",
    "按输出 tokens": "By output tokens",
    "速度与首 Token 趋势": "Speed & First Token Trend",
    "每日平均生成速度（tok/s）与首 token 延迟（ms）": "Daily average generation speed (tok/s) and first token latency (ms)",
    "今日平均速度": "Today's Average Speed",
    "与历史最高速度对比": "Compared with the all-time peak speed",
    "活跃时段热力图": "Activity Heatmap",
    "星期 × 小时 调用次数": "Weekday × hour call counts",
    "今日 24 小时分布": "Today's 24-Hour Distribution",
    "调用次数与 tokens": "Call counts and tokens",
    "模型排行": "Model Ranking",
    "输出 tokens / 调用次数": "Output tokens / calls",
    "速度分布": "Speed Distribution",
    "tok/s 区间的调用次数": "Calls by tok/s range",
    "首 Token 延迟分布": "First Token Latency Distribution",
    "ms 区间的调用次数": "Calls by ms range",
    "输出长度分布": "Output Length Distribution",
    "每次输出 tokens": "Tokens per output",
    "输入 × 输出 散点": "Input × Output Scatter",
    "每个点是一次调用，大小表示速度": "Each point is one call; size indicates speed",
    "来源与状态": "Source & Status",
    "界面对话 / API；成功 / 停止 / 失败": "UI chats / API; success / stopped / failed",
    "模型明细": "Model Details",
    "最近调用": "Recent Calls",

    // ---------------- pages/stats.js：区间选择 / 周期对比 ----------------
    "今日": "Today",
    "7 天": "7 Days",
    "30 天": "30 Days",
    "90 天": "90 Days",
    "1 年": "1 Year",
    "近 7 天": "Last 7 Days",
    "近 30 天": "Last 30 Days",
    "全部": "All",
    "1 天": "1 Day",

    // ---------------- pages/stats.js：KPI ----------------
    "调用次数": "Calls",
    "清空所有用量统计记录？对话记录不受影响。": "Clear all usage statistics? Chat history is not affected.",
    "已清空": "Cleared",
    "新增": "New",
    "今日 vs 昨日": "Today vs Yesterday",
    "总输入 tokens": "Total Input tokens",
    "总输出 tokens": "Total Output tokens",
    "思考 tokens": "Thinking tokens",
    "平均速度": "Avg Speed",
    "平均首 Token": "Avg First Token",
    "对话 / 消息": "Chats / Messages",
    "失败 / 停止": "Failed / Stopped",
    "输入 tokens": "Input tokens",
    "输出 tokens": "Output tokens",
    "合计 tokens": "Total tokens",
    "使用模型数": "Models Used",

    // ---------------- pages/stats.js：图表系列 / 轴名 / 图例 ----------------
    "输入": "Input",
    "输出": "Output",
    "思考": "Thinking",
    "合计": "Total",
    "失败": "Failed",
    "首 Token": "First Token",
    "来源": "Source",
    "状态": "Status",
    "无": "None",
    "暂无数据": "No data",
    "界面对话": "UI Chats",
    "API 调用": "API Calls",
    "成功": "Success",
    "手动停止": "Stopped manually",
    "调用": "Calls",
    "模型": "Model",
    "次数": "Count",
    "次": "times",
    "周一": "Mon",
    "周二": "Tue",
    "周三": "Wed",
    "周四": "Thu",
    "周五": "Fri",
    "周六": "Sat",
    "周日": "Sun",

    // ---------------- pages/stats.js：表格表头 / 状态 / 空态 ----------------
    "峰值速度": "Peak Speed",
    "平均耗时": "Avg Time",
    "最近使用": "Last Used",
    "时间": "Time",
    "对话": "Chat",
    "速度": "Speed",
    "推理": "Reasoning",
    "总耗时": "Total Time",
    "该时间段暂无数据，去首页聊几句吧": "No data in this period. Go to the Home page and chat a bit.",
    "暂无调用记录": "No calls yet",

    // ---------------- 带变量的模板文案（{} 为占位符，实际替换见下方 rules） ----------------
    "生成完成 · {} 张 · {}": "Generation complete · {} images · {}",
    "生成失败：": "Generation failed: ",
    "图生图模式 · {} 张参考图": "Image-to-image · {} reference images",
    "已添加 {} 张参考图": "{} reference images added",
    "累计 {}": "Total {}",
    "占输出 {}%": "{}% of output",
    "峰值 {} tok/s": "Peak {} tok/s",
    "平均总耗时 {}": "Avg total {}",
    "{} 条消息 · 活跃 {} 天": "{} messages · active {} days",
    "停止 {} 次 · 成功率 {}%": "{} stopped · {}% success",
    "自 {}": "Since {}",
    "tok/s · 峰值 {}": "tok/s · Peak {}",
    " tokens（{}%）": " tokens ({}%)",
  },
  rules: [
    // ---- pages/image.js ----
    // 排队提示：`(j.stage || "排队中") + "…"`（对话生成期间 stage 为「等待对话结束」）
    [/^等待对话结束…$/, "Waiting for chat to finish…"],
    // 生成完成 toast：`生成完成 · ${e.outputs.length} 张 · ${fmtMs(e.elapsed_ms)}`
    [/^生成完成 · (\d+) 张 · (.+)$/, "Generation complete · $1 images · $2"],
    // 生成失败 toast：`"生成失败：" + (e.error || "未知错误")`
    [/^生成失败：([\s\S]+)$/, "Generation failed: $1"],
    // 队列提示：`图生图模式 · ${S.refs.length} 张参考图`
    [/^图生图模式 · (\d+) 张参考图$/, "Image-to-image · $1 reference images"],
    // 参考图上传成功：`已添加 ${d.data.length} 张参考图`
    [/^已添加 (\d+) 张参考图$/, "$1 reference images added"],
    // 引擎状态：`<span class="dot ok"></span> 引擎就绪${eng.cuda ? " · CUDA" : " · CPU"}`（图标后有空格）
    [/^\s*引擎就绪 · CUDA$/, "Engine Ready · CUDA"],
    [/^\s*引擎就绪 · CPU$/, "Engine Ready · CPU"],
    // 缺少模型文件：` 缺少：${names.join("、")}。把对应文件放进 <span class="mono">models/image</span>...`
    [/^\s*缺少：(.+?)。把对应文件放进\s*$/, "Missing: $1. Place the corresponding files into "],
    // 进度步数：`${j.step}/${j.total_steps} 步 · ${(j.it_s || 0).toFixed(2)} s/步`
    [/^(\d+)\/(\d+) 步 · ([\d.]+) s\/步$/, "$1/$2 steps · $3 s/step"],
    // 进度时间：`[已用 ${elapsed}s] · [剩余约 ${eta}s] · [队列 ${queued}]` 的组合
    [/^已用 (\d+)s · 剩余约 (\d+)s · 队列 (\d+)$/, "$1s elapsed · ~$2s left · $3 in queue"],
    [/^已用 (\d+)s · 剩余约 (\d+)s$/, "$1s elapsed · ~$2s left"],
    [/^已用 (\d+)s · 队列 (\d+)$/, "$1s elapsed · $2 in queue"],
    [/^已用 (\d+)s$/, "$1s elapsed"],
    [/^剩余约 (\d+)s · 队列 (\d+)$/, "~$1s left · $2 in queue"],
    [/^剩余约 (\d+)s$/, "~$1s left"],
    [/^队列 (\d+)$/, "$1 in queue"],

    // ---- pages/stats.js ----
    // KPI 副标题：`累计 ${fmtNum(o.all.input)}`
    [/^累计 (.+)$/, "Total $1"],
    // 思考占比：`占输出 ${...}%`
    [/^占输出 (\d+)%$/, "$1% of output"],
    // 峰值速度：`峰值 ${(range.max_tps || 0).toFixed(1)} tok/s`
    [/^峰值 (.+) tok\/s$/, "Peak $1 tok/s"],
    // 平均总耗时：`平均总耗时 ${fmtMs(range.avg_total)}`
    [/^平均总耗时 (.+)$/, "Avg total $1"],
    // 消息与活跃：`${fmtNum(o.messages)} 条消息 · 活跃 ${o.active_days} 天`
    [/^(.+) 条消息 · 活跃 (.+) 天$/, "$1 messages · active $2 days"],
    // 失败 / 停止：`停止 ${range.stopped || 0} 次 · 成功率 ${...}%`
    [/^停止 (\d+) 次 · 成功率 (.+)%$/, "$1 stopped · $2% success"],
    // 全部周期起点：`"自 " + fmtTime(o.first_ts).slice(0, 10)`（结果为 YYYY-MM-DD）
    [/^自 (\d{4}-\d{2}-\d{2})$/, "Since $1"],
    // 速度表仪表盘名称：`tok/s · 峰值 ${(o.all.max_tps || 0).toFixed(1)}`
    [/^tok\/s · 峰值 (.+)$/, "tok/s · Peak $1"],
    // 热力图 tooltip：`周${"一二三四五六日"[...]} ${hour}:00`
    [/^周一 (\d+):00$/, "Mon $1:00"],
    [/^周二 (\d+):00$/, "Tue $1:00"],
    [/^周三 (\d+):00$/, "Wed $1:00"],
    [/^周四 (\d+):00$/, "Thu $1:00"],
    [/^周五 (\d+):00$/, "Fri $1:00"],
    [/^周六 (\d+):00$/, "Sat $1:00"],
    [/^周日 (\d+):00$/, "Sun $1:00"],
    // 小时轴：`${i}时`
    [/^(\d+)时$/, "$1:00"],
    // 模型占比 tooltip：`...输出 <b>${n}</b> tokens（${p.percent}%）`
    [/^ tokens（(.+)%）$/, " tokens ($1%)"],
    // 散点 tooltip：`输入 ${...} · 输出 ${...}`
    [/^输入 (.+?) · 输出 (.+)$/, "Input $1 · Output $2"],
    // 散点 tooltip：`速度 ${...} tok/s · 首 token ${...}`
    [/^速度 (.+) tok\/s · 首 token (.+)$/, "Speed $1 tok/s · First token $2"],
  ],
};