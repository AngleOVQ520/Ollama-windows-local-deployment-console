// 英文词表：core/ui.js、core/markdown.js、pages/filebrowser.js
export default {
  dict: {
    // ---- core/ui.js：相对时间 / 通用确认框 / 剪贴板 ----
    "刚刚": "Just now",
    // 相对时间后缀（字符串拼接，需配合下方 rules 生效）
    " 分钟前": " min ago",
    " 小时前": " hr ago",
    " 天前": " days ago",

    // 通用确认框 / 输入框
    "确认操作": "Confirm Action",
    "确定": "OK",
    "取消": "Cancel",

    // 复制提示
    "已复制到剪贴板": "Copied to clipboard",

    // ---- core/markdown.js：代码块 / 全屏预览 ----
    "预览": "Preview",
    "代码": "Code",
    "源码": "Source Code",
    "新标签页": "New Tab",
    "下载": "Download",
    "复制": "Copy",
    "已复制": "Copied",
    "全屏预览": "Fullscreen Preview",
    "自动换行": "Toggle Word Wrap",

    // 动态文案（模板插值 + 字符串拼接，需配合下方 rules 生效）
    "{n} 行": "{n} lines",
    "Mermaid 语法错误：{msg}": "Mermaid syntax error: {msg}",

    // ---- pages/filebrowser.js：路径选择器 ----
    "上一级": "Up One Level",
    "输入路径后回车": "Type a path and press Enter",
    "新建文件夹": "New Folder",
    "文件夹名称": "Folder Name",
    "进入目标文件夹后点击「选择此文件夹」": "Enter the target folder, then click \"Select This Folder\"",
    "双击 .gguf 文件或选中后点击「选择」": "Double-click a .gguf file, or select one and click \"Select\"",
    "选择此文件夹": "Select This Folder",
    "选择": "Select",
    "选择文件夹": "Select Folder",
    "选择 GGUF 文件": "Select GGUF File",
    "请选择上方的磁盘": "Select a drive above",
    "空文件夹": "Empty folder",

    // 磁盘剩余空间（模板插值，需配合下方 rules 生效）
    "{size} 可用": "{size} free",
  },
  rules: [
    // 相对时间：`Math.floor(s / 60) + " 分钟前"` 等
    [/^(\d+) 分钟前$/, "$1 minutes ago"],
    [/^(\d+) 小时前$/, "$1 hours ago"],
    [/^(\d+) 天前$/, "$1 days ago"],
    // 代码块行数：`${lines} 行`
    [/^(\d+) 行$/, "$1 lines"],
    // Mermaid 渲染失败：`Mermaid 语法错误：${esc(e.message || e)}`
    [/^Mermaid 语法错误：([\s\S]+)$/, "Mermaid syntax error: $1"],
    // 磁盘可用空间：`${fmtBytes(x.free, 0)} 可用`
    [/^(.+) 可用$/, "$1 free"],
  ],
};