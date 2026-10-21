// 英文词表：补齐被 HTML 标签切开的句子片段，以及中英标点收尾。
// 运行时是按「文本节点」逐个查表的，像 `将删除所有<b>未置顶</b>的对话` 这种
// 句子会被拆成三段，需要为每段单独给词条；正则条目放在最后，避免遮蔽前面的精确条目。
export default {
  dict: {
    // —— 对话页：删除未置顶对话的确认框 ——
    "将删除所有": "This will delete all ",
    "未置顶": "unpinned",
    "的对话，此操作不可恢复。": " chats. This cannot be undone.",
    // —— 对话页：欢迎页首屏 ——
    "你好，今天想": "Hi, what would you like to ",
    "聊点什么": "chat about",
    "？": "?",
    // —— 对话页：空态引导（被 <b> 切开） ——
    "先点击左下角 ": "Click ",
    "，选中后会立即开始加载": " at the bottom left to pick one — loading starts right away.",
    "当前模型：": "Current model: ",
    // —— 模型列表：汇总行与删除确认（被 <b>/<span> 切开） ——
    "共 ": "Total ",
    " 个模型": " models",
    "总大小 ": "Total size ",
    "分区 ": "Partition ",
    "确定删除模型 ": "Delete model ",
    "导入的原始 GGUF 文件不会被删除。": "The original imported GGUF file will not be deleted.",
    // —— 深度思考档位：设置页会把 name 与 desc 拼成一整句，需按整句收录 ——
    "关闭 · 直接回答，最快": "Off · Answer directly, fastest",
    "Mini · 极简思考": "Mini · Minimal thinking",
    "Low · 轻度思考": "Low · Light thinking",
    "Medium · 均衡": "Medium · Balanced",
    "High · 深入推理": "High · Deep reasoning",
    "X-High · 更深入": "X-High · Deeper",
    "Max · 大量推理": "Max · Heavy reasoning",
    "Ultra · 不设上限": "Ultra · No limit",
    // —— 其他零散片段 ——
    "天": "days",
    "ollama run <模型ID>": "ollama run <model-id>",
    "当前访问地址：": "Current address: ",
    "当前：": "Current: ",
  },
  rules: [
    // 分区名是运行期插入的（可能是用户自定义中文），这里保留原值
    [/^将从分区「(.+)」中移除，未被其他模型共享的文件会被删除。$/,
      "will be removed from partition \"$1\". Files not shared with other models will be deleted."],
    // 中英标点收尾：英文模式下把全角问号/句号换成半角
    [/^(.*)？$/, "$1?"],
    [/^(.*)。$/, "$1."],
  ],
};