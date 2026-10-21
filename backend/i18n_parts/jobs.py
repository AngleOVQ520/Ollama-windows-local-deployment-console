"""英文词表：backend/services/jobs.py、backend/services/registry.py（下载/导入任务与分区管理）"""
TABLE = {
    # ---------------- services/jobs.py ----------------
    # 任务阶段 / 状态映射（显示在仪表盘「用量与任务」面板与网页「添加模型」队列）
    "排队中": "Queued",
    "启动引擎": "Starting engine",
    "获取清单": "Fetching manifest",
    "下载中 %s": "Downloading %s",
    "校验数据": "Verifying digest",
    "写入清单": "Writing manifest",
    "清理旧层": "Removing unused layers",
    "计算校验值": "Computing checksum",
    "已硬链接（零拷贝）": "Hard-linked (zero-copy)",
    "复制到分区": "Copying to partition",
    "创建模型": "Creating model",
    "解析 GGUF": "Parsing GGUF",
    "完成": "Done",

    # 日志
    "开始拉取 %s → 分区「%s」": "Pulling %s → partition \"%s\"",
    "已取消 %s": "Cancelled %s",
    "%s 下载完成": "%s download complete",
    "%s 下载失败: %s": "%s download failed: %s",
    "导入 %s → 分区「%s」为 %s": "Importing %s → partition \"%s\" as %s",
    "GGUF 导入完成：%s": "GGUF import complete: %s",
    "导入失败：%s": "Import failed: %s",

    # 异常提示
    "任务不存在": "Task not found",
    "请输入模型 ID，例如 qwen3.5:2b": "Please enter a model ID, e.g. qwen3.5:2b",
    "该模型正在下载中": "This model is already downloading",
    "引擎未就绪": "Engine is not ready",
    "文件不存在": "File not found",
    "GGUF 文件不存在": "GGUF file not found",
    "不是有效的 GGUF 文件：%s": "Not a valid GGUF file: %s",
    "无法创建硬链接（源文件与分区不在同一磁盘）": "Cannot create a hard link (source file and partition are on different disks)",

    # ---------------- services/registry.py ----------------
    # 异常提示
    "分区不存在": "Partition not found",
    "模型不存在": "Model not found",
    "请填写有效的文件夹路径": "Please enter a valid folder path",
    "磁盘 %s 不存在": "Drive %s does not exist",
    "分区名称不能为空": "Partition name cannot be empty",
    "该文件夹已被其他分区使用": "This folder is already used by another partition",
    "至少需要保留一个分区": "At least one partition must be kept",
    "引擎中未找到模型 %s": "Model %s not found in the engine",

    # 日志
    "新建分区「%s」→ %s": "Created partition \"%s\" → %s",
    "删除模型 %s 失败: %s": "Failed to delete model %s: %s",
    "已删除分区「%s」": "Deleted partition \"%s\"",
    "已删除模型 %s": "Deleted model %s",
    "同步分区「%s」失败: %s": "Failed to sync partition \"%s\": %s",
}