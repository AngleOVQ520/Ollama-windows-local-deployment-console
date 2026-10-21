"""英文词表：backend/services/loader.py、backend/services/engines.py（加载阶段与引擎日志）"""
TABLE = {
    # ---------------- loader 日志 ----------------
    "对话结束，开始切换到 %s": "Chat finished, switching to %s",
    "正在输出，%s 将在本次回复结束后加载": "Generating; %s will load after this reply finishes",
    "已卸载 %s": "Unloaded %s",
    "推测解码设置变更：%r → %r（重启引擎）": "Speculative decoding setting changed: %r → %r (restarting engine)",
    "%s 加载完成（%.1fs，ctx=%d）": "%s loaded (%.1fs, ctx=%d)",
    "%s 加载失败：%s": "%s failed to load: %s",
    "MTP/推测解码探测：%s（%s）": "MTP/speculative decoding probe: %s (%s)",
    "已启用": "enabled",
    "未检测到": "not detected",

    # ---------------- loader 阶段名 ----------------
    "准备中": "Preparing",
    "卸载 %s": "Unloading %s",
    "以 MTP 模式启动引擎": "Starting engine in MTP mode",
    "启动引擎（推测解码关闭）": "Starting engine (speculative decoding off)",
    "读取权重": "Loading weights",
    "初始化上下文 / 计算图": "Initializing context / graph",
    "启动推理进程": "Starting inference process",
    "读取权重 %.0f%%": "Loading weights %.0f%%",
    "加载失败": "Load failed",

    # ---------------- engines 日志 ----------------
    "分区「%s」引擎就绪 :%d  v%s": "Partition \"%s\" engine ready :%d  v%s",
}