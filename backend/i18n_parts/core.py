"""英文词表：backend/core/gguf.py、backend/services/library.py"""
TABLE = {
    # ---------------- GGUF 解析（core/gguf.py） ----------------
    "文件意外结束": "Unexpected end of file",
    "字符串长度异常": "Invalid string length",
    "未知的元数据类型 %s": "Unknown metadata type %s",
    "不是有效的 GGUF 文件": "Not a valid GGUF file",
    "不支持的 GGUF 版本 %s": "Unsupported GGUF version %s",
    "GGUF 头部数据异常": "Invalid GGUF header data",
    "张量维度异常": "Invalid tensor dimensions",
    "…（共 %d 字符）": "… (%d chars in total)",
    "[数组 · %d 项]": "[array · %d items]",

    # ---------------- 内置推荐模型描述（services/library.py） ----------------
    "通义千问 3.5，支持思考 / 视觉 / 工具": "Qwen 3.5 with thinking / vision / tools",
    "通义千问 3，混合思考模型": "Qwen 3 hybrid thinking model",
    "DeepSeek 推理模型": "DeepSeek reasoning model",
    "Google Gemma 3，多模态": "Google Gemma 3 multimodal",
    "Meta Llama 3.2 小模型": "Meta Llama 3.2 small models",
    "OpenAI 开放权重推理模型": "OpenAI open-weight reasoning model",
    "微软 Phi-4": "Microsoft Phi-4",
    "千问代码模型": "Qwen coding model",
    "文本向量模型": "Text embedding model",
    "超小模型，适合测试": "Ultra-small model, good for testing",
}