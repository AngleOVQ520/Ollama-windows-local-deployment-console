"""英文词表：异常冒泡文案与任务消息的补充（engines / loader / jobs）。

这几条会经由 routes 的错误处理原样返回给前端，或写入 jobs 表显示在队列里，
也叫进命令行日志面板，所以必须跟随语言。
"""

TABLE = {
    # ---------------- engines.py ----------------
    "未找到 ollama.exe，请在设置中指定路径": "ollama.exe not found — set its path in Settings",
    "引擎进程意外退出（详见 runtime/logs/engine-p%d.log）":
        "Engine process exited unexpectedly (see runtime/logs/engine-p%d.log)",
    "引擎启动超时": "Engine start timed out",

    # ---------------- loader.py ----------------
    "分区不存在": "Partition not found",
    "模型不存在：%s": "Model not found: %s",
    "加载目标已被切换": "Load target was switched",
    "模型加载失败": "Model failed to load",
    "模型加载超时": "Model load timed out",
    "引擎启动失败": "Engine failed to start",
    "引擎重启失败": "Engine failed to restart",
    "加载被中断": "Load was interrupted",

    # ---------------- jobs.py ----------------
    "用户取消（已下载部分会保留，再次下载可续传）":
        "Cancelled by user (downloaded parts are kept and can be resumed)",
    "已安装到 %s": "Installed to %s",
    "Ollama 仓库中不存在该模型：%s": "Model does not exist in the Ollama registry: %s",
    "用户取消": "Cancelled by user",
    "已导入到分区「%s」": "Imported into partition \"%s\"",

    # ---------------- chat.py：Markdown 导出正文 ----------------
    "> 导出时间：%s": "> Exported at: %s",
    "🧑 用户": "🧑 User",
    "🤖 助手 · %s": "🤖 Assistant · %s",
    "⚙ 系统": "⚙ System",
    "思考过程": "Thinking process",
    "\n`输入 %s · 输出 %s · %.1f tok/s · 首 token %.0f ms`":
        "\n`Input %s · Output %s · %.1f tok/s · First token %.0f ms`",
}