"""英文词表：backend/services 下的 context / chat / api_server / imagegen"""
TABLE = {
    # ---------------- context（AppContext） ----------------
    "已清理 %d 个过期生图任务": "Cleaned up %d expired image job(s)",
    "清理生图产物失败：%s": "Failed to clean up image job outputs: %s",
    "未找到 ollama.exe，请在 设置 → 引擎 中指定路径": "ollama.exe not found — specify its path in Settings → Engines",
    "分区「%s」路径不存在：%s": "Partition \"%s\" path does not exist: %s",
    "模型同步完成（%d 项更新，共 %d 个模型）": "Model sync complete (%d update(s), %d model(s) total)",
    "自动加载上次模型失败：%s": "Failed to auto-load the last model: %s",
    "引擎配置已变更，重启引擎…": "Engine settings changed, restarting engines…",
    "正在关闭…": "Shutting down…",
    "后台初始化失败：%s": "Background initialization failed: %s",
    "自动备份失败（已跳过，不影响启动）：%s": "Auto backup failed (skipped, startup unaffected): %s",

    # ---------------- chat（ChatService） ----------------
    "对话不存在": "Conversation not found",
    "该对话正在生成中": "This conversation is already generating",
    "另一个对话正在使用其他模型生成，请等待其结束或先停止它":
        "Another chat is generating with a different model; wait for it to finish or stop it first",
    "请先在左下角选择模型": "Please select a model from the bottom-left first",
    "模型不存在或已被删除": "Model does not exist or has been deleted",
    "没有可重新生成的消息": "No message available to regenerate",
    "消息不能为空": "Message cannot be empty",
    "正在准备模型…": "Preparing model…",
    "已按最大输入限制省略 %d 条较早的消息": "Omitted %d earlier message(s) due to the max input limit",
    "处理提示词…": "Processing prompt…",
    "思考达到预算上限（%d tokens），开始输出答案": "Thinking budget reached (%d tokens), starting to output the answer",
    "显存/内存不足：%s（可尝试减小上下文长度）": "Out of VRAM/RAM: %s (try reducing the context length)",
    "生成失败：%s": "Generation failed: %s",
    "自动标题失败：%s": "Auto title failed: %s",

    # ---------------- api_server（ApiServer） ----------------
    "端口 %s 被占用：%s": "Port %s already in use: %s",
    "API 服务已启动 http://%s:%s/v1": "API service started http://%s:%s/v1",

    # ---------------- imagegen（ImageGenService） ----------------
    "生图功能已在设置中关闭": "Image generation is disabled in Settings",
    "未找到生图引擎 sd-cli.exe（runtime/sdcpp/bin）": "Image engine sd-cli.exe not found (runtime/sdcpp/bin)",
    "提示词不能为空": "Prompt cannot be empty",
    "缺少生图资产：%s（请放到 models/image 目录）": "Missing image assets: %s (place them in models/image)",
    "图生图需要视觉投影模型（mmproj-*.gguf），请放到 models/image 目录":
        "Image-to-image requires a vision projection model (mmproj-*.gguf); place it in models/image",
    "收到取消请求，正在终止…": "Cancel requested, terminating…",
    "任务正在运行，请先取消": "The job is running, cancel it first",
    "生图失败：%s": "Image generation failed: %s",
    "生图前卸载当前语言模型以释放显存": "Unloading the current LLM before generation to free VRAM",
    "卸载模型失败：%s": "Failed to unload model: %s",
    "开始生图 %s：%dx%d %d 步%s": "Starting image generation %s: %dx%d %d step(s)%s",
    "（参考图 %d 张）": " (%d reference image(s))",
    "生图进程退出码 %s": "Image process exited with code %s",
    "生图失败 %s：%s": "Image generation failed %s: %s",
    "生图完成 %s（%d 张，%.1f 秒）": "Image generation done %s (%d image(s), %.1f s)",
    "显存不足：请降低分辨率/步数，或在设置中开启「权重卸载到内存」":
        "Out of VRAM: lower the resolution/steps, or enable \"Offload weights to RAM\" in Settings",
    "该扩散模型架构不被当前 sd-cli 支持（请更新 runtime/sdcpp）":
        "This diffusion model architecture is not supported by the current sd-cli (update runtime/sdcpp)",
    "模型加载失败：请检查模型文件是否完整、VAE/文本编码器是否匹配":
        "Model load failed: check that the model file is complete and the VAE/text encoder match",
    "找不到模型文件": "Model file not found",
    "只支持 png / jpg / webp / bmp 图片": "Only png / jpg / webp / bmp images are supported",

    # ---------------- imagegen 阶段名（发往前端 job.stage） ----------------
    "排队中": "Queued",
    "准备中": "Preparing",
    "加载模型": "Loading model",
    "采样": "Sampling",
    "VAE 解码": "VAE decoding",
    "文本编码": "Text encoding",
    "完成": "Done",
}