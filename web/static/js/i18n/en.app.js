// 英文词表：app.js（外壳 / 导航 / 顶栏状态）
export default {
  dict: {
    // 导航标签
    "首页": "Home",
    "添加模型": "Add Model",
    "模型列表": "Model List",
    "生图": "Generate Image",
    "用量统计": "Usage Stats",
    "设置": "Settings",

    // 顶栏品牌与状态
    "Ollama 控制台": "Ollama Console",
    "CPU / 内存 / GPU / 显存": "CPU / RAM / GPU / VRAM",
    "内存": "RAM",
    "显存": "VRAM",
    "未加载模型": "No model loaded",
    "切换深色/浅色": "Toggle dark/light",

    // 动态文案（模板插值 + 字符串拼接，需配合下方 rules 生效）
    "{title} · Ollama 控制台": "{title} · Ollama Console",
    "已加载 · 显存 {size} · ctx {num_ctx}": "Loaded · VRAM {size} · ctx {num_ctx}",
    "无法连接后端：": "Failed to connect to backend: ",
    "模型加载失败：": "Model load failed: ",
    "后台初始化未完成：": "Background initialization incomplete: ",

    // 全局提示（toast）
    "与后端的连接中断，正在重连…": "Connection to the backend was lost, reconnecting…",
    "已重新连接后端": "Reconnected to the backend",
  },
  rules: [
    // 文档标题：`${r[1]} · Ollama 控制台`
    [/^(.+) · Ollama 控制台$/, "$1 · Ollama Console"],
    // 加载状态提示：`已加载 · 显存 ${fmtBytes(size_vram)} · ctx ${num_ctx}`
    [/^已加载 · 显存 (.+) · ctx (.+)$/, "Loaded · VRAM $1 · ctx $2"],
    // 连接失败提示：`"无法连接后端：" + e.message`
    [/^无法连接后端：([\s\S]+)$/, "Failed to connect to backend: $1"],
    // 模型加载失败提示：`"模型加载失败：" + st.error`
    [/^模型加载失败：([\s\S]+)$/, "Model load failed: $1"],
    // 启动失败提示：`"后台初始化未完成：" + b.app.boot_error`
    [/^后台初始化未完成：([\s\S]+)$/, "Background initialization incomplete: $1"],
  ],
};