"""英文词表：backend/routes 下的接口提示文案（fail 返回、接口日志）。"""
TABLE = {
    # ---------------- routes/__init__.py ----------------
    "不存在": "Not found",

    # ---------------- api_chat.py ----------------
    "对话不存在": "Conversation not found",
    "任务不存在或已过期": "Task not found or expired",
    "名称和内容不能为空": "Name and content cannot be empty",

    # ---------------- api_misc.py ----------------
    "端口范围 1024-65535": "Port must be within 1024-65535",
    "API 端口不能与界面端口相同": "API port must differ from the UI port",
    "已开启 API 密钥校验并自动生成密钥": "API key check enabled; a key was generated automatically",
    "无效的配置文件": "Invalid config file",
    "API 服务不可用": "API service unavailable",
    "无效的文件夹名称": "Invalid folder name",
    "文件夹不存在": "Folder does not exist",
    "不允许打开该路径": "Opening this path is not allowed",
    "备份不存在": "Backup not found",

    # ---------------- api_models.py ----------------
    "分区不存在": "Partition not found",
    "未知操作": "Unknown action",
    "模型不存在": "Model not found",
    "请输入新名称": "Please enter a new name",
    "重新加载以应用 MTP 设置失败：%s": "Failed to reload to apply the MTP setting: %s",
    "没有收到文件": "No file received",
    "只支持 .gguf 文件": "Only .gguf files are supported",

    # ---------------- api_image.py ----------------
    "任务不存在": "Task not found",
    "没有收到图片": "No image received",
    "图片不存在": "Image not found",
    "暂无预览": "No preview available",
}