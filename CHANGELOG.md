# CHANGELOG

本项目所有对外可见的变更记录。格式：版本 → 日期 → 变更（逐文件说明动了什么）。

---

## v1.0.6 (2026-10-22)

**缺陷修复：全局同步不再拉起空 / 离线分区的引擎；后台初始化（boot）增加异常兜底并向前端提示失败原因；思考预算与思考统计由「流式块数」改为按 token 估算。**

### 修复
- backend/services/registry.py — 全局同步不再拉起未运行分区的引擎
- backend/context.py — boot 增加异常兜底并记录失败原因
- backend/routes/api_misc.py — bootstrap 下发启动失败原因
- web/static/js/app.js — 启动异常时向用户提示
- backend/services/chat.py — 思考预算与思考统计改为按 token 估算
- backend/i18n_parts/services.py — 补充启动失败相关英文词条
- web/static/js/i18n/en.app.js — 补充启动异常提示英文词条
- backend/__init__.py — 版本号升至 1.0.6
- CHANGELOG.md — 记录本次修复

## v1.0.3 (2026-10-22)

### 修复
- backend/core/config.py — 补登记生图提示词与反向提示词字段，避免保存后被静默丢弃
- backend/services/chat.py — 并发生成时按模型互斥，避免不同会话互相卸载模型
- web/static/js/core/api.js — 生成流永久失败或超重试上限时停止无限重连
- web/static/js/pages/chat.js — 生成中断时收尾气泡提示并恢复发送按钮
- backend/i18n_parts/services.py — 补充并发互斥提示的英文词条
- web/static/js/i18n/en.chat.js — 补充生成中断提示的英文词条
- backend/__init__.py — 版本号升至 1.0.3
- CHANGELOG.md — 记录本次修复

## V1.1.0 — 2026-10-22

**性能优化：修复 TUI 全屏仪表盘空闲时 CPU 偏高（常驻 15%~30%、风扇不停）的问题。**

- `backend/console.py`
  - `Dashboard.__init__`：新增 `_usage_cache`（`(写入时间戳, 今日字典, 累计字典)`）与 `_usage_ttl = 1.5`，用于缓存用量聚合结果。
  - `Dashboard._usage()`：改为在 TTL 内直接复用缓存的「今日 / 累计」两个聚合字典，不再每帧各做一次全表聚合（原为 25fps × 2 次/秒，与 usage 行数线性增长）；查询抛异常时同样写回空字典 + 当前时间戳，避免数据库被锁时退化为每帧重试。面板结构、尺寸、文案与后续 Table 构造逻辑一律未动。
  - `ConsoleUI.ready()`：把原先无效的 `self.live.refresh_per_second = 4`（rich 的 `Live.start()` 已把速率拷贝给 `_RefreshThread`，启动后改属性不生效）替换为：进入仪表盘（`mode="dash"`）后用 `getattr` 取到 Live 的私有刷新线程 `_refresh_thread`，调用其 `stop()`（仅 set Event，线程自然退出）并置为 `None`。取不到属性时静默跳过（退化为原 25fps，功能不受影响）；不使用 `stop()`/`start()`，避免退出备用屏幕造成的闪屏。
  - `ConsoleUI.loop()`：全屏分支由空转改为每 0.25 秒（4fps）主动调用 `self.live.refresh()`（异常静默吞掉），刷新节奏改由主循环驱动；`loop()` 非全屏首分支仍直接走 `_simple_loop`，`--plain` / 非 TTY / 小窗口行为不变。启动动画与 READY 爆破阶段仍保持 25fps。

**影响范围**：仅全屏仪表盘的刷新频率与用量聚合查询频率；不涉及业务功能、数据、接口、配置、依赖、主题与日志。

**验证**：usage 表 10 万行基准（临时目录自建库，未污染 `data/app.db`，用完即删）——空闲 2 分钟窗口实测进程 CPU（单核相对口径）由 **58.68% 降至 4.71%**（约 12.5 倍；按 20 核折算系统占比约 0.24%），单次聚合（今日 + 累计）63 ms，4fps 下纯渲染成本约 0.10%。

## v1.0.0
- 初始版本：本地 Ollama 模型与分区引擎管理、对话生成、用量统计与生图。